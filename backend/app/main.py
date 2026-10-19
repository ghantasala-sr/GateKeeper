import logging
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import db, trace
from app.auth import oidc
from app.chat import answer
from app.config import settings
from app.rag.embeddings import embed
from app.rag.search import search

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    embed(["warm up"])  # load the embedding model once at startup
    yield
    await db.close_pool()


app = FastAPI(title="Gatekeeper", lifespan=lifespan)
app.include_router(oidc.router)


class ChatRequest(BaseModel):
    # INSECURE ON PURPOSE: until login exists (Step 4+), the caller just says who they are.
    user_email: str
    question: str


class ChunkOut(BaseModel):
    reference: str
    tenant: str
    classification: str
    allowed: bool


class ChatResponse(BaseModel):
    answer: str
    chunks: list[ChunkOut]
    forbidden_retrieved: int


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    async with db.get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.email, u.role, t.name AS tenant
            FROM users u JOIN tenants t ON t.id = u.tenant_id
            WHERE u.email = $1 AND u.active
            """,
            req.user_email,
        )
        if row is None:
            raise HTTPException(404, "Unknown or inactive user")
        user = dict(row)
        chunks = await search(conn, req.question)

    if not settings.anthropic_api_key:
        raise HTTPException(503, "Chat model is not configured; set ANTHROPIC_API_KEY in .env")
    try:
        text = await answer(user, req.question, chunks)
    except anthropic.AuthenticationError:
        raise HTTPException(503, "Chat model rejected the API key; check ANTHROPIC_API_KEY in .env")
    except anthropic.RateLimitError:
        raise HTTPException(503, "Chat model is rate limited; try again shortly")
    except anthropic.APIConnectionError:
        raise HTTPException(503, "Could not reach the chat model")

    t = trace.record(user, req.question, chunks, text)
    return ChatResponse(
        answer=text,
        chunks=[ChunkOut(**{k: r[k] for k in ("reference", "tenant", "classification", "allowed")}) for r in t["retrieved"]],
        forbidden_retrieved=t["forbidden_retrieved"],
    )
