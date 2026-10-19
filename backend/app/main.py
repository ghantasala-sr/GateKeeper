import logging
from contextlib import asynccontextmanager

import anthropic
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app import audit, db, trace
from app.auth import oidc, saml, tokens
from app.auth.bridge import Principal
from app.scim import routes as scim
from app.config import settings
from app.rag.embeddings import embed
from app.rag.agent import run_agent

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    embed(["warm up"])  # load the embedding model once at startup
    yield
    await db.close_pool()


app = FastAPI(title="Gatekeeper", lifespan=lifespan)
# Holds only the in-progress login (state, nonce, PKCE verifier), so keep it short-lived.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="gk_login",
    max_age=600,
    same_site="lax",
    https_only=settings.okta_redirect_uri.startswith("https://"),
    # Lax still sends this cookie on the IdP's POST to /auth/saml/acs because Keycloak
    # (localhost:8080) is the same site as us. A real Entra IdP is cross-site: that
    # needs same_site="none" over HTTPS, or the InResponseTo check can't find the request.
)
app.include_router(oidc.router)
app.include_router(saml.router)
app.include_router(scim.router)
app.add_exception_handler(scim.ScimError, lambda request, e: scim.error_response(e))


class ChatRequest(BaseModel):
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


@app.get("/.well-known/jwks.json")
def jwks() -> dict:
    return tokens.jwks()


@app.post("/chat")
async def chat(req: ChatRequest, principal: Principal = Depends(tokens.require_scope("docs:read"))) -> ChatResponse:
    # Who is asking now comes only from the verified access token.
    async with db.run_as(principal) as conn:
        tenant_name = await conn.fetchval("SELECT name FROM tenants WHERE id = $1::uuid", principal.tenant_id)
    user = {"email": principal.email, "role": principal.role, "tenant": tenant_name}

    if not settings.anthropic_api_key:
        raise HTTPException(503, "Chat model is not configured; set ANTHROPIC_API_KEY in .env")
    try:
        # The agent searches as this principal; RLS limits what its tool can see (Steps 10-13).
        text, chunks = await run_agent(principal, req.question)
    except anthropic.AuthenticationError:
        raise HTTPException(503, "Chat model rejected the API key; check ANTHROPIC_API_KEY in .env")
    except anthropic.RateLimitError:
        raise HTTPException(503, "Chat model is rate limited; try again shortly")
    except anthropic.APIConnectionError:
        raise HTTPException(503, "Could not reach the chat model")

    async with db.run_as(principal) as conn:
        await audit.record(conn, tenant_id=principal.tenant_id, user_id=principal.user_id, action="chat",
                           question=req.question, chunk_ids=list(dict.fromkeys(c.id for c in chunks)))
    t = trace.record(user, req.question, chunks, text)
    return ChatResponse(
        answer=text,
        chunks=[ChunkOut(**{k: r[k] for k in ("reference", "tenant", "classification", "allowed")}) for r in t["retrieved"]],
        forbidden_retrieved=t["forbidden_retrieved"],
    )


@app.get("/admin/stats")
async def admin_stats(principal: Principal = Depends(tokens.require_scope("docs:admin"))) -> dict:
    """Test-only route to prove scope checks. Counts the admin's own tenant only."""
    async with db.run_as(principal) as conn:
        # RLS scopes these counts; the explicit tenant filter is a second layer, not the guard.
        row = await conn.fetchrow(
            """
            SELECT (SELECT count(*) FROM documents WHERE tenant_id = $1::uuid) AS documents,
                   (SELECT count(*) FROM chunks    WHERE tenant_id = $1::uuid) AS chunks,
                   (SELECT count(*) FROM users     WHERE tenant_id = $1::uuid) AS users
            """,
            principal.tenant_id,
        )
    return {"tenant_id": principal.tenant_id, **dict(row)}
