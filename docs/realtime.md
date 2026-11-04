# Realtime over MQTT

Clients connect to the broker over WebSocket. The web container proxies `/mqtt`, so the URL is `ws(s)://<game host>/mqtt`. The broker's own port works too.

- **Username:** the player id, as a string.
- **Password:** the bearer token returned by `/api/v1/auth/login`.
- `GET /api/v1/realtime` returns the topics for the signed-in player.

## Topics

`{root}` is `ovian/{world_id}`, for example `ovian/w1`. It is returned by `GET /api/v1/world` as `topic_root`.

| Topic | Direction | Content |
|---|---|---|
| `{root}/player/{id}/events` | server → that player only | Private events. |
| `{root}/map` | server → everyone | `map.village_founded`, `map.village_changed`. |
| `{root}/chat/{channel}` | server → everyone | `chat.message`, stamped with the real sender. |
| `{root}/chat/{channel}/in/{id}` | that player → server | `{"text": "..."}`. The broker rejects any id that is not the sender's. |
| `{root}/server` | server → everyone | Announcements. |

Built-in chat channels are `global`, `trade` and `help`.

## Event envelope

```json
{ "type": "village.updated", "at": 1793581617000, "data": { } }
```

| Type | Data |
|---|---|
| `village.updated` | The full village view, the same as `GET /villages/{id}`. Replace your copy with it. |
| `build.completed` | `village_id, slot, building, level` |
| `train.completed` | `village_id, unit, count, remaining` |
| `movement.incoming` | `id, kind, from, to, arrives_at`. Units are included only for reinforcements. |
| `movement.returned` | `village_id, units, loot` |
| `report.new` | `id, kind, title, created_at` |
| `village.submitted`, `village.vassal_gained` | `vassal, overlord, tribute`, sent to the vassal's and the overlord's player. |
| `village.founded` | `village, mother`: a ver sacrum founded a colony. |
| `village.freed`, `village.vassal_lost` | `vassal, overlord, reason`: `rebellion`, `conquered` or `released`. |
| `chat.message` | `id, channel, from {id, name}, text, at` |
| `chat.rejected` | `channel, error` |

## Permissions

The broker asks the server about every connection and subscription, and caches the answers for 60 seconds. A player may:

- subscribe to their own `player/{id}/#`, to `map`, to `server`, and to `chat/+`;
- publish only to `chat/{channel}/in/{their id}`.

Everything else is denied. Plugins can grant more through the `ovian_mqtt_acl` hook. The server itself connects as a superuser with `OVIAN_MQTT_SERVICE_PASSWORD`.

## A minimal bot in Python

```python
import httpx, json, paho.mqtt.client as mqtt

api = "http://localhost:47173/api/v1"
tok = httpx.post(f"{api}/auth/login", json={"username": "bot", "password": "secret123"}).json()
pid, root = tok["player"]["id"], httpx.get(f"{api}/world").json()["topic_root"]

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
c.username_pw_set(str(pid), tok["token"])
c.on_connect = lambda c, *_: c.subscribe(f"{root}/player/{pid}/events")
c.on_message = lambda c, u, m: print(json.loads(m.payload)["type"])
c.ws_set_options(path="/mqtt")
c.connect("localhost", 47173)
c.loop_forever()
```
