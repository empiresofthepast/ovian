from typing import Annotated

from fastapi import Depends, Request

from .game import Game


def get_game(request: Request) -> Game:
    return request.app.state.game


GameDep = Annotated[Game, Depends(get_game)]
