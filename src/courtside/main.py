from fastapi import FastAPI

from courtside.errors import install_error_handlers
from courtside.routes import archetype, auth, chat, games, health, me, seasons, stats

app = FastAPI(title="Courtside API", version="0.1.0")

install_error_handlers(app)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(seasons.router)
app.include_router(games.router)
app.include_router(stats.router)
app.include_router(archetype.router)
app.include_router(chat.router)
app.include_router(health.router)
