from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import db
from app.chat import answer
from app.config import settings
from app.rag.embeddings import embed
from app.rag.search import search


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    embed(["warm up"])  # load the embedding model once at startup
    yield
    await db.close_pool()


app = FastAPI(title="Gatekeeper", lifespan=lifespan)


class ChatRequest(BaseModel):
    question: str


class ChunkOut(BaseModel):
    reference: str
    tenant: str
    classification: str
    distance: float


class ChatResponse(BaseModel):
    answer: str
    chunks: list[ChunkOut]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    async with db.get_pool().acquire() as conn:
        chunks = await search(conn, req.question)
    if not settings.anthropic_api_key:
        raise HTTPException(503, "Chat model is not configured; set ANTHROPIC_API_KEY in .env")
    try:
        text = await answer(req.question, chunks)
    except anthropic.AuthenticationError:
        raise HTTPException(503, "Chat model is not configured; set ANTHROPIC_API_KEY in .env")
    except anthropic.RateLimitError:
        raise HTTPException(503, "Chat model is rate limited; try again shortly")
    except anthropic.APIConnectionError:
        raise HTTPException(503, "Could not reach the chat model")
    return ChatResponse(
        answer=text,
        chunks=[ChunkOut(reference=c.reference, tenant=c.tenant, classification=c.classification, distance=c.distance) for c in chunks],
    )
