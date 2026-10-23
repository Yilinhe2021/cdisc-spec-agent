"""Provider-agnostic LLM interface.

Agents never talk to a vendor SDK directly. They call `complete_json(task=..., ...)`
with a *task name*; real providers ignore the task name and send the prompt,
while the offline `MockProvider` routes the task to a deterministic heuristic so the
whole system runs (and is testable) without an API key.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""
    offline: bool = False

    def __init__(self) -> None:
        self.calls = 0
        self.input_chars = 0
        self.output_chars = 0

    @abstractmethod
    async def _complete(self, system: str, user: str, max_tokens: int) -> str: ...

    async def complete(self, system: str, user: str, *, task: str = "", context: dict | None = None,
                       max_tokens: int = 4000) -> str:
        self.calls += 1
        self.input_chars += len(system) + len(user)
        out = await self._complete(system, user, max_tokens)
        self.output_chars += len(out)
        return out

    async def complete_json(self, system: str, user: str, *, task: str = "", context: dict | None = None,
                            max_tokens: int = 4000) -> Any:
        system = system + "\n\nRespond with a single valid JSON value only. No prose, no markdown fences."
        raw = await self.complete(system, user, task=task, context=context, max_tokens=max_tokens)
        return extract_json(raw)

    def usage(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "calls": self.calls,
                "input_chars": self.input_chars, "output_chars": self.output_chars}


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in `text` (tolerates code fences / chatter)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_, close in (("{", "}"), ("[", "]")):
        start = text.find(open_)
        end = text.rfind(close)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Model did not return JSON: {text[:300]}")


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"
