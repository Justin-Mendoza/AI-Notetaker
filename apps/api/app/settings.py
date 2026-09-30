import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://meeting_notes:change-me@localhost:5432/meeting_notes"
    )
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_jwt_audience: str = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    allowed_web_origin: str = os.getenv("ALLOWED_WEB_ORIGIN", "http://localhost:3000")
    bucket_endpoint: str = os.getenv("BUCKET_ENDPOINT", "http://localhost:9000")
    bucket_name: str = os.getenv("BUCKET_NAME", "meeting-audio")
    bucket_access_key: str = os.getenv("BUCKET_ACCESS_KEY", "")
    bucket_secret_key: str = os.getenv("BUCKET_SECRET_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    stt_model: str = os.getenv("STT_MODEL", "gpt-4o-transcribe")
    summary_model: str = os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
    raw_audio_retention_hours: int = int(os.getenv("RAW_AUDIO_RETENTION_HOURS", "24"))
    failed_audio_retention_days: int = int(os.getenv("FAILED_AUDIO_RETENTION_DAYS", "7"))
    max_meetings_per_hour: int = int(os.getenv("MAX_MEETINGS_PER_HOUR", "20"))
    max_uploads_per_hour: int = int(os.getenv("MAX_UPLOADS_PER_HOUR", "10"))
    max_manual_retries_per_hour: int = int(os.getenv("MAX_MANUAL_RETRIES_PER_HOUR", "3"))
    metrics_token: str = os.getenv("METRICS_TOKEN", "")

    @property
    def issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    def validate_auth(self) -> None:
        parsed = urlparse(self.supabase_url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError("SUPABASE_URL must use HTTPS, except for local Supabase Auth")
        if not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("SUPABASE_URL must be a project base URL")
        if not self.supabase_jwt_audience:
            raise ValueError("SUPABASE_JWT_AUDIENCE is required")


settings = Settings()
