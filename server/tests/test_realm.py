"""Contentment and unrest, governments, seasons and the festival, omens, medals, roads and trade routes,
espionage, the chronicle, world rounds and bans, and the tutorial."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from ovian_server.game import Game
from ovian_server.modules import calendar, contentment, medals, omens
from ovian_server.modules.auth import found_village_at
from ovian_server.modules.submission import submit
from ovian_server.repo import bump_stat, get_village, refresh_all, travel_factor

from .conftest import give_buildings, patch_state, rich
from .test_society import arrive, last_report, neighbours

HOUR = 3_600_000
MISSING = object()

GOVERNMENTS = {
    "default": "chiefdom", "anarchy_hours": 6, "cooldown_hours": 48,
    "anarchy": {"contentment": -15, "production": {"all": -0.1}},
    "list": {
        "chiefdom": {"name": "Chiefdom"},
        "republic": {"name": "Republic", "production": {"all": 0.05}, "trade_speed": 0.25},
        "tyranny": {"name": "Tyranny", "attack": 0.15},
    },
}
SEASONS = {"hours": 24, "list": [
    {"id": "spring", "name": "Spring", "production": {"grain": 0.1}},
    {"id": "summer", "name": "Summer"},
    {"id": "autumn", "name": "Autumn", "production": {"all": 0.05}},
    {"id": "winter", "name": "Winter", "production": {"grain": -0.25}, "travel": 1.25, "contentment": -5},
]}
FESTIVAL = {"name": "Games", "season": "summer", "contests": {
    "race": {"name": "Chariot race", "kind": "resources", "resources": ["wood", "iron"]},
    "wrestling": {"name": "Wrestling", "kind": "army"},
}, "prizes": [{"resources": {"all": 1000}, "favor": 50, "contentment": 10}, {"resources": {"all": 500}}]}


@contextmanager
def extensions(game: Game, **kw: Any) -> Iterator[None]:
    ext = game.content.extensions
    old = {k: ext.get(k, MISSING) for k in kw}
    ext.update(kw)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is MISSING:
                ext.pop(k, None)
            else:
                ext[k] = v


async def test_unhappy_vassal_rises_up(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    with extensions(game, contentment={}, submission={"benefits": {}}):  # no peace bonus: tribute alone
        async with game.tx() as tx:
            lord = await get_village(tx.conn, alice.village_id, lock=True)
            vassal = await get_village(tx.conn, bob.village_id, lock=True)
            await submit(game, tx, vassal, lord)
        c = (await bob.village())["contentment"]
        labels = {f["label"] for f in c["factors"]}
        assert "Tribute to an overlord" in labels and c["can_rebel"]
        assert c["score"] < 0 and c["production"] < 0

        # a famine of sorts: far below the line, unrest grows each hour until the city rises
        async with game.tx() as tx:
            v = await get_village(tx.conn, bob.village_id, lock=True)
            contentment.add_effect(game, v.meta, "contentment", "Famine", -40, 100)
            v.meta["unrest_at"] = game.clock.now()
            await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
        game.clock.value += 5 * HOUR
        async with game.tx() as tx:
            await contentment.on_tick(game, tx, {"payload": {}})
        assert not await game.pool.fetchval("SELECT 1 FROM vassals WHERE vassal_id = $1", bob.village_id)
        entry = (await client.get("/chronicle", params={"kind": "rebellion"})).json()["entries"][0]
        assert "rose up" in entry["title"]


async def test_content_cities_defend_themselves(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 10}))

    async def attack() -> dict[str, Any]:
        v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "attack", "x": target["x"], "y": target["y"], "units": {"clubman": 1}})).json()
        await arrive(game, v)
        return (await last_report(bob))["data"]

    with extensions(game, contentment={}):
        c = (await bob.village())["contentment"]
        assert c["score"] < 50 and c["defense"] == 0 and c["defense_from"] == 50
        plain = (await attack())["defense_bonus"]
        c = (await bob.village())["contentment"]  # the lost battle costs some points
        # a festival of sorts: 30 points over the line, 0.4% each
        async with game.tx() as tx:
            v = await get_village(tx.conn, bob.village_id, lock=True)
            contentment.add_effect(game, v.meta, "contentment", "Games", 80 - c["score"], 100)
            await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
        c = (await bob.village())["contentment"]
        assert c["score"] == 80 and c["defense"] == 0.12
        assert (await attack())["defense_bonus"] == plain + 0.12
        # capped at +20%
        async with game.tx() as tx:
            v = await get_village(tx.conn, bob.village_id, lock=True)
            contentment.add_effect(game, v.meta, "contentment", "Triumph", 100, 100)
            await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
        assert (await bob.village())["contentment"]["defense"] == 0.2


async def test_government_anarchy_then_effects(game: Game, client, register):
    alice = await register("alice", "clans")
    with extensions(game, governments=GOVERNMENTS):
        g = (await alice.get("/me/government")).json()
        assert g["current"] == "chiefdom" and {o["id"] for o in g["options"]} == {"chiefdom", "republic", "tyranny"}
        g = (await alice.post("/me/government", {"id": "republic"})).json()
        assert g["label"] == "Anarchy" and g["anarchy_until"] > game.clock.now()
        assert (await alice.village())["state"]["boost_by"]["wood"] == -0.1

        game.clock.value = g["anarchy_until"] + 10
        await game.run_due()
        v = await alice.village()
        assert v["government"]["label"] == "Republic"
        assert v["state"]["boost_by"]["wood"] == 0.05
        r = await alice.post("/me/government", {"id": "tyranny"})
        assert r.json()["error"] == "government_cooldown"


async def test_seasons_and_the_festival(game: Game, client, register):
    alice, bob, _ = await neighbours(game, register)
    with extensions(game, seasons=SEASONS, festival=FESTIVAL):
        await game.pool.execute("INSERT INTO world_state(key, value) VALUES ('calendar_epoch', to_jsonb($1::bigint))", game.clock.now())
        async with game.pool.acquire() as conn:
            await calendar.load_epoch(game, conn)
        cal = (await alice.get("/calendar")).json()
        assert cal["season"]["id"] == "spring" and not cal["festival"]["active"]
        await refresh_all(game)
        assert (await alice.village())["state"]["boost_by"] == {"grain": 0.1}
        assert (await alice.post("/festival/race", {"village_id": alice.village_id, "resources": {"wood": 10}})).json()["error"] == "no_festival"

        game.clock.value += 24 * HOUR  # summer: the games
        await patch_state(game, alice.village_id, lambda s: (rich(s), s.__setitem__("units", {"axeman": 20})))
        await patch_state(game, bob.village_id, rich)
        assert (await alice.post("/festival/race", {"village_id": alice.village_id, "resources": {"wood": 500, "iron": 100}})).status_code == 200
        await bob.post("/festival/race", {"village_id": bob.village_id, "resources": {"wood": 300}})
        cal = (await alice.post("/festival/wrestling", {"village_id": alice.village_id})).json()
        assert cal["festival"]["active"]
        assert [s["username"] for s in cal["festival"]["contests"]["race"]["standings"]] == ["alice", "bob"]
        assert cal["festival"]["contests"]["wrestling"]["mine"] == 20 * 60

        game.clock.value += 24 * HOUR  # autumn: prizes
        wood_before = (await alice.village())["state"]["resources"]["wood"]
        async with game.tx() as tx:
            await calendar.on_turn(game, tx, {"payload": {"festival": 1, "index": 2}})
        v = await alice.village()
        assert v["state"]["resources"]["wood"] >= wood_before + 1000
        assert v["state"]["boost_by"] == {"wood": 0.05, "clay": 0.05, "iron": 0.05, "grain": 0.05}
        mine = (await alice.get("/medals")).json()["mine"]
        assert {m["category"] for m in mine} == {"games_race", "games_wrestling"}
        assert (await bob.get("/medals")).json()["mine"][0]["rank"] == 2

        game.clock.value += 24 * HOUR  # winter: slow marches
        async with game.pool.acquire() as conn:
            a, b = await get_village(conn, alice.village_id), await get_village(conn, bob.village_id)
            assert abs(await travel_factor(game, conn, "attack", a, b, game.clock.now()) - 1.25) < 1e-9


async def test_omens_answered_and_ignored(game: Game, client, register):
    alice = await register("alice", "clans")
    harvest = next(e for e in omens.EVENTS if e["id"] == "harvest")
    async with game.tx() as tx:
        await omens.omen_for(game, tx, await get_village(tx.conn, alice.village_id, lock=True), harvest)
    v = await alice.village()
    feast = next(c for c in v["omen"]["choices"] if c["id"] == "feast")
    assert feast["gain"]["grain"] > 0
    grain = v["state"]["resources"]["grain"]
    v = (await alice.post(f"/villages/{alice.village_id}/omen/feast")).json()
    assert "omen" not in v and v["state"]["resources"]["grain"] > grain
    assert v["contentment"]["effects"][0]["value"] == 15
    assert (await alice.post(f"/villages/{alice.village_id}/omen/feast")).status_code == 404

    plague = next(e for e in omens.EVENTS if e["id"] == "plague")
    async with game.tx() as tx:
        await omens.omen_for(game, tx, await get_village(tx.conn, alice.village_id, lock=True), plague)
    game.clock.value += 13 * HOUR
    await game.run_due()
    v = await alice.village()
    assert "omen" not in v and abs(v["state"]["boost"] - -0.1) < 1e-9  # nobody answered: the default happened
    r = (await alice.get("/reports")).json()[0]
    assert r["kind"] == "omen" and "no answer" in r["title"]


async def test_weekly_medals(game: Game, client, register):
    alice = await register("alice", "clans")
    bob = await register("bob", "legion")
    async with game.tx() as tx:
        await medals.snapshot(tx.conn, await medals.stats_now(tx.conn))
        await bump_stat(tx.conn, alice.id, "attack_points", 50)
        await bump_stat(tx.conn, bob.id, "attack_points", 20)
        await bump_stat(tx.conn, bob.id, "loot", 900)
        await medals.award(game, tx)
    m = (await alice.get("/medals")).json()
    got = {(x["category"], x["player"]["name"], x["rank"]) for x in m["latest"]}
    assert got == {("attacker", "alice", 1), ("attacker", "bob", 2), ("raider", "bob", 1)}
    assert m["table"][0]["username"] in ("alice", "bob") and m["period"] == 2
    async with game.tx() as tx:
        assert await medals.award(game, tx) == []  # nothing gained since


async def test_roads_and_trade_routes(game: Game, client, register):
    alice = await register("alice", "clans")
    home = await alice.village()
    async with game.tx() as tx:
        second = await found_village_at(game, tx, alice.id, "Second", home["x"] + 6, home["y"])
    await patch_state(game, alice.village_id, lambda s: (rich(s), give_buildings(s, market=5)))
    v = (await alice.post(f"/villages/{alice.village_id}/roads", {"to_id": second.id})).json()
    road = v["roads"]["list"][0]
    assert road["to"]["id"] == second.id and road["ready_at"] > game.clock.now()
    async with game.pool.acquire() as conn:
        a = await get_village(conn, alice.village_id)
        assert await travel_factor(game, conn, "trade", a, second, game.clock.now()) == 1.0
        assert await travel_factor(game, conn, "trade", second, a, road["ready_at"]) == 1 / 1.5
    assert (await alice.post(f"/villages/{alice.village_id}/roads", {"to_id": second.id})).json()["error"] == "road_exists"
    assert len((await client.get("/roads", params={"x": 0, "y": 0, "w": 500, "h": 500})).json()) == 1
    # one road below level 10 of the town hall, one more every 10 levels
    async with game.tx() as tx:
        third = await found_village_at(game, tx, alice.id, "Third", home["x"], home["y"] + 6)
    assert v["roads"]["max"] == 1
    assert (await alice.post(f"/villages/{alice.village_id}/roads", {"to_id": third.id})).json()["error"] == "too_many_roads"
    await patch_state(game, alice.village_id, lambda s: give_buildings(s, town_hall=10))
    v = (await alice.post(f"/villages/{alice.village_id}/roads", {"to_id": third.id})).json()
    assert v["roads"]["max"] == 2 and len(v["roads"]["list"]) == 2

    v = (await alice.post(f"/villages/{alice.village_id}/routes",
                          {"x": second.x, "y": second.y, "resources": {"wood": 500}, "every_hours": 2})).json()
    assert v["routes"][0]["to"]["name"] == "Second"
    await game.run_due()
    v = await alice.village()
    assert v["market"]["shipments"][0]["resources"] == {"wood": 500}
    assert v["routes"][0]["next_at"] > game.clock.now() and v["routes"][0]["last_error"] is None

    await patch_state(game, alice.village_id, lambda s: s["resources"].__setitem__("wood", 0))
    game.clock.value = v["routes"][0]["next_at"]
    await game.run_due()
    assert (await alice.village())["routes"][0]["last_error"] == "insufficient_resources"


async def test_espionage_missions(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 50}))
    await patch_state(game, bob.village_id, lambda s: (give_buildings(s, barracks=5), s.__setitem__("techs", ["philosophy"]),
                                                       s.__setitem__("units", {"legionary": 10})))
    order = {"kind": "scout", "x": target["x"], "y": target["y"], "units": {"clubman": 25}}
    assert (await alice.post(f"/villages/{alice.village_id}/send", order | {"mission": "incite"})).json()["error"] == "not_a_vassal"
    assert (await alice.post(f"/villages/{alice.village_id}/send", {**order, "kind": "raid", "mission": "steal"})).json()["error"] == "scouts_only"

    v = (await alice.post(f"/villages/{alice.village_id}/send", order | {"mission": "sabotage"})).json()
    assert v["movements"]["outgoing"][0]["mission"] == "sabotage"
    await alice.post(f"/villages/{alice.village_id}/send", order | {"mission": "steal"})
    await arrive(game, v)
    game.clock.value += HOUR
    await game.run_due()
    barracks = next(s for s in (await bob.village())["state"]["slots"] if s["building"] == "barracks")
    assert barracks["level"] == 4
    assert "philosophy" in (await alice.village())["state"]["techs"]
    r = await last_report(bob)
    assert r["data"]["mission"] in ("sabotage", "steal") and r["data"]["noticed"]

    # too few spies for a hard mission: caught
    await patch_state(game, bob.village_id, lambda s: s.__setitem__("units", {"legionary": 400}))
    v = (await alice.post(f"/villages/{alice.village_id}/send", order | {"mission": "steal"})).json()
    await arrive(game, v)
    assert "caught" in (await last_report(alice))["title"]


async def test_chronicle_and_geojson(game: Game, client, register):
    alice = await register("alice", "clans")
    await alice.post("/alliances", {"name": "Northern League", "tag": "NL"})
    c = (await client.get("/chronicle")).json()
    assert [e["kind"] for e in c["entries"]] == ["alliance", "founded"]
    assert c["entries"][1]["title"] == "alice founded alice's village"
    g = (await client.get("/chronicle.geojson")).json()
    assert g["type"] == "FeatureCollection" and len(g["features"]) == 1  # the alliance has no place
    f = g["features"][0]
    assert f["geometry"]["type"] == "Point" and f["properties"]["fictional"] and f["properties"]["start_date"]


async def test_new_round_and_bans(game: Game, client, register):
    alice = await register("alice", "clans")
    bob = await register("bob", "legion")
    carol = await register("carol", "riders")
    await game.pool.execute("UPDATE players SET is_admin = true WHERE id = $1", alice.id)
    assert (await bob.post(f"/admin/players/{alice.id}/ban", {"days": 1})).status_code == 403

    r = (await alice.post(f"/admin/players/{carol.id}/ban", {"days": 2, "reason": "spam"})).json()
    assert r["banned_until"] > game.clock.now()
    assert (await carol.get("/me")).json()["error"] == "banned"
    assert (await client.post("/auth/login", json={"username": "carol", "password": "password123"})).status_code == 403

    old = alice.village_id
    speed = game.content.pack["world"]["speed"]
    try:
        r = (await alice.post("/admin/world/new-round", {"speed": 3})).json()
        assert r["round"] == 2 and r["players"] == 2 and game.content.pack["world"]["speed"] == 3
    finally:
        from ovian_server.modules.rounds import apply_speed

        await apply_speed(game, speed)
    me = (await alice.get("/me")).json()
    assert len(me["villages"]) == 1 and me["villages"][0]["id"] != old
    assert me["protected_until"] > game.clock.now()
    hof = (await client.get("/hall-of-fame")).json()
    assert hof["current_round"] == 2 and hof["rounds"][0]["round"] == 1
    assert {p["username"] for p in hof["rounds"][0]["data"]["players"]} == {"alice", "bob", "carol"}
    assert not await game.pool.fetchval("SELECT count(*) FROM villages WHERE player_id = $1", carol.id)
    assert [e["kind"] for e in (await client.get("/chronicle")).json()["entries"]][:1] == ["round"]

    await alice.post(f"/admin/players/{carol.id}/unban")
    assert (await carol.get("/me")).status_code == 200


async def test_tutorial(game: Game, client, register):
    alice = await register("alice", "clans")
    q = (await alice.get("/quests")).json()
    assert q["tutorial"] and q["quests"][0]["hint"] and q["quests"][0]["focus"] == {"building": "woodcutter"}
    await alice.post("/me/tutorial", {"on": False})
    assert (await alice.get("/me")).json()["tutorial"] is False
    assert (await alice.get("/quests")).json()["tutorial"] is False


async def test_politics_techs_slow_unrest(game: Game, register):
    """Techs listed in contentment.techs add points, soften tribute and slow unrest."""
    alice, bob, target = await neighbours(game, register)
    techs = {"philosophy": {"contentment": 3, "unrest": 0.5, "tribute": 0.5, "rebel_below": -5, "calm": 2}}
    with extensions(game, contentment={"techs": techs}, submission={"benefits": {}}):
        async with game.tx() as tx:
            lord = await get_village(tx.conn, alice.village_id, lock=True)
            vassal = await get_village(tx.conn, bob.village_id, lock=True)
            await submit(game, tx, vassal, lord)
            contentment.add_effect(game, vassal.meta, "contentment", "Famine", -40, 100)
            vassal.meta["unrest_at"] = game.clock.now()
            await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", vassal.id, vassal.meta)
        plain = (await bob.village())["contentment"]
        assert "politics" not in plain or not plain["politics"]
        game.clock.value += HOUR
        u_plain = (await bob.village())["contentment"]["unrest"]

        await patch_state(game, bob.village_id, lambda s: s.update(techs=["philosophy"]))
        async with game.tx() as tx:
            v = await get_village(tx.conn, bob.village_id, lock=True)
            v.meta["unrest"], v.meta["unrest_at"] = 0.0, game.clock.now()
            await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
        c = (await bob.village())["contentment"]
        f = {x["label"]: x["value"] for x in c["factors"]}
        assert f["Philosophy"] == 3
        assert f["Tribute to an overlord"] == plain_factor(plain, "Tribute to an overlord") * 0.5
        assert c["rebel_below"] == plain["rebel_below"] - 5
        assert c["politics"] == {"unrest": 0.5, "tribute": 0.5, "calm": 2.0, "rebel_below": -5.0}
        game.clock.value += HOUR
        u_wise = (await bob.village())["contentment"]["unrest"]
        # higher score, lower line, half the speed
        assert 0 < u_wise < u_plain / 2, (u_wise, u_plain)


def plain_factor(c: dict, label: str) -> float:
    return next(x["value"] for x in c["factors"] if x["label"] == label)
