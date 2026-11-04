"""Content packs and plugins load without a database."""

from __future__ import annotations

from ovian_server.clock import ManualClock
from ovian_server.config import Settings
from ovian_server.game import Game
from ovian_server.hooks import hookimpl
from ovian_server.realtime import filter_covers, topic_matches

from .conftest import ROOT


def make(pack: str, **kw) -> Game:
    return Game(Settings(content_dir=str(ROOT / "content" / pack), mqtt_url="", **kw), clock=ManualClock())


def test_isles_pack_runs_on_the_same_server():
    g = make("isles")
    assert g.content.pack["world"]["generator"] == "islands"
    v = g.engine.create_village(0)
    assert set(v["resources"]) == {"wood", "marble", "crystal", "wine"}
    assert g.engine.upkeep_resource == "wine"
    assert {m.name for m in g.modules} >= {"auth", "villages", "military", "chat"}


def test_antiquity_pack_has_the_0ad_civilizations():
    g = make("antiquity")
    tribes = g.content.tribe_ids()
    assert len(tribes) == 15 and {"rome", "athen", "han"} <= set(tribes)
    # every civ fields infantry and cavalry, and its art mapping travels with the pack
    for t in tribes:
        classes = {u["class"] for u in g.content.pack["units"] if u["tribe"] == t}
        assert classes == {"infantry", "cavalry"}, t
    assert g.content.extensions["zeroad"]["tribes"]["rome"]["buildings"]["barracks"]["actor"]
    eco = g.engine.economy(g.engine.create_village(0), 0)
    assert eco["phase"] == "village" and eco["center_sites"] == 8


def test_world_speed_override():
    assert make("classic", world_speed=10).content.pack["world"]["speed"] == 10


def test_pack_loaded_hook_can_rebalance(monkeypatch):
    class Cheap:
        @hookimpl
        def ovian_pack_loaded(self, pack):
            for b in pack["buildings"]:
                b["cost"]["factor"] = 1.0

    import ovian_server.game as game_mod

    original = game_mod.Game._load_plugins

    def load_with_cheap(self):
        original(self)
        self.pm.register(Cheap())

    monkeypatch.setattr(game_mod.Game, "_load_plugins", load_with_cheap)
    g = make("classic")
    assert g.engine.build_cost("woodcutter", 10) == g.engine.build_cost("woodcutter", 1)


def test_mqtt_filters():
    assert topic_matches("ovian/w1/chat/+/in/+", "ovian/w1/chat/global/in/3")
    assert not topic_matches("ovian/w1/chat/+", "ovian/w1/chat/global/in/3")
    assert filter_covers("ovian/w1/player/3/#", "ovian/w1/player/3/events")
    assert not filter_covers("ovian/w1/chat/+", "ovian/w1/chat/#")
