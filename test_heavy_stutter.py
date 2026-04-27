"""
Heavy-stutter / hard-block reconstruction test harness.

Targets the silent-block / hard-block case (George's case) — distinct from
tests/stutter_pipeline/test_cases.json which covers audible disfluencies.

Two execution backends are supported. Pick one with --backend:

  --backend=module   Imports wim/api/reconstruct.py directly. Requires
                     OPENAI_API_KEY env var (or api_key.txt at repo root).
                     Mirrors tests/stutter_pipeline/run_test.py exactly.

  --backend=http     Hits a running Lavrentiy engine at http://127.0.0.1:7878
                     via POST /api/reconstruct_test. Engine must be alive and
                     authenticated. No OpenAI key needed in this process.

Per-case output: raw input -> reconstructed output -> WER vs intended ->
intent-preservation score (Jaccard on content lemmas, fast offline proxy) ->
proper-noun preservation rate -> coverage (no information dropped).

Saves results_<UTC>.json + report_<UTC>.html alongside the script.

NOT executed by this harness file at import. Run explicitly:

    python test_heavy_stutter.py --backend=module --layer=4 --tone=casual
    python test_heavy_stutter.py --backend=http --layer=4

Companion data: heavy_stutter_test_scripts.json (loaded if present, else
falls back to the inline embedded list at the bottom of this file).
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS_JSON = HERE / "heavy_stutter_test_scripts.json"

# ─── Defaults ───
DEFAULT_LAYERS = [1, 2, 3, 4]
DEFAULT_TONE = "casual"
DEFAULT_MODE = "SAFE"
DEFAULT_PORT = 7878
DEFAULT_PROFILE = {
    "filler_words": ["um", "uh", "uhm", "uhh", "ну", "нуу", "э", "ээ"],
    "trigger_words": ["call", "present", "doctor", "henderson", "marriott", "consent"],
    "onset_weights": {"p": 0.85, "k": 0.75, "t": 0.55, "d": 0.65, "s": 0.4, "g": 0.7, "h": 0.6, "ch": 0.7, "m": 0.45},
    "vocabulary": ["Henderson", "Marriott", "Tuesday", "Thursday", "Friday", "George"],
    "corrections": {},
    "covert_profile": {
        "avoidance_pairs": {
            "default": {
                "call": {
                    "avoided_count": 6,
                    "used_count": 1,
                    "common_substitutes": ["reach out to"],
                    "dominant_onset": "k",
                }
            }
        }
    },
}


# ─── Score helpers (intentionally simple, offline) ───

_PUNCT_RE = re.compile(r"[^\w\s'-]")


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def _tokens(text: str) -> list[str]:
    return _normalize(text).split()


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate against reference. Same Levenshtein as engine endpoint."""
    ref = _tokens(reference)
    hyp = _tokens(hypothesis)
    n, m = len(ref), len(hyp)
    if n == 0:
        return 0.0 if m == 0 else 1.0
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[j], prev = min(dp[j] + 1, dp[j - 1] + 1, prev + cost), dp[j]
    return round(dp[m] / n, 4)


_STOP = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "i", "you", "he", "she",
    "it", "we", "they", "me", "my", "your", "our", "their", "this", "that",
    "do", "does", "did", "have", "has", "had", "with", "about", "as", "by",
    "if", "so", "not", "no", "yes", "uh", "um", "uhh", "uhm",
}


def _content_lemmas(text: str) -> set[str]:
    return {t for t in _tokens(text) if t not in _STOP and len(t) > 1}


def intent_preservation(intended: str, output: str) -> float:
    """Jaccard over content-word sets. Cheap offline proxy for semantic
    similarity. 1.0 = all intended content words appear in output, no extras
    (interpret loosely — intent-preservation should be HIGH; precision-style
    extras are penalized lightly via union)."""
    a, b = _content_lemmas(intended), _content_lemmas(output)
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    inter = a & b
    return round(len(inter) / len(union), 4)


_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]{2,})\b")


