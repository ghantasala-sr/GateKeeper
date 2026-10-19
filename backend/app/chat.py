import anthropic

from app.config import settings
from app.rag.search import Chunk

# Step 3 "guard": the access rules exist ONLY in this prompt. Retrieval still
# hands the model every company's chunks. See app/trace.py for what it fetched.
SYSTEM_PROMPT = """You answer employees' questions about internal company documents.

You are assisting {email}, who works at {tenant} with the role "{role}".

Access rules:
- Only use documents that belong to {tenant}. Never reveal another company's information.
- The role "employee" may only see "public" documents.
- The role "hr_manager" may see "public" and "hr_confidential" documents.
- The role "admin" may see every document in their own company.

Each context chunk is labeled with its company and classification. Answer only
from chunks this user is allowed to see. If the answer needs anything else, reply
exactly: "I don't have access to that." Keep answers short and cite the document
reference in brackets, e.g. [ACME-PUB-02]."""

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)  # key checked in /chat


def format_context(chunks: list[Chunk]) -> str:
    return "\n\n".join(
        f'<chunk reference="{c.reference}" company="{c.tenant}" classification="{c.classification}">\n'
        f"{c.content}\n</chunk>"
        for c in chunks
    )


async def answer(user: dict, question: str, chunks: list[Chunk]) -> str:
    response = await client.beta.messages.create(
        model=settings.chat_model,
        max_tokens=16000,
        system=SYSTEM_PROMPT.format(email=user["email"], tenant=user["tenant"], role=user["role"]),
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[
            {
                "role": "user",
                "content": f"<context>\n{format_context(chunks)}\n</context>\n\nQuestion: {question}",
            }
        ],
    )
    if response.stop_reason == "refusal":
        return "Sorry, I can't help with that request."
    return "".join(block.text for block in response.content if block.type == "text")
