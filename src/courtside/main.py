from fastapi import FastAPI

from courtside.config import get_settings
from courtside.errors import install_error_handlers
from courtside.routes import archetype, auth, games, me, seasons, stats

settings = get_settings()

app = FastAPI(title="Courtside API", version="0.1.0")

install_error_handlers(app)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(seasons.router)
app.include_router(games.router)
app.include_router(stats.router)
app.include_router(archetype.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}
