"""Pydantic models for banner templates."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class SlotType(str, Enum):
    """Enumeration of supported slot types."""

    IMAGE = "image"
    TEXT = "text"
    BUTTON = "button"
    IMAGE_OR_TEXT = "image_or_text"


class TemplateMeta(BaseModel):
    """Metadata section of a banner template."""

    model_config = {"strict": False}

    category: str
    pattern_id: str
    pattern_name: str
    width: int
    height: int
    unit: str = "px"
    aspect_ratio: str = ""
    layout_type: str = ""
    recommended_use: str = ""


class TemplateDesign(BaseModel):
    """Design section of a banner template."""

    model_config = {"strict": False}

    background_type: str
    background_value: Optional[str] = None
    overlay_type: Optional[str] = None
    overlay_opacity: Optional[float] = None
    primary_color: str
    accent_color: Optional[str] = None
    font_style: str
    highlight_panel: Optional[str] = None
    illustration_style: Optional[str] = None


class Slot(BaseModel):
    """A single slot (placeholder) within a banner template."""

    model_config = {"strict": False}

    id: str
    type: SlotType
    x: float
    y: float
    width: float
    height: float
    description: str = ""
    required: bool = True

    # Text-specific optional fields
    max_chars: Optional[int] = None
    font_size_guideline: Optional[str] = None
    font_weight: Optional[str] = None
    color: Optional[str] = None

    # Button-specific optional fields
    default_label: Optional[str] = None
    bg_color: Optional[str] = None
    text_color: Optional[str] = None

    # General optional fields
    format_hint: Optional[str] = None


class BannerTemplate(BaseModel):
    """Complete banner template parsed from XML."""

    model_config = {"strict": False}

    meta: TemplateMeta
    design: TemplateDesign
    slots: list[Slot]
    rules: list[str]
