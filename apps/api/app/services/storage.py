import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.errors import ApiError
from app.settings import settings

OBJECT_KEY = re.compile(r"[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}\.(?:webm|ogg|m4a|wav|mp3)")
DEFAULT_ROOT = Path(__file__).resolve().parents[4] / ".data" / "recordings"


class Storage:
    """Private recordings on this Mac, shared by the API and worker."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root or settings.local_recording_dir or DEFAULT_ROOT).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def _path(self, key: str) -> Path:
        if not OBJECT_KEY.fullmatch(key):
            raise ApiError(500, "STORAGE_KEY_INVALID", "Stored recording key is invalid")
        path = self.root / key
        if not path.resolve().is_relative_to(self.root):
            raise ApiError(500, "STORAGE_KEY_INVALID", "Stored recording key is invalid")
        return path

    def upload(self, path: Path, key: str, mime_type: str) -> None:
        destination = self._path(key)
        temporary_path = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.parent.chmod(0o700)
            destination.parent.parent.chmod(0o700)
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                with path.open("rb") as source:
                    shutil.copyfileobj(source, temporary)
            temporary_path.chmod(0o600)
            os.replace(temporary_path, destination)
        except OSError as exc:
            raise ApiError(
                503, "STORAGE_UPLOAD_FAILED", "Recording storage is unavailable"
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        for directory in (path.parent, path.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                pass

    def download(self, key: str, path: Path) -> None:
        shutil.copyfile(self._path(key), path)

    def list_objects(self) -> Iterator[tuple[str, datetime]]:
        if not self.root.exists():
            return
        for path in self.root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            key = path.relative_to(self.root).as_posix()
            if OBJECT_KEY.fullmatch(key):
                yield key, datetime.fromtimestamp(path.stat().st_mtime, UTC)


@lru_cache
def get_storage() -> Storage:
    return Storage()
