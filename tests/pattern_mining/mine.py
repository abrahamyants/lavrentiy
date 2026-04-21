"""
Cross-session pattern mining for Lavrentiy history.db.

Surfaces patterns nobody's asked for by default: fluency trends, onset
frequencies, situation breakdowns, day/hour heatmaps, edit-distance trends.
Pure SQL + simple stats — no API calls, no new deps.

Usage from repo root:
    python3 tests/pattern_mining/mine.py

Writes JSON + HTML report next to this file.
"""
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
PROFILES_DIR = Path.home() / ".lavrentiy" / "profiles"


def discover_db():
    # Prefer the active profile per ~/.lavrentiy/active_profile
    active_file = Path.home() / ".lavrentiy" / "active_profile"
    if active_file.exists():
        name = active_file.read_text(encoding="utf-8").strip()
        db = PROFILES_DIR / name / "history.db"
        if db.exists():
            return name, db
    # Fall back to the largest db found
    candidates = [(p.parent.name, p) for p in PROFILES_DIR.glob("*/history.db")]
    if not candidates:
        raise SystemExit("No history.db found under ~/.lavrentiy/profiles/")
    candidates.sort(key=lambda x: x[1].stat().st_size, reverse=True)
    return candidates[0]


def parse_ts(s):
    # Accept ISO-ish or unix-epoch; return datetime or None
    if s is None:
        return None
    if isinstance(s, (int, float)):
        try:
            return datetime.fromtimestamp(s, tz=timezone.utc)
        except Exception:
            return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def mine(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Introspect schema
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]

    total_rows = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    print("sessions table cols:", cols)
    print("total rows:", total_rows)

    # Pull everything (these are text, no giant blobs)
    rows = conn.execute("SELECT * FROM sessions").fetchall()
    sessions = [dict(r) for r in rows]
    conn.close()

    report = {"total_sessions": total_rows, "columns": cols}

    # --- time distribution ---
    ts_col = next((c for c in cols if c.lower() in ("ts", "timestamp", "created", "created_at", "time")), None)
    if ts_col:
        parsed = [(s, parse_ts(s.get(ts_col))) for s in sessions]
        valid = [(s, t) for s, t in parsed if t is not None]
        if valid:
            earliest = min(t for _, t in valid)
            latest = max(t for _, t in valid)
            report["earliest_session"] = earliest.isoformat()
            report["latest_session"] = latest.isoformat()
            span_days = (latest - earliest).days or 1
            report["span_days"] = span_days
            report["sessions_per_day_avg"] = round(len(valid) / span_days, 2)

            # By day of week / hour of day
            dow = Counter(t.strftime("%a") for _, t in valid)
            hour = Counter(t.hour for _, t in valid)
            report["sessions_by_day_of_week"] = dict(dow)
            report["sessions_by_hour"] = dict(sorted(hour.items()))

    # --- numeric metric aggregates (auto-discover numeric columns) ---
    numeric_cols = []
    for c in cols:
        sample = [s.get(c) for s in sessions[:200] if s.get(c) is not None]
        if sample and all(isinstance(v, (int, float)) for v in sample):
            numeric_cols.append(c)
    report["numeric_columns"] = numeric_cols

    metrics = {}
    for c in numeric_cols:
        vals = [s[c] for s in sessions if isinstance(s.get(c), (int, float))]
        if not vals:
            continue
        metrics[c] = {
            "n": len(vals),
            "mean": round(mean(vals), 3),
            "median": round(median(vals), 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
        }
    report["numeric_aggregates"] = metrics

    # --- situation breakdown ---
    sit_col = next((c for c in cols if c.lower() in ("situation", "sit", "context")), None)
    if sit_col:
        sit = Counter((s.get(sit_col) or "unknown") for s in sessions)
        report["situation_breakdown"] = dict(sit.most_common())

    # --- tone breakdown ---
    tone_col = next((c for c in cols if c.lower() == "tone"), None)
    if tone_col:
        tone = Counter((s.get(tone_col) or "unknown") for s in sessions)
        report["tone_breakdown"] = dict(tone.most_common())

    # --- layer breakdown ---
    layer_col = next((c for c in cols if c.lower() == "layer"), None)
    if layer_col:
        layer = Counter((s.get(layer_col) or "unknown") for s in sessions)
        report["layer_breakdown"] = dict(layer.most_common())

    # --- raw → output length ratio (rough proxy for how aggressively Lavrentiy is cleaning) ---
    raw_col = next((c for c in cols if c.lower() in ("raw", "raw_text", "input")), None)
    out_col = next((c for c in cols if c.lower() in ("out", "output", "clean", "clean_text", "final")), None)
    if raw_col and out_col:
        ratios = []
        for s in sessions:
            r = s.get(raw_col) or ""
            o = s.get(out_col) or ""
            if isinstance(r, str) and isinstance(o, str) and r.strip():
                rw = len(r.split())
                ow = len(o.split())
                if rw:
                    ratios.append(ow / rw)
        if ratios:
            report["clean_to_raw_word_ratio"] = {
                "n": len(ratios),
                "mean": round(mean(ratios), 3),
                "median": round(median(ratios), 3),
                "min": round(min(ratios), 3),
                "max": round(max(ratios), 3),
            }

    # --- onset frequency ---
    # Two views: (1) raw over every word (dominated by function-word onsets —
    # "the/to/it/a/in" etc.), (2) content-word only (filter out the ~100 most
    # common English function words plus very short words). The second view
    # is the one that actually maps to stutter-prone positions.
    FUNCTION_WORDS = {
        "the", "a", "an", "and", "or", "but", "if", "of", "at", "by", "for",
        "to", "in", "on", "up", "down", "with", "from", "as", "into", "through",
        "over", "under", "out", "off", "is", "am", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "having", "do", "does", "did",
        "doing", "will", "would", "shall", "should", "can", "could", "may",
        "might", "must", "i", "me", "my", "mine", "myself", "you", "your",
        "yours", "yourself", "he", "him", "his", "himself", "she", "her",
        "hers", "herself", "it", "its", "itself", "we", "us", "our", "ours",
        "ourselves", "they", "them", "their", "theirs", "themselves", "this",
        "that", "these", "those", "what", "which", "who", "whom", "whose",
        "where", "when", "why", "how", "all", "any", "each", "every", "some",
        "no", "not", "so", "very", "too", "just", "than", "then", "there",
        "here", "one", "two",
    }
    if raw_col:
        all_counter = Counter()
        all_total = 0
        content_counter = Counter()
        content_total = 0
        for s in sessions:
            r = s.get(raw_col) or ""
            if not isinstance(r, str):
                continue
            for w in r.split():
                w = w.strip(".,!?;:\"'()[]{}").lower()
                if not (w and w[0].isalpha()):
                    continue
                all_counter[w[0]] += 1
                all_total += 1
                # Content-word filter: drop function words and very short words
                if w not in FUNCTION_WORDS and len(w) >= 3:
                    content_counter[w[0]] += 1
                    content_total += 1
        if all_total:
            top = all_counter.most_common(15)
            report["raw_word_onset_frequency_top15"] = [
                {"onset": k, "count": v, "pct": round(v / all_total * 100, 2)} for k, v in top
            ]
        if content_total:
            top_c = content_counter.most_common(15)
            report["content_word_onset_frequency_top15"] = [
                {"onset": k, "count": v, "pct": round(v / content_total * 100, 2)} for k, v in top_c
            ]
            report["content_word_total"] = content_total

    # --- sessions by month ---
    if ts_col:
        mo = Counter()
        for s in sessions:
            t = parse_ts(s.get(ts_col))
            if t:
                mo[t.strftime("%Y-%m")] += 1
        report["sessions_by_month"] = dict(sorted(mo.items()))

    return report, sessions, cols


def render_html(report, profile_name, db_path, ts):
    parts = [
        '<!DOCTYPE html><html><head><meta charset="UTF-8">',
        '<title>Lavrentiy — Cross-Session Pattern Report</title>',
        '<style>',
        'body{font-family:"Segoe UI",sans-serif;margin:30px;background:#f5f5f5;color:#222;max-width:1100px}',
        'h1{color:#1a1a1e;border-bottom:3px solid #ee5a24;padding-bottom:10px}',
        'h2{color:#333;margin-top:28px}',
        '.box{background:white;padding:15px 20px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);margin-bottom:18px}',
        'table{border-collapse:collapse;width:100%;font-size:13px}',
        'th{background:#1a1a1e;color:#d4d4d8;padding:6px 10px;text-align:left;font-weight:500}',
        'td{padding:6px 10px;border-bottom:1px solid #eee}',
        'tr:nth-child(even){background:#fafafa}',
        '.k{color:#666;font-size:12px}',
        '.v{font-family:monospace}',
        '.bar{background:linear-gradient(to right,#ee5a24,#b55050);height:14px;border-radius:2px}',
        '</style></head><body>',
        f'<h1>Lavrentiy &mdash; Cross-Session Pattern Report</h1>',
        '<div class="box">',
        f'<div><b>Profile:</b> {profile_name}</div>',
        f'<div><b>Database:</b> <code>{db_path}</code></div>',
        f'<div><b>Generated (UTC):</b> {ts}</div>',
        f'<div><b>Total sessions:</b> {report.get("total_sessions", "?")}</div>',
        '</div>',
    ]

    def simple_kv(title, d):
        if not d:
            return
        parts.append(f'<div class="box"><h2>{title}</h2><table>')
        for k, v in d.items():
            parts.append(f'<tr><td class="k">{k}</td><td class="v">{v}</td></tr>')
        parts.append('</table></div>')

    def table_list(title, rows, headers):
        if not rows:
            return
        parts.append(f'<div class="box"><h2>{title}</h2><table><tr>')
        for h in headers:
            parts.append(f'<th>{h}</th>')
        parts.append('</tr>')
        for row in rows:
            parts.append('<tr>' + ''.join(f'<td class="v">{c}</td>' for c in row) + '</tr>')
        parts.append('</table></div>')

    # Session span
    span_kv = {}
    for k in ("earliest_session", "latest_session", "span_days", "sessions_per_day_avg"):
        if k in report:
            span_kv[k] = report[k]
    simple_kv("Session span", span_kv)

    # Day of week
    if "sessions_by_day_of_week" in report:
        days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        dow = report["sessions_by_day_of_week"]
        max_v = max(dow.values()) if dow else 1
        rows = []
        for d in days_order:
            v = dow.get(d, 0)
            bar_width = int(v / max_v * 400) if max_v else 0
            rows.append([d, v, f'<div class="bar" style="width:{bar_width}px"></div>'])
        table_list("Sessions by day of week", rows, ["Day", "Count", ""])

    # Hour of day
    if "sessions_by_hour" in report:
        hr = report["sessions_by_hour"]
        max_v = max(hr.values()) if hr else 1
        rows = []
        for h in range(24):
            v = hr.get(str(h), hr.get(h, 0))
            bar_width = int(v / max_v * 400) if max_v else 0
            rows.append([f"{h:02d}:00", v, f'<div class="bar" style="width:{bar_width}px"></div>'])
        table_list("Sessions by hour of day", rows, ["Hour (local)", "Count", ""])

    # Monthly
    if "sessions_by_month" in report:
        mo = report["sessions_by_month"]
        max_v = max(mo.values()) if mo else 1
        rows = []
        for k, v in sorted(mo.items()):
            bar_width = int(v / max_v * 400) if max_v else 0
            rows.append([k, v, f'<div class="bar" style="width:{bar_width}px"></div>'])
        table_list("Sessions by month", rows, ["Month", "Count", ""])

    # Situation / tone / layer
    simple_kv("Situation breakdown", report.get("situation_breakdown"))
    simple_kv("Tone breakdown", report.get("tone_breakdown"))
    simple_kv("Layer breakdown", report.get("layer_breakdown"))

    # Numeric aggregates
    if report.get("numeric_aggregates"):
        rows = []
        for col, stats in report["numeric_aggregates"].items():
            rows.append([col, stats["n"], stats["mean"], stats["median"], stats["min"], stats["max"]])
        table_list("Numeric column aggregates", rows, ["Column", "n", "mean", "median", "min", "max"])

    # Clean/raw ratio
    if "clean_to_raw_word_ratio" in report:
        stats = report["clean_to_raw_word_ratio"]
        rows = [[stats["n"], stats["mean"], stats["median"], stats["min"], stats["max"]]]
        table_list("Clean-to-raw word ratio (proxy for how aggressively each session was cleaned)", rows, ["n", "mean", "median", "min", "max"])

    # Onset frequency — both views
    if report.get("raw_word_onset_frequency_top15"):
        rows = [[r["onset"], r["count"], f'{r["pct"]}%'] for r in report["raw_word_onset_frequency_top15"]]
        table_list("Raw-word onset frequency — all words (top 15)", rows, ["Onset letter", "Count", "Pct of total words"])

    if report.get("content_word_onset_frequency_top15"):
        rows = [[r["onset"], r["count"], f'{r["pct"]}%'] for r in report["content_word_onset_frequency_top15"]]
        table_list("Content-word onset frequency — function words filtered out (top 15)", rows, ["Onset letter", "Count", "Pct of content words"])

    parts.append('</body></html>')
    return "\n".join(parts)


def main():
    profile_name, db_path = discover_db()
    print(f"Using profile: {profile_name}")
    print(f"DB: {db_path}")

    report, sessions, cols = mine(db_path)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_json = HERE / f"mining_report_{profile_name}_{ts}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "generated_utc": ts,
            "profile": profile_name,
            "db_path": str(db_path),
            "report": report,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"JSON: {out_json.name}")

    out_html = HERE / f"mining_report_{profile_name}_{ts}.html"
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(render_html(report, profile_name, db_path, ts))
    print(f"HTML: {out_html.name}")


if __name__ == "__main__":
    main()
