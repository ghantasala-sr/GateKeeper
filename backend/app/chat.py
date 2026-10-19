import anthropic

from app.config import settings
from app.rag.search import Chunk

# Since Step 12 this prompt is NOT a security control. The database has already
# removed everything this user may not see (RLS), so the model only ever
# receives allowed chunks. The prompt just keeps answers grounded.
SYSTEM_PROMPT = """You answer employees' questions about internal company documents.

Only answer from the provided context. If the context doesn't contain the answer,
reply exactly: "I don't have access to that information." Keep answers short and
cite the document reference in brackets, e.g. [ACME-PUB-02]."""

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)  # key checked in /chat


def format_context(chunks: list[Chunk]) -> str:
    return "\n\n".join(f'<chunk reference="{c.reference}">\n{c.content}\n</chunk>' for c in chunks)


async def answer(question: str, chunks: list[Chunk]) -> str:
    response = await client.beta.messages.create(
        model=settings.chat_model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
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
