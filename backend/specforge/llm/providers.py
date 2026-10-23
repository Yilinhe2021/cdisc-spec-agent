"""Concrete providers + factory. Selection is driven by environment variables:

    SPECFORGE_LLM      = anthropic | openai | mock   (default: anthropic if a key is set, else mock)
    SPECFORGE_MODEL    = model id override
    ANTHROPIC_API_KEY / OPENAI_API_KEY
"""
from __future__ import annotations

import asyncio
import os

from .base import LLMError, LLMProvider


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        from anthropic import AsyncAnthropic  # lazy: optional dependency

        self.client = AsyncAnthropic()
        self.model = model or os.getenv("SPECFORGE_MODEL", "claude-sonnet-4-5")

    async def _complete(self, system: str, user: str, max_tokens: int) -> str:
        for attempt in range(3):
            try:
                resp = await self.client.messages.create(
                    model=self.model, max_tokens=max_tokens, system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            except Exception as e:  # pragma: no cover - network
                if attempt == 2:
                    raise LLMError(str(e)) from e
                await asyncio.sleep(2 ** attempt)
        return ""


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI()
        self.model = model or os.getenv("SPECFORGE_MODEL", "gpt-4.1")

    async def _complete(self, system: str, user: str, max_tokens: int) -> str:
        for attempt in range(3):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model, max_tokens=max_tokens,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                return resp.choices[0].message.content or ""
            except Exception as e:  # pragma: no cover - network
                if attempt == 2:
                    raise LLMError(str(e)) from e
                await asyncio.sleep(2 ** attempt)
        return ""


def get_provider(name: str | None = None) -> LLMProvider:
    name = (name or os.getenv("SPECFORGE_LLM") or "").lower()
    if not name:
        if os.getenv("ANTHROPIC_API_KEY"):
            name = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            name = "openai"
        else:
            name = "mock"
    if name == "anthropic":
        return AnthropicProvider()
    if name == "openai":
        return OpenAIProvider()
    if name == "mock":
        from .mock import MockProvider

        return MockProvider()
    raise ValueError(f"Unknown LLM provider: {name}")
