from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigError(AppError):
    pass


class ProcessingError(AppError):
    pass


class NotFoundError(AppError):
    pass
