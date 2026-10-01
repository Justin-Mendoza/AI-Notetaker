from types import SimpleNamespace

import pytest

from app.errors import ApiError
from app.services import media


def test_probe_rejects_audio_over_ninety_minutes(tmp_path, monkeypatch):
    path = tmp_path / "sample.wav"
    path.write_bytes(b"RIFFxxxxWAVE")
    monkeypatch.setattr(
        media.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout='{"streams":[{"codec_type":"audio"}],"format":{"duration":"5401"}}',
        ),
    )
    with pytest.raises(ApiError) as error:
        media.inspect_audio(path, "audio/wav")
    assert error.value.status_code == 413


def test_probe_reads_packet_timing_when_webm_duration_missing(tmp_path, monkeypatch):
    path = tmp_path / "sample.webm"
    path.write_bytes(bytes.fromhex("1a45dfa3") + b"data")
    responses = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout='{"streams":[{"codec_type":"audio"}],"format":{"duration":"N/A"}}',
            ),
            SimpleNamespace(returncode=0, stdout="0,1\n1,1\n"),
        ]
    )
    monkeypatch.setattr(media.subprocess, "run", lambda *args, **kwargs: next(responses))
    assert media.inspect_audio(path, "audio/webm;codecs=opus") == ("audio/webm", 2000)
