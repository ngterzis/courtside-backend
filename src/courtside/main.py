import logging

from fastapi import FastAPI

from courtside.config import get_settings
from courtside.errors import install_error_handlers
from courtside.origin import OriginVerifyMiddleware
from courtside.routes import archetype, auth, chat, games, health, me, seasons, stats


def _configure_logging() -> None:
    # uvicorn only configures its own loggers; without a handler here every
    # courtside.* INFO line (chat turn summaries, Aurora resume notices) is
    # dropped, both locally and in Lambda (CloudWatch reads stderr).
    logger = logging.getLogger("courtside")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


_configure_logging()

app = FastAPI(title="Courtside API", version="0.1.0")

install_error_handlers(app)
app.add_middleware(OriginVerifyMiddleware, secret=get_settings().origin_secret)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(seasons.router)
app.include_router(games.router)
app.include_router(stats.router)
app.include_router(archetype.router)
app.include_router(chat.router)
app.include_router(health.router)
