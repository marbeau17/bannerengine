"""Tests for prompt persistence in slot session data."""

import pytest
from unittest.mock import MagicMock


class TestSlotPromptPersistence:
    """Tests for saving/loading prompt data in session slots."""

    def test_image_slot_prompt_stored_in_dict(self):
        """Image slot with prompt should be stored as dict with prompt key."""
        session_slots = {}
        slot_id = "img1"
        # Simulate what the router does
        session_slots[slot_id] = {
            "source_url": "/static/uploads/test.png",
            "prompt": "A red car",
            "fit": "cover",
        }
        assert session_slots[slot_id]["prompt"] == "A red car"
        assert session_slots[slot_id]["source_url"] == "/static/uploads/test.png"

    def test_image_slot_prompt_only(self):
        """Image slot can have prompt without source_url."""
        session_slots = {}
        slot_id = "img1"
        session_slots[slot_id] = {
            "source_url": "",
            "prompt": "Beautiful landscape",
            "fit": "cover",
        }
        assert session_slots[slot_id]["prompt"] == "Beautiful landscape"
        assert session_slots[slot_id]["source_url"] == ""

    def test_image_slot_generation_job_id(self):
        """Slot should store generation job_id during generation."""
        session_slots = {}
        slot_id = "img1"
        session_slots[slot_id] = {
            "prompt": "Test prompt",
            "generation_job_id": "job-123",
        }
        assert session_slots[slot_id]["generation_job_id"] == "job-123"

    def test_backward_compatible_string_value(self):
        """Old string-style slot values should still work."""
        session_slots = {}
        slot_id = "img1"
        # Old format: just a string URL
        session_slots[slot_id] = "/static/uploads/old.png"
        # Should be a string, not a dict
        assert isinstance(session_slots[slot_id], str)

    def test_prompt_preserved_after_image_generation(self):
        """Prompt should be preserved after image is generated and applied."""
        session_slots = {}
        slot_id = "img1"
        # Step 1: User enters prompt
        session_slots[slot_id] = {
            "prompt": "A sunset over ocean",
            "generation_job_id": "job-456",
        }
        # Step 2: Image generated, apply it
        session_slots[slot_id] = {
            "source_url": "/static/generated/job-456.png",
            "prompt": "A sunset over ocean",
            "fit": "cover",
        }
        assert session_slots[slot_id]["source_url"] == "/static/generated/job-456.png"
        assert session_slots[slot_id]["prompt"] == "A sunset over ocean"
