"""Per-request trace of what retrieval actually fetched.

`allowed` uses the same rules the system prompt describes, but it only
*labels* chunks for the log. Nothing here filters anything.
"""

import json
import logging
from pathlib import Path

from app.rag.search import Chunk

LOG_FILE = Path(__file__).resolve().parents[1] / "logs" / "trace.jsonl"

ROLE_CLASSIFICATIONS = {
    "employee": {"public"},
    "hr_manager": {"public", "hr_confidential"},
    "admin": {"public", "hr_confidential", "executive"},
}

logger = logging.getLogger("gatekeeper.trace")


def is_allowed(user_tenant: str, role: str, chunk: Chunk) -> bool:
    return chunk.tenant == user_tenant and chunk.classification in ROLE_CLASSIFICATIONS[role]


def record(user: dict, question: str, chunks: list[Chunk], answer: str) -> dict:
    retrieved = [
        {
            "chunk_id": c.id,
            "reference": c.reference,
            "tenant": c.tenant,
            "classification": c.classification,
            "allowed": is_allowed(user["tenant"], user["role"], c),
        }
        for c in chunks
    ]
    trace = {
        "event": "chat",
        "user": user["email"],
        "tenant": user["tenant"],
        "role": user["role"],
        "question": question,
        "retrieved": retrieved,
        "forbidden_retrieved": sum(not r["allowed"] for r in retrieved),
        "answer": answer,
    }
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(trace) + "\n")

    level = logging.WARNING if trace["forbidden_retrieved"] else logging.INFO
    logger.log(
        level,
        "user=%s role=%s retrieved=%d forbidden=%d refs=%s",
        user["email"], user["role"], len(retrieved), trace["forbidden_retrieved"],
        ",".join(f'{r["reference"]}{"" if r["allowed"] else "(FORBIDDEN)"}' for r in retrieved),
    )
    return trace
