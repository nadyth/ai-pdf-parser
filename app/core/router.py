from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.exceptions import ConfigError
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ResolvedRoute:
    """Fully resolved provider config for a specific task."""

    provider_type: str  # "litellm", "vision", "image", "tts"
    provider: str
    api_key: str
    base_url: str
    model: str
    params: dict[str, Any] = field(default_factory=dict)


class ModelRouter:
    """Resolves which provider/model/config to use for a given task.

    Resolution order (highest priority wins):
      1. Explicit model override (e.g. from a rule)
      2. Named route override (e.g. rule.model_route="vision_alt")
      3. Task default route (model_routes.yaml)
      4. Global _default route (model_routes.yaml)
    """

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            cfg = get_settings().model_routes_path
            config_path = cfg or Path(__file__).parent.parent / "config" / "model_routes.yaml"
        self._config_path = Path(config_path)
        self._providers: dict[str, dict] = {}
        self._routes: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self._config_path.exists():
            raise ConfigError(
                f"Model routes config not found: {self._config_path}",
                details={"path": str(self._config_path)},
            )
        with open(self._config_path) as f:
            raw = yaml.safe_load(f) or {}
        self._providers = raw.get("providers", {})
        self._routes = raw.get("routes", {})
        logger.info(
            "Loaded model routes: %d providers, %d routes from %s",
            len(self._providers),
            len(self._routes),
            self._config_path,
        )

    def resolve(
        self,
        task_name: str,
        override_model: str | None = None,
        route_name: str | None = None,
    ) -> ResolvedRoute:
        route_config = self._find_route(task_name, route_name)
        effective = dict(route_config)
        if override_model:
            effective["model"] = override_model

        provider_name = effective.get("provider")
        if not provider_name:
            raise ConfigError(
                f"No provider in route for task '{task_name}'",
                details={"task": task_name, "route_config": route_config},
            )
        provider_def = self._providers.get(provider_name)
        if not provider_def:
            raise ConfigError(
                f"Unknown provider '{provider_name}' for task '{task_name}'",
                details={"available": list(self._providers.keys())},
            )

        api_key = os.environ.get(provider_def.get("api_key_env", ""), "")
        base_url = effective.pop("base_url", None) or provider_def.get("base_url", "")
        model = effective.pop("model", "")
        effective.pop("provider", None)

        return ResolvedRoute(
            provider_type=provider_def.get("type", "litellm"),
            provider=provider_name,
            api_key=api_key,
            base_url=base_url,
            model=model,
            params=effective,
        )

    def _find_route(self, task_name: str, route_name: str | None = None) -> dict:
        if route_name:
            if route_name not in self._routes:
                raise ConfigError(
                    f"Unknown model route '{route_name}'",
                    details={"available": list(self._routes.keys())},
                )
            return self._routes[route_name]
        if task_name in self._routes:
            return self._routes[task_name]
        if "_default" in self._routes:
            return self._routes["_default"]
        raise ConfigError(
            f"No route for task '{task_name}' and no _default",
            details={"available": list(self._routes.keys())},
        )


_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
