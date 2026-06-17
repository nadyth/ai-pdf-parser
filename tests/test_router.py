from __future__ import annotations

import os
from pathlib import Path

from app.core.router import ModelRouter


def test_default_routes_resolve(tmp_path: Path):
    cfg = Path("app/config/model_routes.yaml")
    r = ModelRouter(config_path=cfg)

    os.environ["OLLAMA_API_KEY"] = "test"

    route = r.resolve("page_vision")
    assert route.provider == "ollama"
    assert "minimax" in route.model
    assert route.provider_type == "litellm"

    fallback = r.resolve("nonexistent_task")
    assert fallback.provider == "ollama"


def test_override_model():
    r = ModelRouter()
    os.environ["OLLAMA_API_KEY"] = "test"
    route = r.resolve("page_vision", override_model="qwen2.5vl:cloud")
    assert route.model == "qwen2.5vl:cloud"
