"""Pure monthly quota calculations for the WiM Cloud backend."""

import time


def month_key(now=None):
    """Return the UTC billing-usage period for a Unix timestamp."""
    timestamp = time.time() if now is None else float(now)
    return time.strftime("%Y-%m", time.gmtime(timestamp))


def usage_period_key(data, now=None):
    """Use the verified subscription expiry as the quota-cycle boundary.

    A calendar-month reset lets a new subscriber receive two full quotas by
    joining at month-end. The Play-verified period end changes only on renewal,
    so it is a stable key for one paid subscription period. Legacy/manual tiers
    without an expiry retain a UTC calendar-month key.
    """
    try:
        expiry = float(data.get("billing_expiry_ts", 0) or 0)
    except (TypeError, ValueError):
        expiry = 0
    return f"subscription:{int(expiry)}" if expiry > 0 else month_key(now)


def plan_cloud_usage(data, monthly_limit, l4_limit, layer=None, period=None):
    """Plan one cloud request without mutating *data*.

    Returns ``(ok, remaining, error_code, update_fields)``. L4 requests consume
    one general slot and one L4 slot; other requests consume one general slot.
    """
    period = period or usage_period_key(data)
    same_period = data.get("usage_period") == period
    count = int(data.get("monthly_count", 0)) if same_period else 0
    l4_count = int(data.get("l4_monthly_count", 0)) if same_period else 0
    is_l4 = layer is not None and int(layer) >= 4

    if count >= int(monthly_limit):
        return False, 0, "monthly_quota_reached", {}
    if is_l4 and l4_count >= int(l4_limit):
        return False, 0, "l4_monthly_quota_reached", {}

    update = {
        "usage_period": period,
        "monthly_count": count + 1,
        "l4_monthly_count": l4_count + (1 if is_l4 else 0),
    }
    remaining = int(monthly_limit) - count - 1
    if is_l4:
        remaining = min(remaining, int(l4_limit) - l4_count - 1)
    return True, remaining, None, update


def plan_audio_usage(data, monthly_limit, period=None, seconds=0, seconds_limit=None):
    """Plan one cloud-audio transcription without mutating *data*.

    Returns ``(ok, remaining, error_code, update_fields)``. Two caps guard the
    audio bill: a count of uploads per period and, since 2026-10-11, a total of
    audio seconds per period. The count alone let one subscriber send 300
    six-minute takes (~32 hours, ~$20 of transcription against a $4.99 plan);
    the seconds cap bounds that to the minutes a heavy real talker uses.
    """
    period = period or usage_period_key(data)
    same_period = data.get("audio_usage_period") == period
    count = int(data.get("audio_monthly_count", 0)) if same_period else 0
    used_seconds = float(data.get("audio_monthly_seconds", 0) or 0) if same_period else 0.0
    seconds = max(0.0, float(seconds or 0))
    if count >= int(monthly_limit):
        return False, 0, "monthly_audio_quota_reached", {}
    if seconds_limit is not None and used_seconds + seconds > float(seconds_limit):
        return False, 0, "monthly_audio_minutes_reached", {}
    return True, int(monthly_limit) - count - 1, "", {
        "audio_usage_period": period,
        "audio_monthly_count": count + 1,
        "audio_monthly_seconds": round(used_seconds + seconds, 1),
    }
