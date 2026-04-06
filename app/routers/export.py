"""Multi-format image export — serve generated PNGs as JPEG (with white BG flattening)."""

from __future__ import annotations

import io
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter(prefix="/api/export", tags=["export"])

_GENERATED_DIR = os.path.join("static", "generated")


@router.get("/{filename}")
async def export_image(filename: str, format: str = "png"):
    """Export a generated file in the requested format.

    Supported formats:
    - ``png``  — return the file as-is (default)
    - ``jpeg`` — flatten any transparency to white, re-encode as JPEG 90%

    Only files inside ``static/generated/`` may be served; path traversal is
    rejected by taking only the basename.
    """
    safe_name = os.path.basename(filename)
    file_path = os.path.join(_GENERATED_DIR, safe_name)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Generated file not found")

    if format.lower() == "jpeg":
        try:
            from PIL import Image
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="Pillow is not installed") from exc

        with Image.open(file_path) as img:
            # Flatten any alpha channel onto white
            if img.mode in ("RGBA", "LA", "P"):
                if img.mode == "P":
                    img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                mask = img.split()[-1] if img.mode in ("RGBA", "LA") else None
                background.paste(img, mask=mask)
                img = background
            else:
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90, optimize=True)
            buf.seek(0)

        output_name = os.path.splitext(safe_name)[0] + ".jpg"
        return StreamingResponse(
            buf,
            media_type="image/jpeg",
            headers={"Content-Disposition": f'attachment; filename="{output_name}"'},
        )

    # Default: serve the PNG directly
    return FileResponse(
        file_path,
        media_type="image/png",
        filename=safe_name,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )
