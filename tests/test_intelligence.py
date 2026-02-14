from reward_agent.intelligence import LLMRefiner


def test_ollama_env_resolution(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("OLLAMA_HOST", "localhost:11434")
    refiner = LLMRefiner()

    assert refiner._resolve_ollama_model() == "qwen2.5:7b"
    assert refiner._resolve_ollama_base_url() == "http://localhost:11434"
