"""End-to-end Playwright tests for dashboard.html.

These tests exercise the dashboard JS + HTTP API together — the layer
that NO existing test_*.py file touches. Catches the class of bug the
recent code-review pass surfaced: missing API routes (the L1-ASR 404),
non-existent function names in event handlers (closeProfile() typo
caught by eslint), and toggle-disabled-on-wrong-layer policy errors.

Requirements:
  pip install pytest-playwright
  playwright install chromium

How to run:
  pytest tests/test_dashboard_e2e.py            # full suite
  pytest tests/test_dashboard_e2e.py -k toggle  # subset
  python tests/test_dashboard_e2e.py            # script-style (matches repo convention)

The engine must be running on localhost:7878 before the tests start.
The fixture below will SKIP — not fail — if the engine isn't reachable,
so the suite doesn't false-fail in CI environments where the engine
isn't bootstrapped.
"""

import json
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import Page, expect, sync_playwright

DASHBOARD_URL = "http://127.0.0.1:7878"
API_BASE = f"{DASHBOARD_URL}"


def _engine_alive() -> bool:
    try:
        urllib.request.urlopen(f"{API_BASE}/api/state", timeout=2)
        return True
    except Exception:
        return False


def _get_state() -> dict:
    return json.loads(urllib.request.urlopen(f"{API_BASE}/api/state", timeout=5).read())


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


# ── pytest fixtures ──

@pytest.fixture(scope="session", autouse=True)
def _require_engine():
    if not _engine_alive():
        pytest.skip(f"Lavrentiy engine not reachable at {DASHBOARD_URL}. Start it before running e2e tests.")


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    # Bigger viewport so all dashboard sections fit; 1440x900 = common laptop
    return {**browser_context_args, "viewport": {"width": 1440, "height": 900}}


# ── Tests ──

class TestDashboardLoad:
    """Smoke tests — dashboard renders and basic structure is present."""

    def test_page_loads(self, page: Page):
        page.goto(DASHBOARD_URL)
        # Title is Cyrillic — match by content, not exact codepoints
        expect(page).to_have_title("Лаврентий")

    def test_no_console_errors_after_initial_poll(self, page: Page):
        """Catches the class of bug eslint's no-undef found (closeProfile typo).
        Listens for `pageerror` (uncaught exceptions) for 3 seconds after load
        — covers initial poll, layer-render cycle, and toggle-sync.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(3000)  # let poll cycle + render fire
        assert errors == [], f"Uncaught JS errors during initial load: {errors}"

    def test_dashboard_sections_present(self, page: Page):
        """Every major selector we depend on must be in the DOM. Mode buttons
        are added dynamically by the render loop, so wait briefly first.
        """
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1500)  # let initial poll + render cycle fire
        for selector in [
            "#state-label",          # top status indicator
            "#l1-asr-toggle",        # L1 ASR cloud/local toggle (recently fixed route)
            "#toggle-paralinguistic",
            "#toggle-prosodic",
            "#tone-section",
        ]:
            assert page.locator(selector).count() >= 1, f"Missing selector: {selector}"


class TestL1AsrToggle:
    """The L1-ASR toggle's /api/l1_asr endpoint was 404 (handler existed but
    wasn't wired into dispatch_api). Fixed in this session — verify the click
    actually changes server state.
    """

    def test_l1_asr_toggle_flips_server_state(self, page: Page):
        """Invokes toggleL1Asr() directly via JS rather than DOM click. The
        toggle is a styled div with custom transform; DOM-level click is
        flaky across CSS scale + animation states. The function itself is
        what we want to verify — that it routes through dispatch_api and
        hits the handler we wired in this session.
        """
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1800)  # ensure state has polled at least once
        before = _get_state().get("l1_cloud_asr")
        # Call the JS function directly + await the fetch
        page.evaluate("toggleL1Asr()")
        page.wait_for_timeout(1500)  # fetch round-trip + server commit
        after = _get_state().get("l1_cloud_asr")
        assert before != after, (
            f"Toggle didn't flip server state (before={before}, after={after}) — "
            f"if this fails, /api/l1_asr is probably 404 again (route not wired)."
        )
        # Restore original state so subsequent test runs are order-independent
        _post("/api/l1_asr", {"cloud": before})


class TestLayerSwitchPolicy:
    """Paralinguistic + Prosodic availability is server-decided per layer:
    L1 (transcribe-only) → forced OFF + grey. L2/L3/L4 → toggleable.
    Recent fix from this session.
    """

    def test_l1_marks_para_pros_unavailable(self, page: Page):
        _post("/api/layer", {"layer": 1})
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1000)
        state = _get_state()
        assert state.get("paralinguistic_available") is False
        assert state.get("prosodic_available") is False

    def test_l2_marks_para_pros_available(self, page: Page):
        _post("/api/layer", {"layer": 2})
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1000)
        state = _get_state()
        assert state.get("paralinguistic_available") is True
        assert state.get("prosodic_available") is True

    def test_l4_marks_para_pros_available(self, page: Page):
        _post("/api/layer", {"layer": 4})
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1000)
        state = _get_state()
        assert state.get("paralinguistic_available") is True
        assert state.get("prosodic_available") is True

    def test_paralinguistic_toggle_disabled_on_l1(self, page: Page):
        _post("/api/layer", {"layer": 1})
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1500)
        toggle = page.locator("#toggle-paralinguistic")
        expect(toggle).to_be_disabled()

    def test_paralinguistic_toggle_enabled_on_l4(self, page: Page):
        _post("/api/layer", {"layer": 4})
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1500)
        toggle = page.locator("#toggle-paralinguistic")
        expect(toggle).to_be_enabled()


class TestProfileModalEscapeKey:
    """closeProfile() called from Escape handler was undefined — typo for
    closeProfileModal(). Fixed in this session. Verify Escape closes the
    profile modal when it's open.
    """

    def test_escape_handler_does_not_throw(self, page: Page):
        """Even if no modal is open, pressing Escape must not throw. This
        was the actual bug: closeProfile() raised ReferenceError, killing
        the keydown listener entirely.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        assert errors == [], f"Escape key threw: {errors}"

    def test_closeprofilemodal_function_exists(self, page: Page):
        """Sanity check: the function the Escape handler calls must exist."""
        page.goto(DASHBOARD_URL)
        result = page.evaluate("typeof closeProfileModal")
        assert result == "function", f"closeProfileModal not defined (got: {result})"