def proper_nouns(text: str) -> list[str]:
    """Extract candidate proper nouns. Skips first-word-of-sentence false
    positives by also dropping single-token sentence starts (heuristic)."""
    if not text:
        return []
    out: list[str] = []
    for sent in re.split(r"[.!?]\s+", text):
        toks = sent.split()
        if not toks:
            continue
        for t in toks[1:]:
            for m in _PROPER_NOUN_RE.findall(t):
                out.append(m)
        # Take first token if it doesn't look like a sentence-start common word
        first = toks[0].strip(",;:")
        for m in _PROPER_NOUN_RE.findall(first):
            if m.lower() not in {"i", "we", "you", "they", "he", "she", "it",
                                 "the", "a", "an", "good", "hi", "please",
                                 "can", "want", "thank"}:
                out.append(m)
    return out


def proper_noun_preservation(intended: str, output: str) -> dict:
    """Returns {expected, preserved, rate, missing}. Rate is in [0,1]."""
    expected = [p for p in proper_nouns(intended) if p.lower() != "i"]
    if not expected:
        return {"expected": [], "preserved": [], "rate": 1.0, "missing": []}
    out_lower = _normalize(output)
    preserved = [p for p in expected if p.lower() in out_lower.split()]
    missing = [p for p in expected if p not in preserved]
    return {
        "expected": expected,
        "preserved": preserved,
        "rate": round(len(preserved) / len(expected), 4),
        "missing": missing,
    }


def coverage(intended: str, output: str) -> float:
    """Recall of content lemmas — what fraction of intended content survived."""
    a = _content_lemmas(intended)
    b = _content_lemmas(output)
    if not a:
        return 1.0
    return round(len(a & b) / len(a), 4)


# ─── Commodity baseline: vanilla GPT-4o, no Lav prompt-stack ───
# Answers the question: does Lavrentiy add measurable value over a
# $0.01 commodity GPT-4o call with a one-line system prompt?
# Lift per case = (commodity score) vs (Lav score). Positive lift
# only counts as Lav doing real work.

_COMMODITY_CLIENT = None
_COMMODITY_LOADED = False
_COMMODITY_LAYER_KEY = 0  # uses int 0 so it sorts before L1-L4 in summary


def _commodity_setup():
    """Load a vanilla OpenAI client. Tries env var, then api_key.txt files.
    Returns None if no key — commodity baseline silently skipped in that case."""
    global _COMMODITY_CLIENT, _COMMODITY_LOADED
    if _COMMODITY_LOADED:
        return _COMMODITY_CLIENT
    _COMMODITY_LOADED = True
    try:
        import openai
    except ImportError:
        return None
    # Prefer env var. Then walk known on-disk locations. The repo-root
    # api_key.txt is often stale/rotated; the working install at AppData
    # is what the running engine uses, so it's the most reliable
    # fallback. We try a small probe call against each candidate to
    # filter out known-bad keys before committing to one.
    candidates = []
    env_key = os.environ.get("OPENAI_API_KEY", "")
    if env_key:
        candidates.append(("env", env_key))
    for label, p in [
        ("repo-root", HERE / "api_key.txt"),
        ("wim-api", HERE / "wim" / "api" / "api_key.txt"),
        ("repo-engine", HERE / "engine" / "api_key.txt"),
        ("install", Path(os.path.expandvars(
            r"%LOCALAPPDATA%\Programs\Lavrentiy-Eval\engine\api_key.txt"
        ))),
    ]:
        if p.exists():
            try:
                k = p.read_text(encoding="utf-8").strip()
                if k:
                    candidates.append((label, k))
            except OSError:
                pass
    if not candidates:
        return None
    for label, k in candidates:
        try:
            client = openai.OpenAI(api_key=k)
            # Probe with a minimal models.list call (cheap, no completion)
            client.models.list()
            print(f"[commodity] using {label} api_key")
            _COMMODITY_CLIENT = client
            return _COMMODITY_CLIENT
        except Exception:
            continue
    return None


