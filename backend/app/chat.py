import anthropic

from app.config import settings
from app.rag.search import Chunk

SYSTEM_PROMPT = (
    "You answer employees' questions about internal company documents. "
    "Answer only from the provided context. Keep answers short and cite the "
    "document reference in brackets, e.g. [ACME-PUB-02]."
)

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)  # key checked in /chat


def format_context(chunks: list[Chunk]) -> str:
    return "\n\n".join(
        f'<chunk reference="{c.reference}" company="{c.tenant}">\n{c.content}\n</chunk>'
        for c in chunks
    )


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
