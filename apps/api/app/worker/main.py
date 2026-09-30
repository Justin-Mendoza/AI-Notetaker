import logging
import socket
import time
import uuid

from app.db.session import SessionLocal
from app.services.storage import get_storage
from app.services.transcription import OpenAITranscriber
from app.worker.runner import run_once


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    worker_id = f"{socket.gethostname()}-{uuid.uuid4()}"
    storage = get_storage()
    transcriber = OpenAITranscriber()
    logging.info("worker started id=%s", worker_id)
    while True:
        if not run_once(worker_id, SessionLocal, storage, transcriber):
            time.sleep(2)


if __name__ == "__main__":
    main()
