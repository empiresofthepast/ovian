"""Browser walkthrough of the diorama front end with Playwright. Saves screenshots.

    docker run --rm --network ovian_default -v "$PWD/scripts:/s:ro" -v "$PWD/shots:/shots" \
      mcr.microsoft.com/playwright/python:v1.49.0-noble \
      sh -c "pip -q install playwright==1.49.0 && python /s/e2e_diorama.py"

Env: OVIAN_DIORAMA (default http://diorama), OVIAN_SHOTS (default /shots), OVIAN_CIV (default rome).
"""

from __future__ import annotations

import os
import sys
import uuid

from playwright.sync_api import expect, sync_playwright

WEB = os.environ.get("OVIAN_DIORAMA", "http://diorama")
SHOTS = os.environ.get("OVIAN_SHOTS", "/shots")
CIV = os.environ.get("OVIAN_CIV", "Romans")
failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def main() -> int:
    os.makedirs(SHOTS, exist_ok=True)
    name = "dio" + uuid.uuid4().hex[:6]
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        shot = lambda n: page.screenshot(path=f"{SHOTS}/{n}.png")  # noqa: E731

        page.goto(WEB)
        expect(page.locator(".civ").first).to_be_visible(timeout=20000)
        check(page.locator(".civ").count() >= 3, f"{page.locator('.civ').count()} civilizations offered")
        page.get_by_label("Name").fill(name)
        page.get_by_label("Password").fill("password123")
        page.locator(".civ", has_text=CIV).click()
        expect(page.locator(".roster__unit").first).to_be_visible()
        shot("d01-welcome")
        page.locator("form button.btn--gold").click()

        expect(page.locator("canvas.scene-canvas")).to_be_visible(timeout=20000)
        expect(page.locator(".topbar__village")).to_contain_text(name, timeout=15000)
        check(page.locator(".res").count() >= 4, "resource bar with 0 A.D. icons")
        expect(page.locator(".tutorial")).to_be_visible(timeout=10000)
        check("next step" in page.locator(".tutorial").inner_text().lower(), "tutorial shows the first step")
        check(page.locator(".season-chip").count() == 1 and page.locator(".mood-chip").count() == 1, "season and mood in the top bar")
        page.wait_for_timeout(9000)  # meshes stream in
        shot("d02-village")

        # click the centre of the screen area where the first ring sites are: use the scene's own picking
        box = page.locator("canvas.scene-canvas").bounding_box()
        assert box
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        found = False
        for dx, dy in [(0, 0), (0, 40), (120, 30), (-120, 30), (0, 120), (160, 110), (-160, 110), (60, -60)]:
            page.mouse.click(cx + dx, cy + dy)
            page.wait_for_timeout(400)
            if page.locator(".selection").count():
                found = True
                break
        check(found, "clicking the village selects a site")
        shot("d03-selected")
        if page.locator(".selection .btn--gold", has_text="Upgrade").count():
            page.locator(".selection .btn--gold", has_text="Upgrade").click()
            expect(page.locator(".queue .job").first).to_be_visible(timeout=8000)
            check(True, "upgrade queued from the selection panel")
            page.wait_for_timeout(1500)
            shot("d04-queued")
        page.keyboard.press("Escape")

        # screens over the city
        page.locator(".navbtn", has_text="Map").click()
        expect(page.locator(".worldmap canvas")).to_be_visible(timeout=8000)
        page.wait_for_timeout(2500)
        mb = page.locator(".worldmap canvas").bounding_box()
        assert mb
        page.mouse.click(mb["x"] + mb["width"] / 2 - 3, mb["y"] + mb["height"] / 2 - 3)
        page.wait_for_timeout(500)
        check("Your city" in page.locator(".worldmap__info").inner_text(), "map: own city is in the middle and selectable")
        shot("d06-map")
        page.keyboard.press("Escape")
        expect(page.locator(".worldmap")).to_have_count(0)
        check(True, "Escape closes the map")

        page.keyboard.press("r")
        expect(page.locator(".rally")).to_be_visible(timeout=5000)
        check(page.locator(".rally > .rally__cols .seg__opt").count() == 4, "rally point: attack, raid, scout, reinforce")
        shot("d07-rally")
        page.keyboard.press("k")
        expect(page.locator(".rankings .civcell img").first).to_be_visible(timeout=5000)
        check(page.locator(".rankings .civcell img").count() > 0, "rankings with civ emblems")
        shot("d08-rankings")
        page.locator(".rankings .seg__opt", has_text="Medals").click()
        expect(page.locator(".medal-cat").first).to_be_visible(timeout=5000)
        check(page.locator(".medal-cat").count() >= 4, "rankings: medal categories")
        page.locator(".rankings .seg__opt", has_text="Hall of fame").click()
        page.wait_for_timeout(300)
        shot("d10-medals")
        page.keyboard.press("g")
        expect(page.locator(".realm")).to_be_visible(timeout=5000)
        check(page.locator(".realm .mood").count() == 1, "realm: contentment of the city")
        page.locator(".realm .seg__opt", has_text="Government").click()
        expect(page.locator(".gov").first).to_be_visible(timeout=5000)
        check(page.locator(".gov").count() >= 4, "realm: governments to choose from")
        shot("d11-realm")
        page.keyboard.press("y")
        expect(page.locator(".festival .season").first).to_be_visible(timeout=5000)
        check(page.locator(".festival .season").count() == 4 and page.locator(".contest").count() >= 3, "year: four seasons and the games")
        shot("d12-year")
        page.keyboard.press("n")
        expect(page.locator(".chronicle .timeline__item").first).to_be_visible(timeout=5000)
        check(name in page.locator(".chronicle").inner_text(), "chronicle: our founding is recorded")
        shot("d13-chronicle")
        page.locator(".navmore > button").click()
        page.locator(".navmore__item", has_text="Settings").click()
        expect(page.locator(".settings")).to_be_visible(timeout=5000)
        page.locator(".opt", has_text="Level badges").locator("input").uncheck()
        page.wait_for_timeout(300)
        check(page.locator(".scene-labels").get_attribute("hidden") is not None, "settings: badges can be hidden")
        page.locator(".opt", has_text="Level badges").locator("input").check()
        shot("d09-settings")
        page.locator(".navbtn", has_text="City").click()
        expect(page.locator(".dialog")).to_have_count(0)

        real = [e for e in errors if "favicon" not in e and "WebGL" not in e and "GPU stall" not in e]
        check(not real, f"no console errors {real[:4]}")
        page.set_viewport_size({"width": 420, "height": 860})
        page.wait_for_timeout(1500)
        shot("d05-mobile")

        # clean up: delete the throwaway account through the settings
        page.set_viewport_size({"width": 1400, "height": 900})
        page.locator(".navmore > button").click()
        page.locator(".navmore__item", has_text="Settings").click()
        page.locator(".danger-zone summary").click()
        page.get_by_label("Type your username to confirm").fill(name)
        page.locator(".danger-zone").get_by_label("Your password").fill("password123")
        page.locator(".danger-zone button.btn--danger").click()
        expect(page.locator(".danger-zone button.btn--danger")).to_have_text("Really delete, for good")
        shot("d14-delete")
        page.locator(".danger-zone button.btn--danger").click()
        expect(page.locator(".civ").first).to_be_visible(timeout=10000)
        check(True, "account deleted from the settings, back at the welcome page")
        browser.close()
    print(f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
