from fastapi import FastAPI

from courtside.config import get_settings

settings = get_settings()

app = FastAPI(title="Courtside API", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}
