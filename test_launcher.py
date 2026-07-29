"""Regression tests for the frozen desktop launcher.

Runs without the engine, WebView2, audio hardware, or network.
"""
import sys
import types

import lavrentiy_launcher as launcher


passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


print("=== Existing-engine native reopen ===")

events = []
fake_webview = types.ModuleType("webview")
fake_webview.windows = []


def fake_create_window(**kwargs):
    events.append(("create", kwargs))


def fake_start(gui=None):
    events.append(("start", gui))


fake_webview.create_window = fake_create_window
fake_webview.start = fake_start

original_webview = sys.modules.get("webview")
original_port_is_open = launcher._port_is_open
original_native_log = launcher._native_log
original_show_error = launcher._show_error_dialog
original_lavrentiy = sys.modules.pop("lavrentiy", None)

try:
    sys.modules["webview"] = fake_webview
    launcher._port_is_open = lambda port: True
    launcher._native_log = lambda message: events.append(("log", message))
    launcher._show_error_dialog = lambda *args, **kwargs: events.append(("error", args))

    launcher._run_native_window()

    create_events = [event for event in events if event[0] == "create"]
    check("reopens one native window", len(create_events) == 1)
    check(
        "reopened window uses live dashboard",
        create_events[0][1].get("url") == launcher.DASHBOARD_URL,
    )
    check("does not import a second engine", "lavrentiy" not in sys.modules)
    check(
        "logs existing-engine route",
        any(
            event[0] == "log" and "existing engine detected" in event[1]
            for event in events
        ),
    )
    check("starts WebView2", ("start", "edgechromium") in events)
    check("does not show an error", not any(event[0] == "error" for event in events))
finally:
    launcher._port_is_open = original_port_is_open
    launcher._native_log = original_native_log
    launcher._show_error_dialog = original_show_error
    if original_webview is None:
        sys.modules.pop("webview", None)
    else:
        sys.modules["webview"] = original_webview
    if original_lavrentiy is not None:
        sys.modules["lavrentiy"] = original_lavrentiy

print()
print("=" * 40)
print(f"  PASSED: {passed}")
print(f"  FAILED: {failed}")
print("=" * 40)
sys.exit(1 if failed else 0)
