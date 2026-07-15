"""Offline monthly quota contract tests (no Firebase credentials needed)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))
from quota_backend import month_key, plan_audio_usage, plan_cloud_usage, usage_period_key


assert month_key(0) == "1970-01"
assert usage_period_key({"billing_expiry_ts": 1_800_000_000}) == "subscription:1800000000"
assert usage_period_key({}, now=0) == "1970-01"

ok, remaining, error, update = plan_cloud_usage({}, 300, 20, layer=2, period="2026-07")
assert (ok, remaining, error) == (True, 299, None)
assert update == {
    "usage_period": "2026-07", "monthly_count": 1, "l4_monthly_count": 0,
}

ok, remaining, error, update = plan_cloud_usage({
    "usage_period": "2026-07", "monthly_count": 9, "l4_monthly_count": 4,
}, 300, 20, layer=4, period="2026-07")
assert (ok, remaining, error) == (True, 15, None)
assert update["monthly_count"] == 10 and update["l4_monthly_count"] == 5

ok, remaining, error, update = plan_cloud_usage({
    "usage_period": "2026-07", "monthly_count": 300,
}, 300, 20, layer=2, period="2026-07")
assert (ok, remaining, error, update) == (False, 0, "monthly_quota_reached", {})

ok, remaining, error, update = plan_cloud_usage({
    "usage_period": "2026-07", "monthly_count": 50, "l4_monthly_count": 20,
}, 300, 20, layer=4, period="2026-07")
assert (ok, remaining, error, update) == (False, 0, "l4_monthly_quota_reached", {})

# A new UTC month resets both counters instead of inheriting stale usage.
ok, remaining, error, update = plan_cloud_usage({
    "usage_period": "2026-06", "monthly_count": 300, "l4_monthly_count": 20,
}, 300, 20, layer=4, period="2026-07")
assert (ok, remaining, error) == (True, 19, None)
assert update["monthly_count"] == 1 and update["l4_monthly_count"] == 1

# Renewal changes the verified expiry key and resets the paid-period quota.
ok, remaining, error, update = plan_cloud_usage({
    "billing_expiry_ts": 1_800_000_000,
    "usage_period": "subscription:1700000000",
    "monthly_count": 300,
    "l4_monthly_count": 20,
}, 300, 20, layer=4)
assert (ok, remaining, error) == (True, 19, None)
assert update["usage_period"] == "subscription:1800000000"

ok, remaining, update = plan_audio_usage({
    "audio_usage_period": "2026-07", "audio_monthly_count": 299,
}, 300, period="2026-07")
assert (ok, remaining, update["audio_monthly_count"]) == (True, 0, 300)

ok, remaining, update = plan_audio_usage({
    "audio_usage_period": "2026-07", "audio_monthly_count": 300,
}, 300, period="2026-07")
assert (ok, remaining, update) == (False, 0, {})

print("PASSED: monthly quota backend contract")
