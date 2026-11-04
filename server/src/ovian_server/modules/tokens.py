"""Personal access tokens, for scripts and AI assistants (see ``mcp/`` and docs/mcp.md).

A token (``ovp_…``) acts as its player on every endpoint except account settings: it
cannot create tokens or change the username. It is shown once, stored only as a
SHA-256 hash, and can be revoked at any time. At most ``MAX`` live tokens per player.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import not_found, rule
from ..security import PAT_PREFIX, PlayerId, require_session, token_hash
from .base import Module

router = APIRouter(tags=["access tokens"])
MAX = 10


class NewToken(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def _row(r: Any) -> dict[str, Any]:
    return {"id": r["id"], "name": r["name"], "prefix": r["prefix"], "created_at": r["created_at"], "last_used_at": r["last_used_at"]}


@router.get("/me/tokens")
async def list_tokens(player_id: PlayerId, game: GameDep) -> list[dict[str, Any]]:
    rows = await game.pool.fetch("SELECT * FROM api_tokens WHERE player_id = $1 AND revoked_at IS NULL ORDER BY id", player_id)
    return [_row(r) for r in rows]


@router.post("/me/tokens", status_code=201)
async def create_token(body: NewToken, request: Request, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Create a token. The response is the only time its full value is shown."""
    require_session(request)
    n = await game.pool.fetchval("SELECT count(*) FROM api_tokens WHERE player_id = $1 AND revoked_at IS NULL", player_id)
    if n >= MAX:
        raise rule("too_many_tokens", f"at most {MAX} access tokens; revoke one first")
    token = PAT_PREFIX + secrets.token_urlsafe(32)
    r = await game.pool.fetchrow(
        "INSERT INTO api_tokens(player_id, name, token_hash, prefix, created_at) VALUES ($1, $2, $3, $4, $5) RETURNING *",
        player_id, body.name.strip(), token_hash(token), token[:10], game.clock.now())
    return _row(r) | {"token": token}


@router.delete("/me/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: int, player_id: PlayerId, game: GameDep) -> None:
    done = await game.pool.fetchval(
        "UPDATE api_tokens SET revoked_at = $3 WHERE id = $1 AND player_id = $2 AND revoked_at IS NULL RETURNING id",
        token_id, player_id, game.clock.now())
    if done is None:
        raise not_found("token_not_found")


module = Module("tokens", router=router)
