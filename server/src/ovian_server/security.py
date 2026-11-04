from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import time
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import GameError

_N, _R, _P = 2**14, 8, 1


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)


async def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = await asyncio.to_thread(_scrypt, password, salt, _N, _R, _P)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


async def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = await asyncio.to_thread(_scrypt, password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(got, base64.b64decode(digest))
    except ValueError:
        return False


def issue_token(secret: str, player_id: int, username: str, world: str, ttl_hours: int) -> str:
    now = int(time.time())
    claims = {"sub": str(player_id), "name": username, "world": world, "iat": now, "exp": now + ttl_hours * 3600}
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "exp"]})
    except jwt.PyJWTError as e:
        raise GameError(401, "invalid_token", str(e)) from e


_bearer = HTTPBearer(auto_error=False)
PAT_PREFIX = "ovp_"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _personal_token(game: Any, token: str) -> int:
    """A personal access token (``ovp_…``): long-lived, revocable, for scripts and the MCP server."""
    row = await game.pool.fetchrow(
        "UPDATE api_tokens SET last_used_at = $2 WHERE token_hash = $1 AND revoked_at IS NULL RETURNING player_id",
        token_hash(token), game.clock.now())
    if row is None:
        raise GameError(401, "invalid_token", "unknown or revoked access token")
    return int(row["player_id"])


def require_session(request: Request) -> None:
    """Account settings (name, access tokens) need a real login, not a personal access token."""
    if getattr(request.state, "personal_token", False):
        raise GameError(403, "needs_login", "log in with your password for this; access tokens cannot do it")


async def current_player_id(
    request: Request, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> int:
    if creds is None:
        raise GameError(401, "unauthorized", "missing bearer token")
    game = request.app.state.game
    if creds.credentials.startswith(PAT_PREFIX):
        player_id = await _personal_token(game, creds.credentials)
        request.state.personal_token = True
    else:
        claims = decode_token(game.settings.jwt_secret, creds.credentials)
        if claims.get("world") != game.settings.world_id:
            raise GameError(401, "invalid_token", "token is for another world")
        player_id = int(claims["sub"])
        request.state.personal_token = False
    from .modules.rounds import check_ban

    check_ban(game, player_id)
    game.presence.touch(player_id)
    return player_id


PlayerId = Annotated[int, Depends(current_player_id)]
