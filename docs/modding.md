# Server plugins

Server behaviour is extended with [pluggy](https://pluggy.readthedocs.io) hooks, the same system pytest uses. The built-in features are modules contributed through these same hooks, so a plugin has the same power as core code.

## Loading plugins

- **Installed packages** declare an entry point in the `ovian.plugins` group:

  ```toml
  [project.entry-points."ovian.plugins"]
  morale = "ovian_morale"
  ```

- **Any importable module** can be listed in `OVIAN_PLUGINS=my_pkg.plugin,other.plugin`.
- Entry-point plugins can be switched off with `OVIAN_DISABLED_PLUGINS=beginner_protection`.

## Hooks

| Hook | When | Sync or async |
|---|---|---|
| `ovian_modules()` | Startup. Return `Module` objects: routes, timed jobs, MQTT handlers. | sync |
| `ovian_pack_loaded(pack)` | Before the engine validates the pack. Mutate the dict to rebalance or add content. | sync |
| `ovian_player_registered(game, tx, player)` | Inside the registration transaction. | either |
| `ovian_village_founded(game, tx, village)` | A village was created. Change `village.state` to alter it. | either |
| `ovian_validate_order(game, tx, player, village, order)` | Before build, train, send and recall. Raise `GameError` to refuse. | either |
| `ovian_battle_prepare(game, tx, battle, attacker, defender)` | Change `defense_bonus`, `attack_multiplier` or the troops. | either |
| `ovian_battle_resolved(game, tx, battle, result, report, attacker, defender)` | After losses and loot. `report` can be extended. | either |
| `ovian_village_view(game, conn, village, view)` | The owner's view of a village is built. Add keys to `view`; the submission module adds `submission`, `vassals` and `dominance` this way. |
| `ovian_mqtt_acl(game, player_id, topic, access)` | A topic the built-in rules do not cover. Return True or False to decide. | sync |

Hooks that receive `tx` run inside the game transaction. Use `tx.conn` (asyncpg) for SQL, and `game.event(tx, player_id, type, data)` or `tx.publish(topic, payload)` for realtime messages. Messages are sent only if the transaction commits.

## Example: morale

Big players hit small players less hard.

```python
# ovian_morale.py
from ovian_server.hooks import hookimpl

@hookimpl
async def ovian_battle_prepare(game, tx, battle, attacker, defender):
    a = await tx.conn.fetchval("SELECT sum(population) FROM villages WHERE player_id = $1", attacker.player_id)
    d = await tx.conn.fetchval("SELECT sum(population) FROM villages WHERE player_id = $1", defender.player_id)
    if a and d and a > d:
        battle["attack_multiplier"] *= max(0.33, (d / a) ** 0.2)

@hookimpl
def ovian_battle_resolved(report, **_):
    report["morale"] = True
```

## Example: a new feature module

```python
from fastapi import APIRouter
from ovian_server.deps import GameDep
from ovian_server.hooks import hookimpl
from ovian_server.modules.base import Module
from ovian_server.security import PlayerId

router = APIRouter(tags=["quests"])

@router.get("/quests")
async def quests(player_id: PlayerId, game: GameDep):
    return [{"id": "first_steps", "title": "Build a woodcutter"}]

async def on_quest_tick(game, tx, job):
    game.event(tx, job["payload"]["player_id"], "quest.tick", {})

@hookimpl
def ovian_modules():
    return [Module("quests", router=router, jobs={"quest.tick": on_quest_tick})]
```

Routes mount under `/api/v1` and appear in the OpenAPI docs. Schedule jobs with `await game.schedule(tx, "quest.tick", due_at_ms, payload, village_id=None)`. Subscribe to client messages with `mqtt={"quests/+/in/+": handler}`; give players publish rights through `ovian_mqtt_acl`.

## Reading pack extensions

Keep plugin settings in the pack so a world's rules live in one place:

```yaml
extensions:
  beginner_protection_hours: 72
```

```python
hours = game.content.extensions.get("beginner_protection_hours", 0)
```

See `server/src/ovian_server/plugins/beginner_protection.py` for a complete plugin.
