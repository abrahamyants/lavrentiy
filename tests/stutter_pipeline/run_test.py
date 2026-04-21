"""
Disfluent-speech reconstruction pipeline test runner.
Runs test_cases.json through wim/api/reconstruct.py at L1-L4,
saves JSON + HTML report.

Usage from this directory:
    export OPENAI_API_KEY=$(cat ../../api_key.txt)
    PYTHONIOENCODING=utf-8 python3 run_test.py
"""
import json
import sys
import time
import html as html_mod
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "wim" / "api"))

from reconstruct import reconstruct_intent, client  # noqa: E402

LAYERS = [1, 2, 3, 4]
TONE = "casual"
MODE = "SAFE"

PROFILE = {
    "filler_words": ["um", "uh", "э", "ээ", "ну"],
    "trigger_words": ["doctor", "call", "disagree", "hometown", "problem"],
    "onset_weights": {"p": 0.75, "k": 0.65, "t": 0.5, "d": 0.55, "s": 0.4},
    "vocabulary": ["Thursday", "contract", "Henderson"],
    "corrections": {},
    "covert_profile": {
        "avoidance_pairs": {
            "default": {
                "hometown": {
                    "avoided_count": 5,
                    "used_count": 1,
                    "common_substitutes": ["the place where I grew up"],
                    "dominant_onset": "h",
                }
            }
        }
    },
}


def run_case(case):
    rows = []
    situation = case.get("situation", "default")
    for L in LAYERS:
        t0 = time.time()
        try:
            r = reconstruct_intent(
                raw_text=case["disfluent"], tone=TONE, layer=L,
                profile=PROFILE, situation=situation, mode=MODE,
                language_code="en",
            )
            rows.append({
                "case_id": case["id"], "type": case["type"], "layer": L,
                "situation": situation, "intended": case["intended"],
                "raw_input": case["disfluent"], "output": r.get("clean", ""),
                "falcon_ok": r.get("falcon_ok"),
                "confidence": r.get("confidence"),
                "elapsed_s": round(time.time() - t0, 2),
                "error": r.get("error", ""),
            })
        except Exception as e:
            rows.append({
                "case_id": case["id"], "type": case["type"], "layer": L,
                "situation": situation, "intended": case["intended"],
                "raw_input": case["disfluent"], "output": "",
                "falcon_ok": None, "confidence": None,
                "elapsed_s": round(time.time() - t0, 2),
                "error": str(e)[:400],
            })
    return rows


