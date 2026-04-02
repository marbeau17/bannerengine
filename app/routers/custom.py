"""Custom banner routes — upload image, AI analyzes it into editable template."""

from __future__ import annotations

import io
import logging
import os
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image

from app.core.exceptions import AssetUploadError
from app.routers.assets import _detect_mime_from_bytes, ALLOWED_TYPES, MAX_UPLOAD_SIZE, UPLOAD_DIR, MIME_TO_EXT

logger = logging.getLogger("banner_engine")

router = APIRouter(prefix="/api/custom", tags=["custom"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/upload-form", response_class=HTMLResponse)
async def upload_form(request: Request):
    """Return the custom banner upload form partial."""
    return templates.TemplateResponse(request, "partials/custom_upload.html", {})


@router.post("/upload", response_class=HTMLResponse)
async def upload_and_analyze(request: Request):
    """Upload a banner image, analyze it with AI, create a template, redirect to editor."""
    form = await request.form()
    file = form.get("file")

    if file is None or not hasattr(file, "read"):
        return _error_html(request, "画像ファイルを選択してください。")

    file_bytes = await file.read()

    # Validate
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        return _error_html(request, "ファイルが大きすぎます（最大10MB）。")
    if len(file_bytes) < 12:
        return _error_html(request, "無効なファイルです。")

    content_type = _detect_mime_from_bytes(file_bytes)
    if not content_type or content_type not in ALLOWED_TYPES:
        return _error_html(request, "JPEG、PNG、WebPのみ対応しています。")

    # Detect dimensions
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img_width, img_height = img.size
    except Exception:
        return _error_html(request, "画像を読み込めませんでした。")

    # Save file
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    asset_id = str(uuid.uuid4())
    ext = MIME_TO_EXT.get(content_type, ".png")
    filename = f"{asset_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(file_bytes)
    file_url = f"/static/uploads/{filename}"

    # Send to AI for analysis
    nano_client = request.app.state.nano_banana_client
    try:
        xml_string = await nano_client.analyze_banner(file_bytes, img_width, img_height, content_type)
    except Exception as exc:
        logger.error("AI analysis failed: %s", exc)
        return _error_html(request, f"AI分析に失敗しました: {exc}")

    if not xml_string or not xml_string.strip():
        return _error_html(request, "AIから有効な応答がありませんでした。")

    # Parse XML into BannerTemplate
    from app.core.xml_parser import XMLTemplateParser
    parser = XMLTemplateParser()
    try:
        parsed_templates = parser.parse_string(xml_string)
    except Exception as exc:
        logger.error("XML parse failed: %s\nRaw XML:\n%s", exc, xml_string[:500])
        return _error_html(
            request,
            f"AIが生成したXMLの解析に失敗しました。もう一度お試しください。",
            detail=str(xml_string[:300]),
        )

    if not parsed_templates:
        return _error_html(request, "テンプレートが生成されませんでした。")

    template = parsed_templates[0]

    # Override pattern_id to ensure uniqueness
    custom_id = f"custom_{uuid.uuid4().hex[:8]}"
    template.meta.pattern_id = custom_id
    template.meta.width = img_width
    template.meta.height = img_height
    template.meta.category = "custom"

    # Register template
    template_service = request.app.state.template_service
    template_service.register_template(template)

    # Pre-fill slot values from detected content (default_label)
    slot_values = {}
    for slot in template.slots:
        if slot.type.value == "text" and slot.default_label:
            slot_values[slot.id] = {"text": slot.default_label}
        elif slot.type.value == "button" and slot.default_label:
            slot_values[slot.id] = {
                "label": slot.default_label,
                "bg_color": slot.bg_color or "#333333",
                "text_color": slot.text_color or "#ffffff",
            }
        elif slot.type.value == "image":
            # Use the original uploaded image as placeholder for image slots
            slot_values[slot.id] = {"source_url": file_url, "prompt": "", "fit": "cover"}

    request.session[f"slots_{custom_id}"] = slot_values
    request.session[f"custom_ref_{custom_id}"] = file_url

    # Redirect to editor
    return HTMLResponse(
        content="",
        status_code=200,
        headers={"HX-Redirect": f"/editor/{custom_id}"},
    )


def _error_html(request: Request, message: str, detail: str | None = None) -> HTMLResponse:
    """Return an error HTML partial for the upload form."""
    html = f'''
    <div class="space-y-2">
      <div class="flex items-start gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg">
        <svg class="w-4 h-4 text-red-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
        <div>
          <p class="text-xs font-medium text-red-700">{message}</p>
          {f'<pre class="mt-1 text-[10px] text-red-400 whitespace-pre-wrap max-h-20 overflow-auto">{detail}</pre>' if detail else ''}
        </div>
      </div>
      <button
        type="button"
        onclick="document.getElementById('custom-upload-input').click()"
        class="w-full py-2 px-4 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-lg transition-colors"
      >もう一度試す</button>
    </div>
    '''
    return HTMLResponse(content=html)
