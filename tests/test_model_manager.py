import pytest

from backend.services.model_manager import PullProgress, full_name, ollama_root


def test_ollama_root_detection():
    assert ollama_root("http://localhost:11434/v1") == "http://localhost:11434"
    assert ollama_root("http://gpu-box:11434/v1") == "http://gpu-box:11434"
    assert ollama_root("https://openrouter.ai/api/v1") is None
    assert ollama_root("http://gpu:8000/v1") is None


def test_full_name_adds_latest_tag():
    assert full_name("qwen3-vl") == "qwen3-vl:latest"
    assert full_name("qwen3-vl:4b-instruct") == "qwen3-vl:4b-instruct"


def test_pull_progress_aggregates_layers():
    p = PullProgress()
    p.update({"status": "pulling manifest"})
    assert p.fraction == 0.0
    p.update({"status": "pulling a", "digest": "a", "total": 300, "completed": 150})
    p.update({"status": "pulling b", "digest": "b", "total": 100, "completed": 0})
    assert p.fraction == pytest.approx(150 / 400)
    p.update({"status": "pulling b", "digest": "b", "total": 100, "completed": 100})
    p.update({"status": "pulling a", "digest": "a", "total": 300, "completed": 300})
    assert p.fraction == 1.0
    p.update({"status": "success"})
    assert p.done


def test_pull_progress_raises_on_error():
    with pytest.raises(RuntimeError, match="not found"):
        PullProgress().update({"error": "pull model manifest: file does not exist / not found"})
