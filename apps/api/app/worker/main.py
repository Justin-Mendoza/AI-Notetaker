import logging
import socket
import time
import uuid

from app.db.session import SessionLocal
from app.observability import configure_logging
from app.services.storage import get_storage
from app.services.summarization import OpenAISummarizer
from app.services.transcription import OpenAITranscriber
from app.worker.runner import requeue_incomplete_summaries, run_once


def main() -> None:
    configure_logging()
    worker_id = f"{socket.gethostname()}-{uuid.uuid4()}"
    storage = get_storage()
    transcriber = OpenAITranscriber()
    summarizer = OpenAISummarizer()
    requeue_incomplete_summaries(SessionLocal)
    logging.info("worker started id=%s", worker_id)
    while True:
        if not run_once(worker_id, SessionLocal, storage, transcriber, summarizer=summarizer):
            time.sleep(2)


if __name__ == "__main__":
    main()
