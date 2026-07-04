"""
LLM integration helpers for the AI Engine (GLM via OpenAI-compatible API).
"""

from functools import lru_cache

from openai import OpenAI

from core.settings import get_settings


@lru_cache
def get_llm_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )


def llm_chat(prompt: str, system: str | None = None) -> str:
    """Generate a completion from the configured GLM model."""
    settings = get_settings()
    client = get_llm_client()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
    )

    return response.choices[0].message.content or ""
