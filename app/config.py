from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    DATABASE_URL: str = ""
    NANO_BANANA_API_KEY: str = ""
    NANO_BANANA_API_URL: str = ""
    GEMINI_API_KEY: str = ""
    SESSION_SECRET_KEY: str = ""
    BLOB_READ_WRITE_TOKEN: str = ""

    ALLOWED_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])
    MAX_UPLOAD_SIZE_MB: int = 10
    DEBUG: bool = False
    APP_NAME: str = "Banner Engine"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


settings = Settings()
