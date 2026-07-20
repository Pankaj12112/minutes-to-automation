"""Application configuration via environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized settings loaded from environment variables or a .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Meeting Intelligence Pipeline"
    debug: bool = False
    log_level: str = "INFO"

    # OpenAI
    openai_api_key: str = Field(..., description="OpenAI API key for GPT-4o extraction")
    openai_model: str = "gpt-4o"

    # Transcription provider: "assemblyai" or "deepgram"
    transcription_provider: Literal["assemblyai", "deepgram"] = "assemblyai"
    assemblyai_api_key: str | None = None
    deepgram_api_key: str | None = None

    # Contact directory for resolving spoken names to office emails.
    # JSON object, e.g. {"Alice Johnson": "alice@company.com", "Bob Smith": "bob@company.com"}
    contact_directory_json: str = "{}"
    unknown_email_placeholder: str = "unknown@company.com"

    # Notification settings
    notification_mode: Literal["webhook", "email", "both"] = "webhook"
    webhook_url: str | None = None
    webhook_timeout_seconds: int = 30

    # SMTP (used when notification_mode is "email" or "both")
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_email: str | None = None

    @field_validator("transcription_provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()

    def validate_transcription_credentials(self) -> None:
        """Ensure the selected transcription provider has a configured API key."""
        if self.transcription_provider == "assemblyai" and not self.assemblyai_api_key:
            raise ValueError("ASSEMBLYAI_API_KEY is required when transcription_provider=assemblyai")
        if self.transcription_provider == "deepgram" and not self.deepgram_api_key:
            raise ValueError("DEEPGRAM_API_KEY is required when transcription_provider=deepgram")

    def validate_notification_settings(self) -> None:
        """Ensure notification transport settings are present for the selected mode."""
        if self.notification_mode in {"webhook", "both"} and not self.webhook_url:
            raise ValueError("WEBHOOK_URL is required when notification_mode is webhook or both")
        if self.notification_mode in {"email", "both"}:
            missing = [
                name
                for name, value in {
                    "SMTP_HOST": self.smtp_host,
                    "SMTP_FROM_EMAIL": self.smtp_from_email,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} required when notification_mode is email or both"
                )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
