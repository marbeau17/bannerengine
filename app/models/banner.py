"""Pydantic models for banner projects and render instructions."""

from typing import Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """Request model for creating a new banner project."""

    template_id: str
    title: str


class ProjectResponse(BaseModel):
    """Response model for a banner project."""

    id: str
    template_id: str
    title: str
    status: str
    created_at: str
    updated_at: str


class SlotEditRequest(BaseModel):
    """Request model for editing a single slot value."""

    slot_id: str
    slot_type: str
    content: dict


class GenerateRequest(BaseModel):
    """Request model for submitting a banner generation job."""

    project_id: str
    format: str = "png"
    quality: int = 95
    dpi: int = 144


class GenerateResponse(BaseModel):
    """Response model for a banner generation job status."""

    job_id: str
    status: str
    progress: int = 0
    file_url: Optional[str] = None
    error: Optional[str] = None


class RenderInstruction(BaseModel):
    """Nano Banana Pro render instruction format.

    Describes the full rendering specification including canvas settings
    and an ordered list of layers to composite.
    """

    schema_version: str = "1.0"
    canvas: dict = Field(
        ...,
        description="Canvas settings: width, height, background_color, format, quality, dpi",
    )
    layers: list[dict] = Field(
        default_factory=list,
        description=(
            "Ordered list of layer dicts. Each layer has: layer_id, type, z_index, "
            "position, size, and type-specific details (image/text/rect)"
        ),
    )
