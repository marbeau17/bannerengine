"""Asset / file upload routes."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import AssetUploadError

logger = logging.getLogger("banner_engine")

router = APIRouter(prefix="/api/assets", tags=["assets"])

templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = os.path.join("static", "uploads")

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

# Allowed MIME types and their corresponding magic bytes
ALLOWED_TYPES: dict[str, bytes] = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89\x50\x4e\x47",
    "image/webp": b"\x52\x49\x46\x46",
}

# Map MIME type to file extension
MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _validate_magic_bytes(header: bytes, content_type: str) -> bool:
    """Check that the file header matches the expected magic bytes."""
    expected = ALLOWED_TYPES.get(content_type)
    if expected is None:
        return False
    # WebP files start with RIFF....WEBP - check the first 4 bytes
    if content_type == "image/webp":
        return header[:4] == expected and header[8:12] == b"WEBP"
    return header[: len(expected)] == expected


@router.post("/upload")
async def upload_asset(request: Request):
    """Upload an image file and update the slot preview.

    Validates file type (JPEG, PNG, WebP only), file size (max 10 MB),
    and magic bytes. Saves to static/uploads/ with a UUID filename.
    If slot_id and pattern_id are provided, updates the slot value in
    the session and returns the re-rendered preview canvas.
    """
    try:
        form = await request.form()
    except Exception as exc:
        logger.error("Form parse failed: %s: %s", type(exc).__name__, exc)
        return JSONResponse(status_code=400, content={"detail": f"Form parse error: {exc}"})

    file = form.get("file")
    slot_id = str(form.get("slot_id", "") or "")
    pattern_id = str(form.get("pattern_id", "") or "")

    if file is None or not hasattr(file, "read"):
        raise AssetUploadError("No file uploaded.")

    # Read file content first so we can detect type from bytes if needed
    file_bytes = await file.read()
    content_type_attr = getattr(file, "content_type", "") or ""
    filename_attr = getattr(file, "filename", "") or ""

    # Determine MIME type — try declared, then extension, then magic bytes
    content_type = content_type_attr
    if content_type not in ALLOWED_TYPES:
        ext_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        for ext, mime in ext_map.items():
            if filename_attr.lower().endswith(ext):
                content_type = mime
                break
    if content_type not in ALLOWED_TYPES and len(file_bytes) >= 12:
        # Detect from magic bytes
        if file_bytes[:3] == b"\xff\xd8\xff":
            content_type = "image/jpeg"
        elif file_bytes[:4] == b"\x89PNG":
            content_type = "image/png"
        elif file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
            content_type = "image/webp"
    if content_type not in ALLOWED_TYPES:
        raise AssetUploadError(
            f"Unsupported file type: {content_type or 'unknown'}. "
            "Allowed types: JPEG, PNG, WebP."
        )

    # Validate file size
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise AssetUploadError(
            f"File too large ({len(file_bytes)} bytes). Maximum size is 10 MB."
        )

    # Validate magic bytes
    if len(file_bytes) < 12:
        raise AssetUploadError("File is too small to be a valid image.")

    if not _validate_magic_bytes(file_bytes, content_type):
        # Try detecting actual type from bytes and use that instead
        detected = None
        if file_bytes[:3] == b"\xff\xd8\xff":
            detected = "image/jpeg"
        elif file_bytes[:4] == b"\x89PNG":
            detected = "image/png"
        elif file_bytes[:4] == b"RIFF" and len(file_bytes) > 11 and file_bytes[8:12] == b"WEBP":
            detected = "image/webp"
        if detected and detected in ALLOWED_TYPES:
            content_type = detected
        else:
            raise AssetUploadError(
                "Unsupported or corrupted image file. "
                "Allowed types: JPEG, PNG, WebP."
            )

    # Generate a safe UUID filename
    asset_id = str(uuid.uuid4())
    ext = MIME_TO_EXT.get(content_type, "")
    safe_filename = f"{asset_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Save file
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    file_url = f"/static/uploads/{safe_filename}"

    # Store asset metadata in session
    session_assets: list[dict] = request.session.get("assets", [])
    asset_meta = {
        "asset_id": asset_id,
        "original_filename": filename_attr or "unknown",
        "content_type": content_type,
        "size": len(file_bytes),
        "file_url": file_url,
        "filename": safe_filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    session_assets.append(asset_meta)
    request.session["assets"] = session_assets

    # If slot_id and pattern_id provided, update the slot and return preview
    if slot_id and pattern_id:
        session_slots = request.session.get(f"slots_{pattern_id}", {})
        session_slots[slot_id] = {
            "source_url": file_url,
            "prompt": session_slots.get(slot_id, {}).get("prompt", "") if isinstance(session_slots.get(slot_id), dict) else "",
            "fit": "cover",
        }
        request.session[f"slots_{pattern_id}"] = session_slots

        # Re-render preview
        template_service = request.app.state.template_service
        svg_renderer = request.app.state.svg_renderer
        template = template_service.get_template(pattern_id)
        svg_markup = svg_renderer.render(template, session_slots)

        return templates.TemplateResponse(
            request,
            "partials/preview_canvas.html",
            {
                "template": template,
                "pattern_id": pattern_id,
                "svg_markup": svg_markup,
            },
        )

    # Fallback: return JSON for non-slot uploads
    return HTMLResponse(
        content=f'<div class="text-xs text-green-600">Uploaded: {file_url}</div>',
        status_code=201,
    )


@router.get("")
async def list_assets(request: Request):
    """List uploaded assets for the current session."""
    session_assets: list[dict] = request.session.get("assets", [])
    return JSONResponse(content={"assets": session_assets})


@router.delete("/{asset_id}")
async def delete_asset(request: Request, asset_id: str):
    """Delete an uploaded asset by its ID.

    Removes the file from disk and removes the metadata from the session.
    """
    session_assets: list[dict] = request.session.get("assets", [])

    # Find the asset in the session
    target = None
    for asset in session_assets:
        if asset["asset_id"] == asset_id:
            target = asset
            break

    if target is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Asset not found: {asset_id}"},
        )

    # Remove file from disk
    file_path = os.path.join(UPLOAD_DIR, target["filename"])
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError as exc:
            logger.warning("Could not delete file %s: %s", file_path, exc)

    # Remove from session
    session_assets = [a for a in session_assets if a["asset_id"] != asset_id]
    request.session["assets"] = session_assets

    return JSONResponse(content={"detail": "Asset deleted.", "asset_id": asset_id})
