from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..deps import GameDep
from ..errors import not_found
from ..security import PlayerId
from .base import Module

router = APIRouter(tags=["reports"])


@router.get("/reports")
async def list_reports(
    player_id: PlayerId, game: GameDep, limit: int = Query(30, ge=1, le=100), before: int | None = None
) -> list[dict[str, Any]]:
    """Newest first. Pass the last id as ``before`` to page."""
    assert game.pool is not None
    rows = await game.pool.fetch(
        """SELECT id, kind, title, read, created_at FROM reports
           WHERE player_id = $1 AND ($2::bigint IS NULL OR id < $2) ORDER BY id DESC LIMIT $3""",
        player_id, before, limit,
    )
    return [dict(r) for r in rows]


@router.get("/reports/{report_id}")
async def get_report(report_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Returns the full report and marks it read."""
    assert game.pool is not None
    r = await game.pool.fetchrow(
        "UPDATE reports SET read = true WHERE id = $1 AND player_id = $2 RETURNING id, kind, title, data, read, created_at",
        report_id, player_id,
    )
    if r is None:
        raise not_found("report_not_found")
    return dict(r)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(report_id: int, player_id: PlayerId, game: GameDep) -> None:
    assert game.pool is not None
    status = await game.pool.execute("DELETE FROM reports WHERE id = $1 AND player_id = $2", report_id, player_id)
    if status.endswith(" 0"):
        raise not_found("report_not_found")


module = Module("reports", router=router)
