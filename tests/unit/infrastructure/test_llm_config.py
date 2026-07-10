"""Smoke tests for online-pipeline configuration loading."""

import pytest


def test_llm_config_loads_from_json(tmp_path):
    from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config

    config_path = tmp_path / "llm.local.json"
    config_path.write_text(
        '{"api_key":"sk-json","base_url":"https://llm.example/v1","model":"model-json","api_mode":"chat"}',
        encoding="utf-8",
    )

    config = load_llm_config(config_path)

    assert config is not None
    assert config.api_key == "sk-json"
    assert config.base_url == "https://llm.example/v1"
    assert config.model == "model-json"
    assert config.api_mode == "chat"


def test_llm_config_ignores_legacy_env(tmp_path, monkeypatch):
    from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config

    monkeypatch.setenv("UNRELATED_API_KEY", "sk-env")
    monkeypatch.setenv("UNRELATED_MODEL", "model-env")
    config_path = tmp_path / "llm.local.json"
    config_path.write_text('{"api_key":"sk-json","model":"model-json"}', encoding="utf-8")

    config = load_llm_config(config_path)

    assert config is not None
    assert config.api_key == "sk-json"
    assert config.model == "model-json"


def test_llm_config_does_not_fallback_to_legacy_env(tmp_path, monkeypatch):
    from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config

    monkeypatch.setenv("UNRELATED_API_KEY", "sk-env")
    monkeypatch.setenv("UNRELATED_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("UNRELATED_MODEL", "model-env")

    with pytest.raises(FileNotFoundError):
        load_llm_config(tmp_path / "missing.json")


def test_llm_config_requires_json_key_and_model(tmp_path):
    from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config

    config_path = tmp_path / "llm.local.json"
    config_path.write_text('{"base_url":"https://llm.example/v1"}', encoding="utf-8")

    with pytest.raises(ValueError, match="api_key"):
        load_llm_config(config_path)
