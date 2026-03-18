import logging

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# OpenAI client
_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# use model
# text-embedding-3-small: 빠르고 저렴, 1536차원
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


async def embed(text: str) -> list[float]:
    text = text.strip()
    if not text:
        raise ValueError("임베딩할 텍스트가 비어있습니다.")

    response = await _client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    vector = response.data[0].embedding
    logger.debug("[Embed] 완료 dim=%d text_preview='%s'", len(vector), text[:50])
    return vector


    # Incident 전용 임베딩 ( summary + stackTrace 500 ) -------------------------------------------
async def embed_incident(summary: str, stack_trace: str | None) -> list[float]:
    stack_preview = (stack_trace or "")[:500]
    combined = f"{summary}\n{stack_preview}".strip()
    return await embed(combined)


    # kb 저장시 addendums 도 포함 ---------------------------------------------
async def embed_kb_article(
        title: str,
        content: str,
        addendums: list[str] | None = None,
) -> list[float]:

    addendums = addendums or []
    addendum_text = "\n".join(addendums)
    combined = f"{title}\n{content}\n{addendum_text}".strip()
    return await embed(combined)