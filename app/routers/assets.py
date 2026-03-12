"""Asset / file upload routes."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import JSONResponse

from app.core.exceptions import AssetUploadError

logger = logging.getLogger("banner_engine")

router = APIRouter(prefix="/api/assets", tags=["assets"])

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
async def upload_asset(request: Request, file: UploadFile = File(...)):
    """Upload an image file.

    Validates file type (JPEG, PNG, WebP only), file size (max 10 MB),
    and magic bytes. Saves to static/uploads/ with a UUID filename.
    Returns JSON with file_url and metadata.
    """
    # Validate MIME type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES:
        raise AssetUploadError(
            f"Unsupported file type: {content_type}. "
            "Allowed types: JPEG, PNG, WebP."
        )

    # Read file content
    file_bytes = await file.read()

    # Validate file size
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise AssetUploadError(
            f"File too large ({len(file_bytes)} bytes). Maximum size is 10 MB."
        )

    # Validate magic bytes
    if len(file_bytes) < 12:
        raise AssetUploadError("File is too small to be a valid image.")

    if not _validate_magic_bytes(file_bytes, content_type):
        raise AssetUploadError(
            "File content does not match the declared MIME type. "
            "The file may be corrupted or mislabeled."
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
        "original_filename": file.filename or "unknown",
        "content_type": content_type,
        "size": len(file_bytes),
        "file_url": file_url,
        "filename": safe_filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    session_assets.append(asset_meta)
    request.session["assets"] = session_assets

    return JSONResponse(
        status_code=201,
        content={
            "asset_id": asset_id,
            "file_url": file_url,
            "original_filename": file.filename or "unknown",
            "content_type": content_type,
            "size": len(file_bytes),
        },
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
