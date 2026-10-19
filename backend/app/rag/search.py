import asyncio
from dataclasses import dataclass

import asyncpg

from app.rag.embeddings import embed, to_pgvector


@dataclass(frozen=True)
class Chunk:
    id: str
    tenant: str
    reference: str
    classification: str
    content: str
    distance: float


async def search(conn: asyncpg.Connection, query: str, k: int = 5) -> list[Chunk]:
    # INSECURE ON PURPOSE (Step 3): no tenant or role filtering at all.
    [vector] = await asyncio.to_thread(embed, [query])
    rows = await conn.fetch(
        """
        SELECT c.id, t.name AS tenant, d.reference, c.classification, c.content,
               c.embedding <=> $1::vector AS distance
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        JOIN tenants t ON t.id = c.tenant_id
        ORDER BY c.embedding <=> $1::vector
        LIMIT $2
        """,
        to_pgvector(vector), k,
    )
    return [
        Chunk(str(r["id"]), r["tenant"], r["reference"], r["classification"], r["content"], r["distance"])
        for r in rows
    ]
