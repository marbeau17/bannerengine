"""Pydantic models for slot values used in banner rendering."""

from typing import Optional

from pydantic import BaseModel


class SlotValue(BaseModel):
    """Base slot value model."""

    model_config = {"strict": False}

    slot_id: str
    slot_type: str


class TextSlotValue(SlotValue):
    """Value for a text slot."""

    slot_type: str = "text"
    text: str
    font_size: Optional[int] = None
    color: Optional[str] = None
    font_weight: Optional[str] = None


class ImageSlotValue(SlotValue):
    """Value for an image slot."""

    slot_type: str = "image"
    image_url: str
    fit: str = "cover"


class ButtonSlotValue(SlotValue):
    """Value for a button slot."""

    slot_type: str = "button"
    label: str
    bg_color: Optional[str] = None
    text_color: Optional[str] = None
    link_url: Optional[str] = None
