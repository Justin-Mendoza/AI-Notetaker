import importlib.util
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

SERVER = Path(__file__).resolve().parents[3] / "scripts" / "cohere_server.py"
spec = importlib.util.spec_from_file_location("cohere_service", SERVER)
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def test_cohere_service_decodes_serialized_local_audio(monkeypatch):
    generated = []

    def transcribe(path):
        assert Path(path).name == "input.wav"
        generated.append(path.name)
        return " A synthetic lecture "

    monkeypatch.setattr(service.subprocess, "run", lambda *args, **kwargs: None)
    service.app.state.engine = SimpleNamespace(transcribe=transcribe)
    client = TestClient(service.app)
    response = client.post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer local-cohere"},
        data={"model": service.MODEL},
        files={"file": ("sample.mp3", b"synthetic audio", "audio/mpeg")},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "A synthetic lecture"}
    assert generated == ["input.wav"]


def test_cohere_service_rejects_browser_forms_and_wrong_models():
    client = TestClient(service.app)
    data = {"model": service.MODEL}
    files = {"file": ("sample.mp3", b"audio", "audio/mpeg")}
    assert client.post("/v1/audio/transcriptions", data=data, files=files).status_code == 401
    assert (
        client.post(
            "/v1/audio/transcriptions",
            headers={"Authorization": "Bearer local-cohere"},
            data={"model": "wrong-model"},
            files=files,
        ).status_code
        == 400
    )


def test_model_load_and_inference_use_the_same_dedicated_thread():
    import threading

    thread_ids = []

    class ThreadBoundEngine:
        def __init__(self):
            thread_ids.append(threading.get_ident())

        def transcribe(self, path):
            thread_ids.append(threading.get_ident())
            return "A complete synthetic minute"

    worker = service.CohereWorker(factory=ThreadBoundEngine)
    try:
        assert worker.transcribe("audio.wav") == "A complete synthetic minute"
        assert worker.transcribe("next.wav") == "A complete synthetic minute"
        assert len(set(thread_ids)) == 1
        assert thread_ids[0] != threading.get_ident()
    finally:
        worker.close()
