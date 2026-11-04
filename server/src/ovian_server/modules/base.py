from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from fastapi import APIRouter

if TYPE_CHECKING:
    from ..game import Game, Tx

JobHandler = Callable[["Game", "Tx", dict[str, Any]], Awaitable[None]]
"""Handles a due job. Receives the job row (id, kind, due_at, village_id, payload)."""

MqttHandler = Callable[["Game", str, bytes], Awaitable[None]]
"""Handles an MQTT message on a subscribed topic filter (relative to the world root)."""


@dataclass
class Module:
    """A feature of the game: its HTTP routes, timed jobs and MQTT handlers.

    Modules are contributed through the ``ovian_modules`` hook, so plugins add
    features exactly the way the built-in ones do.
    """

    name: str
    router: APIRouter | None = None
    jobs: dict[str, JobHandler] = field(default_factory=dict)
    # Topic filter relative to "ovian/{world}/", e.g. "chat/+/in/+".
    mqtt: dict[str, MqttHandler] = field(default_factory=dict)
    # URL prefix the router is mounted under.
    mount: str = "/api/v1"
