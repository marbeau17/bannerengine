"""Unit tests for app.core.xml_parser.XMLTemplateParser.

Test IDs follow the spec convention UT-XML-001 through UT-XML-012.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.exceptions import UnknownSlotTypeError, XMLParseError
from app.core.xml_parser import XMLTemplateParser
from app.models.template import BannerTemplate, SlotType

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def parser() -> XMLTemplateParser:
    return XMLTemplateParser()


# UT-XML-001
class TestParseValidTemplate:
    """UT-XML-001: Parsing a well-formed XML file returns a BannerTemplate."""

    def test_parse_valid_template(self, parser: XMLTemplateParser):
        templates = parser.parse_file(str(FIXTURES_DIR / "sample_car.xml"))

        assert isinstance(templates, list)
        assert len(templates) >= 1
        template = templates[0]
        assert isinstance(template, BannerTemplate)
        assert template.meta.pattern_id == "car_01"
        assert template.meta.category == "used_car"
        assert template.meta.width == 1200
        assert template.meta.height == 628
        assert len(template.slots) == 6
        assert len(template.rules) == 3


# UT-XML-002
class TestParseImageSlotAttributes:
    """UT-XML-002: Image slot attributes are parsed correctly."""

    def test_parse_image_slot_attributes(self, parser: XMLTemplateParser):
        template = parser.parse_file(str(FIXTURES_DIR / "sample_car.xml"))[0]
        image_slot = next(s for s in template.slots if s.id == "hero_image")

        assert image_slot.type == SlotType.IMAGE
        assert image_slot.x == 0.0
        assert image_slot.y == 0.0
        assert image_slot.width == 60.0
        assert image_slot.height == 100.0
        assert image_slot.required is True
        assert image_slot.description == "Main car photo"
        assert image_slot.format_hint is not None


# UT-XML-003
class TestParseTextSlotAttributes:
    """UT-XML-003: Text slot attributes are parsed correctly."""

    def test_parse_text_slot_attributes(self, parser: XMLTemplateParser):
        template = parser.parse_file(str(FIXTURES_DIR / "sample_car.xml"))[0]
        text_slot = next(s for s in template.slots if s.id == "headline")

        assert text_slot.type == SlotType.TEXT
        assert text_slot.x == 62.0
        assert text_slot.y == 10.0
        assert text_slot.width == 35.0
        assert text_slot.height == 15.0
        assert text_slot.required is True
        assert text_slot.max_chars == 30
        assert text_slot.font_size_guideline == "32px"
        assert text_slot.font_weight == "bold"
        assert text_slot.color == "#ffffff"


# UT-XML-004
class TestParseButtonSlotAttributes:
    """UT-XML-004: Button slot attributes are parsed correctly."""

    def test_parse_button_slot_attributes(self, parser: XMLTemplateParser):
        template = parser.parse_file(str(FIXTURES_DIR / "sample_car.xml"))[0]
        button_slot = next(s for s in template.slots if s.id == "cta_button")

        assert button_slot.type == SlotType.BUTTON
        assert button_slot.required is True
        assert button_slot.default_label == "View Details"
        assert button_slot.bg_color == "#e94560"
        assert button_slot.text_color == "#ffffff"
        assert button_slot.font_size_guideline == "16px"


# UT-XML-005
class TestParseImageOrTextSlot:
    """UT-XML-005: image_or_text slot is parsed with correct type."""

    def test_parse_image_or_text_slot(self, parser: XMLTemplateParser):
        template = parser.parse_file(str(FIXTURES_DIR / "sample_car.xml"))[0]
        iot_slot = next(s for s in template.slots if s.id == "logo")

        assert iot_slot.type == SlotType.IMAGE_OR_TEXT
        assert iot_slot.required is False
        assert iot_slot.max_chars == 20


# UT-XML-006
class TestMissingRequiredAttribute:
    """UT-XML-006: Missing <meta> or <design> section raises XMLParseError."""

    def test_missing_meta_raises(self, parser: XMLTemplateParser):
        xml = "<template><design><background_type>solid</background_type><primary_color>#000</primary_color><font_style>x</font_style></design></template>"
        with pytest.raises(XMLParseError, match="Missing <meta>"):
            parser.parse_string(xml)

    def test_missing_design_raises(self, parser: XMLTemplateParser):
        xml = (
            "<template><meta>"
            "<category>c</category><pattern_id>p</pattern_id>"
            "<pattern_name>n</pattern_name><width>100</width><height>100</height>"
            "</meta></template>"
        )
        with pytest.raises(XMLParseError, match="Missing <design>"):
            parser.parse_string(xml)


# UT-XML-007
class TestUnknownSlotType:
    """UT-XML-007: Unrecognised slot type raises UnknownSlotTypeError."""

    def test_unknown_slot_type(self, parser: XMLTemplateParser):
        xml = """<template>
          <meta>
            <category>t</category><pattern_id>p</pattern_id>
            <pattern_name>n</pattern_name><width>100</width><height>100</height>
          </meta>
          <design>
            <background_type>solid</background_type>
            <primary_color>#000</primary_color><font_style>x</font_style>
          </design>
          <slots>
            <slot><id>s1</id><type>video</type><x>0</x><y>0</y><width>10</width><height>10</height></slot>
          </slots>
        </template>"""
        with pytest.raises(UnknownSlotTypeError):
            parser.parse_string(xml)


# UT-XML-008
class TestMalformedXml:
    """UT-XML-008: Malformed XML raises XMLParseError."""

    def test_malformed_xml_file(self, parser: XMLTemplateParser):
        with pytest.raises(XMLParseError):
            parser.parse_file(str(FIXTURES_DIR / "invalid.xml"))

    def test_malformed_xml_string(self, parser: XMLTemplateParser):
        with pytest.raises(XMLParseError):
            parser.parse_string("<template><meta><unclosed>")


# UT-XML-009
class TestEmptyXml:
    """UT-XML-009: Empty or whitespace-only string raises XMLParseError."""

    def test_empty_string(self, parser: XMLTemplateParser):
        with pytest.raises(XMLParseError):
            parser.parse_string("")

    def test_whitespace_string(self, parser: XMLTemplateParser):
        with pytest.raises(XMLParseError):
            parser.parse_string("   \n\t  ")


# UT-XML-010
class TestZeroSlots:
    """UT-XML-010: Template with an empty <slots> section returns 0 slots."""

    def test_zero_slots(self, parser: XMLTemplateParser):
        templates = parser.parse_file(str(FIXTURES_DIR / "empty_slots.xml"))
        assert isinstance(templates, list)
        template = templates[0]
        assert isinstance(template, BannerTemplate)
        assert len(template.slots) == 0
        assert template.meta.pattern_id == "empty_slots_01"


# UT-XML-011
class TestSlotOrderPreserved:
    """UT-XML-011: Slot order matches the order defined in the XML."""

    def test_slot_order_preserved(self, parser: XMLTemplateParser):
        template = parser.parse_file(str(FIXTURES_DIR / "sample_car.xml"))[0]
        expected_order = [
            "hero_image",
            "headline",
            "price_tag",
            "description",
            "logo",
            "cta_button",
        ]
        actual_order = [s.id for s in template.slots]
        assert actual_order == expected_order


# UT-XML-012
class TestUnicodeHandling:
    """UT-XML-012: Unicode characters in slot descriptions are preserved."""

    def test_unicode_handling(self, parser: XMLTemplateParser):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <template>
          <meta>
            <category>test</category><pattern_id>unicode_01</pattern_id>
            <pattern_name>Unicode Test</pattern_name>
            <width>800</width><height>600</height>
          </meta>
          <design>
            <background_type>solid</background_type>
            <primary_color>#000</primary_color><font_style>default</font_style>
          </design>
          <slots>
            <slot>
              <id>title</id><type>text</type>
              <x>10</x><y>10</y><width>80</width><height>20</height>
              <description>Japanese: \u4e2d\u53e4\u8eca \u2014 Emoji: \u2764</description>
              <required>true</required>
            </slot>
          </slots>
        </template>"""
        template = parser.parse_string(xml)[0]
        slot = template.slots[0]
        assert "\u4e2d\u53e4\u8eca" in slot.description
        assert "\u2764" in slot.description
