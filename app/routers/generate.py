"""Banner generation routes - start jobs and stream progress via SSE."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.exceptions import TemplateNotFoundError, ValidationError

logger = logging.getLogger("banner_engine")

router = APIRouter(prefix="/api/generate", tags=["generate"])

# In-memory job store for the MVP. Maps job_id -> job state dict.
_jobs: dict[str, dict] = {}


@router.post("/{pattern_id}", status_code=202)
async def start_generation(request: Request, pattern_id: str):
    """Start a banner generation job.

    Validates that all required slots are filled, creates a render
    instruction via BannerService, and returns a 202 Accepted response
    with the job_id. For the MVP this uses a mock flow since Nano
    Banana Pro may not be available.
    """
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)



    slot_values = request.session.get(f"slots_{pattern_id}", {})

    # Validate all required slots are filled
    missing_slots = []
    for slot in template.slots:
        if slot.required and slot.id not in slot_values:
            missing_slots.append(slot.id)

    if missing_slots:
        raise ValidationError(
            message="Some required slots are not filled.",
            errors=[f"Missing required slot: {s}" for s in missing_slots],
        )

    # Create a job entry
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "pattern_id": pattern_id,
        "status": "queued",
        "progress": 0,
        "file_url": None,
        "slot_values": slot_values,
    }

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "message": "Banner generation started.",
        },
    )


@router.get("/progress/{job_id}")
async def generation_progress(job_id: str):
    """SSE endpoint for generation progress.

    Streams Server-Sent Events with progress updates. For the MVP this
    simulates progress with asyncio.sleep increments, advancing from
    0 to 100 before sending a completed event with a placeholder file URL.
    """
    if job_id not in _jobs:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Job not found: {job_id}"},
        )

    async def event_stream():
        job = _jobs[job_id]
        job["status"] = "processing"

        # Simulate progress in increments
        for progress in range(0, 101, 10):
            job["progress"] = progress
            event_data = json.dumps({
                "status": "processing",
                "progress": progress,
            })
            yield f"data: {event_data}\n\n"
            await asyncio.sleep(0.3)

        # Mark as completed with a placeholder file URL
        file_url = f"/static/generated/{job_id}.png"
        job["status"] = "completed"
        job["progress"] = 100
        job["file_url"] = file_url

        completed_data = json.dumps({
            "status": "completed",
            "progress": 100,
            "file_url": file_url,
        })
        yield f"data: {completed_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
