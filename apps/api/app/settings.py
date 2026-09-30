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
