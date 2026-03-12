"""Custom exceptions for the Banner Engine application."""


class XMLParseError(Exception):
    """Raised when XML template parsing fails."""

    def __init__(self, message: str = "Failed to parse XML template"):
        self.message = message
        super().__init__(self.message)


class UnknownSlotTypeError(XMLParseError):
    """Raised when an unknown slot type is encountered in XML."""

    def __init__(self, slot_type: str):
        self.slot_type = slot_type
        super().__init__(f"Unknown slot type: {slot_type}")


class TemplateNotFoundError(Exception):
    """Raised when a requested template cannot be found."""

    def __init__(self, template_id: str = ""):
        self.template_id = template_id
        message = f"Template not found: {template_id}" if template_id else "Template not found"
        self.message = message
        super().__init__(self.message)


class ValidationError(Exception):
    """Raised when input validation fails."""

    def __init__(self, message: str = "Validation error", errors: list | None = None):
        self.message = message
        self.errors = errors or []
        super().__init__(self.message)


class GenerationError(Exception):
    """Raised when banner generation fails."""

    def __init__(self, message: str = "Banner generation failed"):
        self.message = message
        super().__init__(self.message)


class AssetUploadError(Exception):
    """Raised when asset upload fails."""

    def __init__(self, message: str = "Asset upload failed"):
        self.message = message
        super().__init__(self.message)
