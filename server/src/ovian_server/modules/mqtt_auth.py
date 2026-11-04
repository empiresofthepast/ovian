"""Authentication and ACL callbacks for the broker (mosquitto-go-auth, HTTP backend).

The broker calls these with JSON bodies and treats HTTP 200 as "allowed".
They must only be reachable from the broker: they are mounted under
/internal and require ``?key=OVIAN_INTERNAL_KEY``.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Request, Response

from ..deps import GameDep
from ..errors import GameError
from ..game import Game
from ..realtime import filter_covers
from ..security import decode_token
from .base import Module

router = APIRouter(prefix="/internal/mqtt", include_in_schema=False)

OK = Response(status_code=200)
DENY = Response(status_code=403)
# go-auth "acc" values
ACCESS = {1: "read", 2: "write", 3: "write", 4: "subscribe"}


def _key_ok(game: Game, request: Request) -> bool:
    return hmac.compare_digest(request.query_params.get("key", ""), game.settings.internal_key)


async def _body(request: Request) -> dict[str, Any]:
    if request.headers.get("content-type", "").startswith("application/json"):
        return await request.json()
    return dict(await request.form())


def is_service(game: Game, username: str, password: str | None = None) -> bool:
    s = game.settings
    if not hmac.compare_digest(username, s.mqtt_service_user):
        return False
    return password is None or hmac.compare_digest(password, s.mqtt_service_password)


def player_acl(game: Game, player_id: int, topic: str, access: str) -> bool:
    t = game.topics
    if access in ("read", "subscribe"):
        allowed = [f"{t.player(player_id).rsplit('/', 1)[0]}/#", t.map, t.server, t.chat("+")]
        if any(filter_covers(a, topic) for a in allowed):
            return True
    else:
        parts = topic.split("/")
        root = t.root.split("/")
        # ovian/{world}/chat/{channel}/in/{player_id}
        if (
            len(parts) == len(root) + 4 and parts[: len(root)] == root and parts[len(root)] == "chat"
            and parts[-2] == "in" and parts[-1] == str(player_id) and parts[len(root) + 1] not in ("+", "#")
        ):
            return True
    decided = game.hook.ovian_mqtt_acl(game=game, player_id=player_id, topic=topic, access=access)
    return bool(decided)


@router.post("/user")
async def user(request: Request, game: GameDep) -> Response:
    if not _key_ok(game, request):
        return DENY
    b = await _body(request)
    username, password = str(b.get("username", "")), str(b.get("password", ""))
    if is_service(game, username, password):
        return OK
    try:
        claims = decode_token(game.settings.jwt_secret, password)
    except GameError:
        return DENY
    if claims.get("sub") != username or claims.get("world") != game.settings.world_id:
        return DENY
    game.presence.touch(int(username))
    return OK


@router.post("/superuser")
async def superuser(request: Request, game: GameDep) -> Response:
    if not _key_ok(game, request):
        return DENY
    b = await _body(request)
    return OK if is_service(game, str(b.get("username", ""))) else DENY


@router.post("/acl")
async def acl(request: Request, game: GameDep) -> Response:
    if not _key_ok(game, request):
        return DENY
    b = await _body(request)
    username, topic = str(b.get("username", "")), str(b.get("topic", ""))
    if is_service(game, username):
        return OK
    try:
        player_id = int(username)
        access = ACCESS[int(b.get("acc", 0))]
    except (ValueError, KeyError):
        return DENY
    return OK if player_acl(game, player_id, topic, access) else DENY


module = Module("mqtt_auth", router=router, mount="")