def render_html(cases, rows, ts, total):
    by_case = {}
    for r in rows:
        by_case.setdefault(r["case_id"], []).append(r)
    ok = sum(1 for r in rows if r["falcon_ok"] is True)
    fail = sum(1 for r in rows if r["falcon_ok"] is False)
    esc = html_mod.escape

    css = (
        "body{font-family:'Segoe UI',sans-serif;margin:30px;background:#f5f5f5;color:#222;max-width:1150px}"
        "h1{color:#1a1a1e;border-bottom:3px solid #ee5a24;padding-bottom:10px}"
        "h3{color:#b55050;margin-bottom:6px}"
        ".box{background:white;padding:15px 20px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);margin-bottom:20px}"
        ".meta{font-size:12px;color:#666;margin-bottom:10px}"
        ".intended{background:#e6f3e6;padding:8px 12px;border-radius:4px;font-style:italic;margin:6px 0}"
        ".disfluent{background:#fbe6e6;padding:8px 12px;border-radius:4px;font-family:monospace;margin:6px 0}"
        "table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}"
        "th{background:#1a1a1e;color:#d4d4d8;padding:8px 10px;text-align:left;font-weight:500}"
        "td{padding:8px 10px;border-bottom:1px solid #eee;vertical-align:top}"
        "tr:nth-child(even){background:#f9f9f9}"
        ".ok{color:#2d7d2d}.fail{color:#b55050;font-weight:bold}"
        ".time{color:#666;font-family:monospace}"
        ".badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px}"
        ".badge-ok{background:#dff0d8;color:#2d7d2d}.badge-fail{background:#fbdede;color:#b55050}"
    )

    parts = [
        '<!DOCTYPE html><html><head><meta charset="UTF-8">',
        '<title>Disfluent-Speech Reconstruction Test Report</title>',
        '<style>' + css + '</style></head><body>',
        '<h1>Disfluent-Speech Reconstruction Test Report</h1>',
        '<div class="box">',
        '<div><b>Generated (UTC):</b> ' + ts + '</div>',
        '<div><b>Total elapsed:</b> ' + str(total) + 's</div>',
        '<div><b>Runs:</b> ' + str(len(rows)) + ' &middot; <b>Falcon OK:</b> <span class="badge badge-ok">' + str(ok) + '</span>  <b>Falcon FAIL:</b> <span class="badge badge-fail">' + str(fail) + '</span></div>',
        '<div><b>Pipeline:</b> <code>wim/api/reconstruct.py</code> &middot; <b>Tone:</b> ' + TONE + ' &middot; <b>Mode:</b> ' + MODE + ' &middot; <b>Language:</b> en</div>',
        '</div>',
    ]

    for c in cases:
        case_rows = by_case.get(c["id"], [])
        parts.append('<div class="box">')
        parts.append('<h3>' + esc(c["id"]) + ' &mdash; ' + esc(c["type"]) + '</h3>')
        parts.append('<div class="meta">Situation: ' + esc(c.get("situation", "default")) + ' &middot; ' + esc(c.get("notes", "")) + '</div>')
        parts.append('<div><b>Intended:</b></div><div class="intended">' + esc(c["intended"]) + '</div>')
        parts.append('<div><b>Disfluent input:</b></div><div class="disfluent">' + esc(c["disfluent"]) + '</div>')
        parts.append('<table><tr><th>Layer</th><th>Output</th><th>Falcon</th><th>Confidence</th><th>Elapsed</th></tr>')
        for r in case_rows:
            if r["falcon_ok"] is True:
                fal = '<span class="ok">OK</span>'
            elif r["falcon_ok"] is False:
                fal = '<span class="fail">FAIL</span>'
            else:
                fal = '-'
            conf = ("%.2f" % r["confidence"]) if isinstance(r["confidence"], (int, float)) else '-'
            parts.append('<tr><td>L' + str(r["layer"]) + '</td><td>' + esc(r["output"] or "") + '</td><td>' + fal + '</td><td>' + conf + '</td><td class="time">' + str(r["elapsed_s"]) + 's</td></tr>')
        parts.append('</table></div>')

    parts.append('</body></html>')
    return "\n".join(parts)


def main():
    with open(HERE / "test_cases.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    cases = data["cases"]

    print("Running %d cases x %d layers = %d API sequences" % (len(cases), len(LAYERS), len(cases) * len(LAYERS)))
    if not client:
        print("ERROR: OpenAI client not configured. Set OPENAI_API_KEY or populate api_key.txt")
        sys.exit(1)

    all_rows = []
    t_start = time.time()
    for i, c in enumerate(cases, 1):
        print("[%d/%d] %s" % (i, len(cases), c["id"]))
        rows = run_case(c)
        all_rows.extend(rows)
        for r in rows:
            f_mark = "OK" if r["falcon_ok"] is True else ("FAIL" if r["falcon_ok"] is False else "-")
            print("  L%d  %ss  [%s]" % (r["layer"], r["elapsed_s"], f_mark))

    total = round(time.time() - t_start, 1)
    print("\n=== %d runs in %ss ===" % (len(all_rows), total))

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    json_out = HERE / ("results_%s.json" % ts)
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump({
            "generated_utc": ts, "total_elapsed_s": total,
            "profile_sketch": {k: v for k, v in PROFILE.items() if k != "covert_profile"},
            "results": all_rows,
        }, f, indent=2, ensure_ascii=False)
    print("JSON:", json_out.name)

    html_out = HERE / ("report_%s.html" % ts)
    with open(html_out, "w", encoding="utf-8") as f:
        f.write(render_html(cases, all_rows, ts, total))
    print("HTML:", html_out.name)


if __name__ == "__main__":
    main()
