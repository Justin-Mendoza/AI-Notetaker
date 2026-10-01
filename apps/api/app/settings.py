import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://meeting_notes:change-me@localhost:5432/meeting_notes"
    )
    allowed_web_origin: str = os.getenv("ALLOWED_WEB_ORIGIN", "http://localhost:3000")
    local_recording_dir: str = os.getenv("LOCAL_RECORDING_DIR", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    stt_provider: str = os.getenv("STT_PROVIDER", "openai")
    stt_model: str = os.getenv("STT_MODEL", "gpt-4o-transcribe")
    whisper_local_base_url: str = os.getenv("WHISPER_LOCAL_BASE_URL", "http://127.0.0.1:7777/v1")
    whisper_local_model_label: str = os.getenv("WHISPER_LOCAL_MODEL_LABEL", "base")
    summary_provider: str = os.getenv("SUMMARY_PROVIDER", "openai")
    summary_model: str = os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
    kyma_api_key: str = os.getenv("KYMA_API_KEY", "")
    kyma_base_url: str = os.getenv("KYMA_BASE_URL", "https://kymaapi.com/v1")
    kyma_summary_model: str = os.getenv("KYMA_SUMMARY_MODEL", "qwen3.7-flash")
    raw_audio_retention_hours: int = int(os.getenv("RAW_AUDIO_RETENTION_HOURS", "24"))
    failed_audio_retention_days: int = int(os.getenv("FAILED_AUDIO_RETENTION_DAYS", "7"))
    max_meetings_per_hour: int = int(os.getenv("MAX_MEETINGS_PER_HOUR", "20"))
    max_uploads_per_hour: int = int(os.getenv("MAX_UPLOADS_PER_HOUR", "10"))
    max_manual_retries_per_hour: int = int(os.getenv("MAX_MANUAL_RETRIES_PER_HOUR", "3"))
    metrics_token: str = os.getenv("METRICS_TOKEN", "")


settings = Settings()
