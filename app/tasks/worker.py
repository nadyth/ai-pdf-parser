from __future__ import annotations

from arq.connections import RedisSettings

from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.tasks.callback import deliver_callback
from app.tasks.parse import parse_document


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def startup(ctx):
    configure_logging(get_settings().log_level)


async def shutdown(ctx):
    pass


class WorkerSettings:
    functions = [parse_document, deliver_callback]
    redis_settings = _redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    keep_result = 3600
    max_jobs = 4
    # Allow long book parses (configurable; default 6h).
    job_timeout = get_settings().parse_job_timeout_seconds
