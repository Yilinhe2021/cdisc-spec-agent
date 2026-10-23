"""Offline provider: deterministic heuristics stand in for the model.

Each agent registers an offline handler next to its prompt:

    @register_mock("clarity_review")
    def _offline(ctx): ...

so reading one agent file shows both the LLM path and the fallback. The mock is
intentionally weaker than a real model; it exists so the pipeline, UI, tests and
eval harness run end-to-end with zero credentials.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .base import LLMError, LLMProvider

_HANDLERS: dict[str, Callable[[dict], Any]] = {}


def register_mock(task: str):
    def deco(fn: Callable[[dict], Any]):
        _HANDLERS[task] = fn
        return fn
    return deco


class MockProvider(LLMProvider):
    name = "mock"
    model = "offline-heuristics"
    offline = True

    async def _complete(self, system: str, user: str, max_tokens: int) -> str:  # pragma: no cover
        raise LLMError("MockProvider needs a task name")

    def _run(self, task: str, context: dict | None) -> Any:
        if task not in _HANDLERS:
            raise LLMError(f"No offline handler registered for task '{task}'")
        self.calls += 1
        return _HANDLERS[task](context or {})

    async def complete(self, system: str, user: str, *, task: str = "", context: dict | None = None,
                       max_tokens: int = 4000) -> str:
        out = self._run(task, context)
        return out if isinstance(out, str) else json.dumps(out)

    async def complete_json(self, system: str, user: str, *, task: str = "", context: dict | None = None,
                            max_tokens: int = 4000) -> Any:
        return self._run(task, context)
