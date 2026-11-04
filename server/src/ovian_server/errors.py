from fastapi import Request
from fastapi.responses import JSONResponse


class GameError(Exception):
    """An expected failure reported to the client as {"error": code, "message": ...}."""

    def __init__(self, status: int, code: str, message: str | None = None):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")


def not_found(what: str = "not_found") -> GameError:
    return GameError(404, what)


def forbidden(code: str = "forbidden") -> GameError:
    return GameError(403, code)


def rule(code: str, message: str | None = None) -> GameError:
    """A request that the game rules reject."""
    return GameError(409, code, message)


async def game_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GameError)
    return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)
