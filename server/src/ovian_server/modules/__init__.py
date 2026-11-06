"""Built-in feature modules, contributed through the same hook plugins use."""

from ..hooks import hookimpl
from .base import Module


@hookimpl
def ovian_modules() -> list[Module]:
    from . import (artworks, atlas, pvp, settings, terrain, victory, archaeology, hub, militia, auxiliaries, embassies, governors, admin, alliances, auth, calendar, chat, chronicle, contentment, culture, gods, governments, great, heroes, market, medals,
                   military, mqtt_auth, omens, player_rules, pve, reports, roads, rounds, scouting, settlers, abandon, horde, treaties, infra, starvation, submission, tokens, ver_sacrum, villages, world)

    return [auth.module, villages.module, military.module, world.module, reports.module, chat.module, culture.module, submission.module, ver_sacrum.module, mqtt_auth.module, admin.module,
            alliances.module, market.module, scouting.module, heroes.module, pve.module, gods.module, great.module, player_rules.module,
            chronicle.module, contentment.module, governments.module, calendar.module, terrain.module, victory.module, atlas.module, artworks.module, pvp.module, settings.module, omens.module, medals.module, rounds.module, roads.module, tokens.module, starvation.module, embassies.module,
            archaeology.module, auxiliaries.module, governors.module, hub.module, militia.module, settlers.module, abandon.module, horde.module, treaties.module, infra.module]
