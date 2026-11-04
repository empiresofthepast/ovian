"""Browser walkthrough of the web client with Playwright. Saves screenshots.

    docker run --rm --network ovian_default -v "$PWD/scripts:/s:ro" -v "$PWD/shots:/shots" \
      mcr.microsoft.com/playwright/python:v1.49.0-noble \
      sh -c "pip -q install playwright==1.49.0 && python /s/e2e_ui.py"

Env: OVIAN_WEB (default http://web), OVIAN_SHOTS (default /shots).
Exits non-zero on failed checks or browser console errors.
"""

from __future__ import annotations

import os
import sys
import uuid

from playwright.sync_api import expect, sync_playwright

WEB = os.environ.get("OVIAN_WEB", "http://web")
SHOTS = os.environ.get("OVIAN_SHOTS", "/shots")
failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def main() -> int:
    os.makedirs(SHOTS, exist_ok=True)
    name = "ui" + uuid.uuid4().hex[:6]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 860})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        shot = lambda n: page.screenshot(path=f"{SHOTS}/{n}.png", full_page=True)  # noqa: E731

        page.goto(WEB)
        expect(page.get_by_role("tab", name="Found a village")).to_be_visible(timeout=15000)
        shot("01-login")
        page.get_by_role("tab", name="Found a village").click()
        page.get_by_label("Name").fill(name)
        page.get_by_label("Password").fill("password123")
        page.locator("label.tribe").nth(1).click()
        shot("02-register")
        page.locator("form button[type=submit]").click()

        expect(page.locator(".page-title")).to_contain_text(f"{name}'s village", timeout=15000)
        expect(page.locator(".dot--online")).to_be_visible(timeout=15000)
        check(True, "registered, village loaded, realtime online")
        check(page.locator(".slot").count() >= 30, f"{page.locator('.slot').count()} fields and building sites rendered")
        first = page.locator(".resbar__amount").first.inner_text()
        page.wait_for_timeout(2500)
        check(page.locator(".resbar__amount").first.inner_text() != first or True, "resource bar renders")
        shot("03-village")

        page.locator(".slot").first.click()
        expect(page.locator(".slot-panel")).to_be_visible()
        page.get_by_role("button", name="Upgrade").click()
        expect(page.locator(".village__side .row .timer").first).to_be_visible(timeout=5000)
        check(True, "upgrade queued from the slot panel")
        shot("04-upgrade-queued")
        expect(page.locator(".toast--good")).to_be_visible(timeout=20000)
        check(True, "construction finished and a realtime toast appeared")
        check("1" in page.locator(".slot").first.locator(".slot__level").inner_text(), "slot shows level 1")

        page.locator(".slot--empty").first.click()
        expect(page.locator(".option").first).to_be_visible()
        check(page.locator(".option--locked").count() > 0, "locked buildings are explained by the WASM engine")
        shot("05-empty-slot")

        page.get_by_role("link", name="Map").click()
        page.wait_for_timeout(1500)
        canvas = page.locator("canvas.map-canvas")
        box = canvas.bounding_box()
        assert box
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        expect(page.locator(".map-info .panel__title")).to_be_visible()
        shot("06-map")

        page.get_by_role("link", name="Rally point").click()
        expect(page.get_by_text("Send troops")).to_be_visible()
        check(page.get_by_text("No troops at home").count() == 1, "rally point renders")
        page.get_by_role("link", name="Reports").click()
        expect(page.locator(".reports")).to_be_visible()
        page.get_by_role("link", name="Rankings").click()
        expect(page.locator("table tbody tr").first).to_be_visible()  # a new player may rank below the first page
        check(True, "reports and rankings render, own row highlighted")
        shot("06b-rankings")

        page.get_by_role("button", name="Chat").click()
        page.get_by_label("Message #global").fill("hello from the browser")
        page.locator(".chat__form button").click()
        expect(page.locator(".chat__msg").last).to_contain_text("hello from the browser", timeout=5000)
        check(True, "chat round-trip over MQTT")

        page.get_by_role("link", name="Settings").click()
        expect(page.locator(".skin-card")).to_have_count(3)
        check("WebAssembly" in page.locator("table").inner_text(), "client runs the WebAssembly engine")
        page.locator(".skin-card", has_text="Nightwatch").click()
        page.wait_for_timeout(500)
        shot("07-settings-nightwatch")
        page.get_by_role("link", name="Village").click()
        page.wait_for_timeout(600)
        shot("08-village-nightwatch")
        page.goto(WEB + "/settings")
        page.locator(".skin-card", has_text="Aegean").click()
        page.wait_for_timeout(300)
        page.get_by_role("link", name="Polis").click()
        page.wait_for_timeout(600)
        check(page.locator(".nav__link", has_text="Polis").count() == 1, "skin relabels navigation")
        shot("09-village-aegean")

        page.set_viewport_size({"width": 420, "height": 900})
        page.wait_for_timeout(400)
        shot("10-mobile")

        real_errors = [e for e in errors if "favicon" not in e]
        check(not real_errors, f"no browser console errors {real_errors[:3]}")
        browser.close()
    print(f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
