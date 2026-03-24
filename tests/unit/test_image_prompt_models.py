"""Tests for image prompt model fields."""

import pytest
from app.models.slot import ImageSlotValue, SlotValue
from app.models.template import Slot, SlotType


class TestImageSlotValuePrompt:
    """Tests for prompt field on ImageSlotValue."""

    def test_image_slot_value_with_prompt(self):
        """ImageSlotValue should accept a prompt field."""
        val = ImageSlotValue(
            slot_id="img1",
            slot_type="image",
            image_url="http://example.com/img.png",
            prompt="A red sports car on white background",
        )
        assert val.prompt == "A red sports car on white background"
        assert val.image_url == "http://example.com/img.png"

    def test_image_slot_value_prompt_optional(self):
        """Prompt should be optional and default to None."""
        val = ImageSlotValue(
            slot_id="img1",
            slot_type="image",
        )
        assert val.prompt is None

    def test_image_slot_value_generation_model(self):
        """generation_model should default to nano-bannara-pro-2."""
        val = ImageSlotValue(
            slot_id="img1",
            slot_type="image",
        )
        assert val.generation_model == "nano-bannara-pro-2"

    def test_image_slot_value_custom_model(self):
        """generation_model should be overridable."""
        val = ImageSlotValue(
            slot_id="img1",
            slot_type="image",
            generation_model="custom-model",
        )
        assert val.generation_model == "custom-model"

    def test_image_slot_value_image_url_optional(self):
        """image_url should be optional for prompt-based generation."""
        val = ImageSlotValue(
            slot_id="img1",
            slot_type="image",
            prompt="A beautiful sunset",
        )
        assert val.image_url is None
        assert val.prompt == "A beautiful sunset"

    def test_image_slot_value_with_both(self):
        """Should support both image_url and prompt."""
        val = ImageSlotValue(
            slot_id="img1",
            slot_type="image",
            image_url="/static/generated/abc.png",
            prompt="A red car",
        )
        assert val.image_url == "/static/generated/abc.png"
        assert val.prompt == "A red car"


class TestSlotPromptFields:
    """Tests for prompt-related fields on Slot model."""

    def test_slot_prompt_placeholder(self):
        """Slot should have prompt_placeholder field."""
        slot = Slot(
            id="img1",
            type=SlotType.IMAGE,
            x=0, y=0, width=100, height=50,
            prompt_placeholder="赤いスポーツカーの写真",
        )
        assert slot.prompt_placeholder == "赤いスポーツカーの写真"

    def test_slot_prompt_placeholder_default(self):
        """prompt_placeholder should default to None."""
        slot = Slot(
            id="img1",
            type=SlotType.IMAGE,
            x=0, y=0, width=100, height=50,
        )
        assert slot.prompt_placeholder is None

    def test_slot_allow_ai_generation_default(self):
        """allow_ai_generation should default to True."""
        slot = Slot(
            id="img1",
            type=SlotType.IMAGE,
            x=0, y=0, width=100, height=50,
        )
        assert slot.allow_ai_generation is True

    def test_slot_allow_ai_generation_false(self):
        """allow_ai_generation should be settable to False."""
        slot = Slot(
            id="img1",
            type=SlotType.IMAGE,
            x=0, y=0, width=100, height=50,
            allow_ai_generation=False,
        )
        assert slot.allow_ai_generation is False