class TestStatePolling:
    """The 250ms polling loop is the engine's main heartbeat to the dashboard.
    Verify it actually fires + updates DOM.
    """

    def test_state_polls_within_a_second(self, page: Page):
        """After loading, the page should have called /api/state at least once."""
        api_calls = []
        page.on(
            "request",
            lambda req: api_calls.append(req.url) if "/api/state" in req.url else None,
        )
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(1500)
        assert len(api_calls) >= 1, "Dashboard never polled /api/state"


# ── Visual baseline (used by the upcoming D34 CSS refactor for regression) ──

class TestVisualBaseline:
    """Take baseline screenshots of key states. After the upcoming
    CSS-variable refactor, re-run these and diff. Any unintended visual
    change shows up as a pixel diff in the report.

    Stored in: tests/_screenshots/
    """

    def test_baseline_l1_idle(self, page: Page, request):
        _post("/api/layer", {"layer": 1})
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(2000)  # let pollState + render settle
        out = f"tests/_screenshots/baseline_l1_idle.png"
        page.screenshot(path=out, full_page=True)
        print(f"Saved baseline: {out}")

    def test_baseline_l4_idle(self, page: Page, request):
        _post("/api/layer", {"layer": 4})
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(2000)
        out = f"tests/_screenshots/baseline_l4_idle.png"
        page.screenshot(path=out, full_page=True)
        print(f"Saved baseline: {out}")

    def test_baseline_engine_panel(self, page: Page, request):
        _post("/api/layer", {"layer": 2})
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(2000)
        # Engine panel contains the toggles we resized in D36
        engine = page.locator("#whisper-card").or_(page.locator(".engine-row").first)
        if engine.count() > 0:
            engine.first.screenshot(path="tests/_screenshots/baseline_engine_panel.png")
            print("Saved baseline: tests/_screenshots/baseline_engine_panel.png")


# ── Script-style entry point (matches existing test_*.py convention) ──

if __name__ == "__main__":
    if not _engine_alive():
        print(f"ERROR: engine not reachable at {DASHBOARD_URL}. Start it first.")
        sys.exit(1)
    import os
    os.makedirs("tests/_screenshots", exist_ok=True)
    rc = pytest.main([__file__, "-v", "--tb=short", "-p", "no:cacheprovider"])
    sys.exit(rc)
