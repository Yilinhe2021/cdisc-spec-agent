"""Minimal async agent-graph runtime.

Agents are nodes in a DAG; a node runs as soon as all its dependencies finished,
and independent nodes run concurrently (asyncio). Every agent writes structured
TraceEvents that the API streams to the browser over SSE, so the user watches the
agents work. Kept deliberately small (no framework) so the control flow is easy to
read; the node/edge shape maps 1:1 onto LangGraph if you want to swap it in.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .llm import LLMProvider
from .models import TraceEvent


class Tracer:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self._subscribers: list[asyncio.Queue] = []
        self.closed = False

    def emit(self, agent: str, message: str, kind: str = "info", **data: Any) -> TraceEvent:
        ev = TraceEvent(agent=agent, kind=kind, message=message, data=data)
        self.events.append(ev)
        for q in self._subscribers:
            q.put_nowait(ev)
        return ev

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for ev in self.events:
            q.put_nowait(ev)
        self._subscribers.append(q)
        return q

    def close(self) -> None:
        self.closed = True
        for q in self._subscribers:
            q.put_nowait(None)


@dataclass
class Context:
    llm: LLMProvider
    tracer: Tracer
    state: dict[str, Any] = field(default_factory=dict)


class Agent:
    name = "Agent"
    description = ""

    async def run(self, ctx: Context) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def log(self, ctx: Context, message: str, kind: str = "info", **data: Any) -> None:
        ctx.tracer.emit(self.name, message, kind, **data)


@dataclass
class Node:
    agent: Agent
    deps: list[str] = field(default_factory=list)
    optional: bool = False  # failure is logged but does not stop the graph


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}

    def add(self, agent: Agent, deps: list[str] | None = None, optional: bool = False) -> "Graph":
        self.nodes[agent.name] = Node(agent, deps or [], optional)
        return self

    async def run(self, ctx: Context, on_done: Callable[[str, Any], Awaitable[None]] | None = None) -> dict[str, Any]:
        results: dict[str, Any] = {}
        pending = dict(self.nodes)
        running: dict[str, asyncio.Task] = {}

        async def _exec(name: str, node: Node) -> Any:
            t0 = time.perf_counter()
            node.agent.log(ctx, node.agent.description or "started", "start")
            try:
                out = await node.agent.run(ctx)
            except Exception as e:
                node.agent.log(ctx, f"{type(e).__name__}: {e}", "error")
                if not node.optional:
                    raise
                out = None
            node.agent.log(ctx, f"finished in {time.perf_counter() - t0:.2f}s", "done")
            return out

        while pending or running:
            ready = [n for n, node in pending.items() if all(d in results for d in node.deps)]
            for n in ready:
                running[n] = asyncio.create_task(_exec(n, pending.pop(n)))
            if not running:
                raise RuntimeError(f"Unsatisfiable dependencies: {list(pending)}")
            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for name, task in list(running.items()):
                if task in done:
                    results[name] = task.result()
                    del running[name]
                    if on_done:
                        await on_done(name, results[name])
        return results
