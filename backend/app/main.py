from fastapi import FastAPI

from app.config import settings  # noqa: F401  (fail fast if .env is missing)

app = FastAPI(title="Gatekeeper")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