def _run_commodity(case):
    """One vanilla GPT-4o call, NO Lav prompt-engineering. Returns a row
    with layer=_COMMODITY_LAYER_KEY (0). Caller scores the same way as
    Lav rows so direct lift is visible in the report."""
    client = _commodity_setup()
    situation = case.get("situation", "default")
    base_row = {
        "case_id": case["id"], "type": case["type"],
        "layer": _COMMODITY_LAYER_KEY, "situation": situation,
        "scenario": case.get("scenario", ""),
        "intended": case["intended"], "raw_input": case["disfluent"],
        "falcon_ok": None, "confidence": None,
    }
    if client is None:
        return [{**base_row, "output": "", "elapsed_s": 0.0,
                 "error": "OpenAI client not configured"}]
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": (
                    "You receive raw, messy speech-to-text output. Return ONLY "
                    "the cleaned-up version, nothing else. No preamble, no "
                    "commentary, no markdown, no quotes around the output."
                )},
                {"role": "user", "content": case["disfluent"]},
            ],
            temperature=0.3,
        )
        out = (resp.choices[0].message.content or "").strip()
        return [{**base_row, "output": out,
                 "elapsed_s": round(time.time() - t0, 2), "error": ""}]
    except Exception as e:
        return [{**base_row, "output": "",
                 "elapsed_s": round(time.time() - t0, 2),
                 "error": str(e)[:400]}]


def _layer_label(L):
    """Display label: 0 → 'Commodity', N → 'LN'."""
    return "Commodity" if L == _COMMODITY_LAYER_KEY else f"L{L}"


# ─── Backend: in-process module ───

def _backend_module_setup():
    """Load reconstruct_intent from wim/api/reconstruct.py the same way the
    existing tests/stutter_pipeline/run_test.py does."""
    sys.path.insert(0, str(HERE / "wim" / "api"))
    from reconstruct import reconstruct_intent, client  # noqa: E402
    if not client:
        raise RuntimeError(
            "OpenAI client not configured. Set OPENAI_API_KEY or place api_key.txt "
            "at repo root or in wim/api/."
        )
    return reconstruct_intent


def _run_module(reconstruct_intent, case, layers, tone, mode, profile):
    rows = []
    situation = case.get("situation", "default")
    for L in layers:
        t0 = time.time()
        try:
            r = reconstruct_intent(
                raw_text=case["disfluent"], tone=tone, layer=L,
                profile=profile, situation=situation, mode=mode,
                language_code="en",
            )
            rows.append({
                "case_id": case["id"], "type": case["type"], "layer": L,
                "situation": situation, "scenario": case.get("scenario", ""),
                "intended": case["intended"], "raw_input": case["disfluent"],
                "output": r.get("clean", ""),
                "falcon_ok": r.get("falcon_ok"),
                "confidence": r.get("confidence"),
                "elapsed_s": round(time.time() - t0, 2),
                "error": r.get("error", ""),
            })
        except Exception as e:
            rows.append({
                "case_id": case["id"], "type": case["type"], "layer": L,
                "situation": situation, "scenario": case.get("scenario", ""),
                "intended": case["intended"], "raw_input": case["disfluent"],
                "output": "", "falcon_ok": None, "confidence": None,
                "elapsed_s": round(time.time() - t0, 2), "error": str(e)[:400],
            })
    return rows


# ─── Backend: HTTP /api/reconstruct_test ───

