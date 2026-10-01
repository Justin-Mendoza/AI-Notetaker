import uuid

import pytest

from app.errors import ApiError
from app.services.storage import Storage


def test_local_recording_lifecycle(tmp_path):
    storage = Storage(tmp_path / "private-recordings")
    key = f"{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}.webm"
    source = tmp_path / "source.webm"
    source.write_bytes(b"non-sensitive test audio")

    storage.upload(source, key, "audio/webm")
    destination = storage.root / key
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o600
    assert storage.root.stat().st_mode & 0o777 == 0o700
    assert [item[0] for item in storage.list_objects()] == [key]

    downloaded = tmp_path / "downloaded.webm"
    storage.download(key, downloaded)
    assert downloaded.read_bytes() == source.read_bytes()
    storage.delete(key)
    storage.delete(key)
    assert list(storage.list_objects()) == []


def test_local_recording_rejects_unsafe_key(tmp_path):
    storage = Storage(tmp_path / "private-recordings")
    with pytest.raises(ApiError) as error:
        storage.delete("../../sensitive.txt")
    assert error.value.code == "STORAGE_KEY_INVALID"
