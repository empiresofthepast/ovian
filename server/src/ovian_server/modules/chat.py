"""Chat over MQTT.

Clients publish ``{"text": "..."}`` to ``ovian/{world}/chat/{channel}/in/{their player id}``.
The broker only lets a client publish to the inbox carrying its own id, so the
server knows who wrote it. The server stores the message and rebroadcasts it
on ``ovian/{world}/chat/{channel}``. The same thing is available over REST.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import GameError
from ..repo import get_player
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game

log = logging.getLogger("ovian.chat")
router = APIRouter(tags=["chat"])
CHANNEL = re.compile(r"^[a-z0-9_\-]{1,32}$")
MAX_LEN = 500
# Built-in public channels. Plugins can add more by extending this set.
PUBLIC_CHANNELS: set[str] = {"global", "trade", "help"}
_last_post: dict[int, float] = {}


def check_channel(channel: str) -> None:
    if not CHANNEL.match(channel) or channel not in PUBLIC_CHANNELS:
        raise GameError(404, "unknown_channel")


async def post_message(game: Game, channel: str, player_id: int, text: str) -> dict[str, Any]:
    check_channel(channel)
    text = text.strip()
    if not text or len(text) > MAX_LEN:
        raise GameError(422, "invalid_message", f"1 to {MAX_LEN} characters")
    now = time.monotonic()
    if now - _last_post.get(player_id, 0) < 1.0:
        raise GameError(429, "slow_down")
    _last_post[player_id] = now
    async with game.tx() as tx:
        player = await get_player(tx.conn, player_id)
        msg_id = await tx.conn.fetchval(
            "INSERT INTO chat_messages(channel, player_id, text, created_at) VALUES ($1, $2, $3, $4) RETURNING id",
            channel, player_id, text, game.clock.now(),
        )
        msg = {"id": msg_id, "channel": channel, "from": {"id": player_id, "name": player["username"]}, "text": text, "at": game.clock.now()}
        tx.publish(game.topics.chat(channel), {"type": "chat.message", "at": msg["at"], "data": msg})
    return msg


async def on_inbox(game: Game, topic: str, payload: bytes) -> None:
    # ovian/{world}/chat/{channel}/in/{player_id}
    parts = topic.split("/")
    channel, player_id = parts[3], int(parts[5])
    try:
        body = json.loads(payload)
        text = body["text"] if isinstance(body, dict) else str(body)
    except (ValueError, KeyError):
        text = payload.decode(errors="replace")
    try:
        await post_message(game, channel, player_id, str(text))
    except GameError as e:
        game.realtime.publish(game.topics.player(player_id), {"type": "chat.rejected", "at": game.clock.now(), "data": {"channel": channel, "error": e.code}})


class Post(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_LEN)


@router.get("/chat/{channel}")
async def history(channel: str, game: GameDep, limit: int = Query(50, ge=1, le=200), before: int | None = None) -> list[dict[str, Any]]:
    check_channel(channel)
    assert game.pool is not None
    rows = await game.pool.fetch(
        """SELECT m.id, m.text, m.created_at AS at, p.id AS pid, p.username FROM chat_messages m JOIN players p ON p.id = m.player_id
           WHERE m.channel = $1 AND ($2::bigint IS NULL OR m.id < $2) ORDER BY m.id DESC LIMIT $3""",
        channel, before, limit,
    )
    return [{"id": r["id"], "channel": channel, "from": {"id": r["pid"], "name": r["username"]}, "text": r["text"], "at": r["at"]} for r in reversed(rows)]


@router.post("/chat/{channel}", status_code=201)
async def post(channel: str, body: Post, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    return await post_message(game, channel, player_id, body.text)


module = Module("chat", router=router, mqtt={"chat/+/in/+": on_inbox})