def _run_http(case, layers, tone, port):
    """Hits the running Lavrentiy engine. Note: /api/reconstruct_test is a
    single-layer call (uses current_layer from server state if `layer` arg
    omitted, else honors body['layer']). We send one POST per layer. The
    server endpoint already returns clean / filtered / wer / falcon_ok /
    recon_ms — we re-score WER ourselves against `intended` rather than `raw`.
    """
    rows = []
    situation = case.get("situation", "default")
    base = f"http://127.0.0.1:{port}/api/reconstruct_test"
    for L in layers:
        t0 = time.time()
        body = json.dumps({
            "raw": case["disfluent"], "tone": tone, "layer": L,
            "situation": situation,
        }).encode("utf-8")
        req = urllib.request.Request(
            base, data=body,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            rows.append({
                "case_id": case["id"], "type": case["type"], "layer": L,
                "situation": situation, "scenario": case.get("scenario", ""),
                "intended": case["intended"], "raw_input": case["disfluent"],
                "output": payload.get("clean", "") or "",
                "falcon_ok": payload.get("falcon_ok"),
                "confidence": None,
                "elapsed_s": round(time.time() - t0, 2),
                "error": payload.get("error", "") or "",
                "server_wer_vs_raw": payload.get("wer"),
                "server_recon_ms": payload.get("recon_ms"),
            })
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            rows.append({
                "case_id": case["id"], "type": case["type"], "layer": L,
                "situation": situation, "scenario": case.get("scenario", ""),
                "intended": case["intended"], "raw_input": case["disfluent"],
                "output": "", "falcon_ok": None, "confidence": None,
                "elapsed_s": round(time.time() - t0, 2),
                "error": f"HTTP error: {e}",
            })
    return rows


# ─── Scoring augmentation ───

def _score_row(row):
    intended = row["intended"]
    out = row["output"] or ""
    row["wer_vs_intended"] = wer(intended, out)
    row["intent_jaccard"] = intent_preservation(intended, out)
    row["coverage"] = coverage(intended, out)
    pn = proper_noun_preservation(intended, out)
    row["proper_noun_rate"] = pn["rate"]
    row["proper_nouns_expected"] = pn["expected"]
    row["proper_nouns_missing"] = pn["missing"]
    return row


# ─── Reporting ───

def render_html(cases, rows, ts, total_s, backend, tone, mode):
    by_case = {}
    for r in rows:
        by_case.setdefault(r["case_id"], []).append(r)
    ok = sum(1 for r in rows if r["falcon_ok"] is True)
    fail = sum(1 for r in rows if r["falcon_ok"] is False)
    esc = html_mod.escape

    css = (
        "body{font-family:'Segoe UI',sans-serif;margin:30px;background:#f5f5f5;color:#222;max-width:1200px}"
        "h1{color:#1a1a1e;border-bottom:3px solid #ee5a24;padding-bottom:10px}"
        "h3{color:#b55050;margin-bottom:6px}"
        ".box{background:white;padding:15px 20px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);margin-bottom:20px}"
        ".meta{font-size:12px;color:#666;margin-bottom:10px}"
        ".intended{background:#e6f3e6;padding:8px 12px;border-radius:4px;font-style:italic;margin:6px 0}"
        ".disfluent{background:#fbe6e6;padding:8px 12px;border-radius:4px;font-family:monospace;margin:6px 0}"
        "table{border-collapse:collapse;width:100%;font-size:12px;margin-top:8px}"
        "th{background:#1a1a1e;color:#d4d4d8;padding:6px 8px;text-align:left;font-weight:500}"
        "td{padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top}"
        "tr:nth-child(even){background:#f9f9f9}"
        ".ok{color:#2d7d2d}.fail{color:#b55050;font-weight:bold}"
        ".time{color:#666;font-family:monospace}"
        ".badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px}"
        ".badge-ok{background:#dff0d8;color:#2d7d2d}.badge-fail{background:#fbdede;color:#b55050}"
        ".num{font-family:monospace;text-align:right}"
        ".low{color:#b55050}.high{color:#2d7d2d}.mid{color:#a06d20}"
    )

    def cell_num(v, low_threshold, high_threshold, lower_is_better=False):
        if v is None:
            return '<td class="num">-</td>'
        cls = "mid"
        if lower_is_better:
            if v <= low_threshold:
                cls = "high"
            elif v >= high_threshold:
                cls = "low"
        else:
            if v >= high_threshold:
                cls = "high"
            elif v <= low_threshold:
                cls = "low"
        return f'<td class="num {cls}">{v:.2f}</td>'

    parts = [
        '<!DOCTYPE html><html><head><meta charset="UTF-8">',
        '<title>Heavy-Stutter Reconstruction Test Report</title>',
        '<style>' + css + '</style></head><body>',
        '<h1>Heavy-Stutter / Hard-Block Reconstruction Test Report</h1>',
        '<div class="box">',
        f'<div><b>Generated (UTC):</b> {ts}</div>',
        f'<div><b>Backend:</b> {backend} &middot; <b>Tone:</b> {tone} &middot; <b>Mode:</b> {mode}</div>',
        f'<div><b>Total elapsed:</b> {total_s}s</div>',
        f'<div><b>Runs:</b> {len(rows)} &middot; <b>Falcon OK:</b> <span class="badge badge-ok">{ok}</span>  <b>Falcon FAIL:</b> <span class="badge badge-fail">{fail}</span></div>',
        '</div>',
    ]

    for c in cases:
        case_rows = by_case.get(c["id"], [])
        parts.append('<div class="box">')
        parts.append(f'<h3>{esc(c["id"])} &mdash; {esc(c["type"])}</h3>')
        parts.append(
            f'<div class="meta">Situation: {esc(c.get("situation", "default"))} '
            f'&middot; Scenario: {esc(c.get("scenario", ""))} &middot; {esc(c.get("notes", ""))}</div>'
        )
        parts.append(f'<div><b>Intended:</b></div><div class="intended">{esc(c["intended"])}</div>')
        parts.append(f'<div><b>Disfluent input:</b></div><div class="disfluent">{esc(c["disfluent"])}</div>')
        parts.append(
            '<table><tr>'
            '<th>Layer</th><th>Output</th><th>Falcon</th>'
            '<th>WER&darr;</th><th>Intent J&uarr;</th><th>Cov&uarr;</th><th>PN&uarr;</th>'
            '<th>Elapsed</th></tr>'
        )
        for r in case_rows:
            if r["falcon_ok"] is True:
                fal = '<span class="ok">OK</span>'
            elif r["falcon_ok"] is False:
                fal = '<span class="fail">FAIL</span>'
            else:
                fal = '-'
            row_html = (
                f'<tr><td>{_layer_label(r["layer"])}</td>'
                f'<td>{esc(r["output"] or "")}</td>'
                f'<td>{fal}</td>'
                + cell_num(r.get("wer_vs_intended"), 0.20, 0.50, lower_is_better=True)
                + cell_num(r.get("intent_jaccard"), 0.50, 0.80)
                + cell_num(r.get("coverage"), 0.70, 0.90)
                + cell_num(r.get("proper_noun_rate"), 0.50, 0.90)
                + f'<td class="time">{r["elapsed_s"]}s</td></tr>'
            )
            parts.append(row_html)
        parts.append('</table></div>')

    # Summary table
    by_layer = {}
    for r in rows:
        by_layer.setdefault(r["layer"], []).append(r)
    parts.append('<div class="box"><h3>Per-layer summary</h3>')
    parts.append(
        '<table><tr>'
        '<th>Layer</th><th>N</th><th>WER (median)</th><th>Intent J (median)</th>'
        '<th>Coverage (median)</th><th>PN preservation (mean)</th><th>Falcon OK</th></tr>'
    )

    def median(xs):
        xs = sorted(x for x in xs if x is not None)
        if not xs:
            return None
        m = len(xs) // 2
        return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    for L in sorted(by_layer):
        rs = by_layer[L]
        wmed = median([r.get("wer_vs_intended") for r in rs])
        imed = median([r.get("intent_jaccard") for r in rs])
        cmed = median([r.get("coverage") for r in rs])
        pn = mean([r.get("proper_noun_rate") for r in rs])
        fok = sum(1 for r in rs if r["falcon_ok"] is True)
        parts.append(
            f'<tr><td>{_layer_label(L)}</td><td>{len(rs)}</td>'
            + cell_num(wmed, 0.20, 0.50, lower_is_better=True)
            + cell_num(imed, 0.50, 0.80)
            + cell_num(cmed, 0.70, 0.90)
            + cell_num(pn, 0.50, 0.90)
            + f'<td>{fok}/{len(rs)}</td></tr>'
        )
    parts.append('</table></div>')
    parts.append('</body></html>')
    return "\n".join(parts)


# ─── Inline fallback corpus (in case the JSON file is missing) ───
# Authoritative source is heavy_stutter_test_scripts.json. Keep this list in
# sync if you edit cases there. Truncated to 4 representative cases here for
# quick smoke runs; full 18 lives in the JSON.

INLINE_FALLBACK_CASES = [
    {
        "id": "h01_silent_block_hard_onset_p",
        "type": "hard silent block on /p/ onset",
        "intended": "I want to present the proposal on Tuesday",
        "disfluent": "i want to [BLOCK] [BLOCK] present the proposal on tuesday",
        "notes": "Two silent freezes before the hard /p/ content word.",
        "situation": "default", "scenario": "professional",
    },
    {
        "id": "h02_silent_block_phantom_word",
        "type": "Whisper hallucinated word during silent block",
        "intended": "Can you call the doctor",
        "disfluent": "can you so so so call the doctor",
        "notes": "Silence triggers hallucination of 'so'.",
        "situation": "default", "scenario": "casual",
    },
    {
        "id": "h05_covert_revision_i_mean",
        "type": "self-correction via 'I mean'",
        "intended": "I disagree with the recommendation",
        "disfluent": "i agree with i mean i i disagree with the recommendation",
        "notes": "Opposite-meaning placeholder then correction.",
        "situation": "high_stress", "scenario": "professional",
    },
    {
        "id": "h10_proper_noun_block",
        "type": "block on proper noun",
        "intended": "I met with Henderson at the Marriott yesterday",
        "disfluent": "i met with [BLOCK] [BLOCK] henderson at the the m m marriott yesterday",
        "notes": "Tests proper-noun preservation under block.",
        "situation": "default", "scenario": "professional",
    },
]


def load_cases():
    if SCRIPTS_JSON.exists():
        with open(SCRIPTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["cases"]
    return INLINE_FALLBACK_CASES


# ─── Main ───

def main():
    parser = argparse.ArgumentParser(description="Heavy-stutter reconstruction harness")
    parser.add_argument("--backend", choices=["module", "http"], default="module")
    parser.add_argument("--layer", type=int, default=None,
                        help="Single layer to run. Omit to run all of L1-L4.")
    parser.add_argument("--tone", default=DEFAULT_TONE)
    parser.add_argument("--mode", default=DEFAULT_MODE)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="HTTP backend only.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only first N cases (for fast iteration).")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]
    layers = [args.layer] if args.layer else DEFAULT_LAYERS

    if args.backend == "module":
        try:
            reconstruct_intent = _backend_module_setup()
        except Exception as e:
            print(f"ERROR: module backend setup failed: {e}")
            sys.exit(1)

        def run_one(c):
            return _run_module(reconstruct_intent, c, layers, args.tone,
                               args.mode, DEFAULT_PROFILE)
    else:
        def run_one(c):
            return _run_http(c, layers, args.tone, args.port)

    print(f"Running {len(cases)} cases x {len(layers)} layers = "
          f"{len(cases) * len(layers)} reconstructions [backend={args.backend}]")

    all_rows = []
    t_start = time.time()
    for i, c in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {c['id']}")
        rows = run_one(c)
        # Always run commodity baseline alongside Lav. Same scoring,
        # different prompt-stack. Lift is visible per-case in the report.
        rows.extend(_run_commodity(c))
        for r in rows:
            _score_row(r)
        all_rows.extend(rows)
        for r in rows:
            f_mark = ("OK" if r["falcon_ok"] is True else
                      "FAIL" if r["falcon_ok"] is False else "-")
            print(f"  {_layer_label(r['layer'])}  {r['elapsed_s']}s  "
                  f"WER={r.get('wer_vs_intended', '-'):.2f}  "
                  f"IntentJ={r.get('intent_jaccard', '-'):.2f}  "
                  f"Cov={r.get('coverage', '-'):.2f}  "
                  f"PN={r.get('proper_noun_rate', '-'):.2f}  [{f_mark}]")

    total = round(time.time() - t_start, 1)
    print(f"\n=== {len(all_rows)} runs in {total}s ===")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    json_out = HERE / f"results_heavy_stutter_{ts}.json"
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump({
            "generated_utc": ts, "total_elapsed_s": total,
            "backend": args.backend, "tone": args.tone, "mode": args.mode,
            "layers": layers, "results": all_rows,
        }, f, indent=2, ensure_ascii=False)
    print(f"JSON: {json_out.name}")

    html_out = HERE / f"report_heavy_stutter_{ts}.html"
    with open(html_out, "w", encoding="utf-8") as f:
        f.write(render_html(cases, all_rows, ts, total, args.backend,
                            args.tone, args.mode))
    print(f"HTML: {html_out.name}")


if __name__ == "__main__":
    main()
