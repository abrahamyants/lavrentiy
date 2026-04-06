"""
Full pipeline test — all layers, tones, situations, regular + stuttered speech.
Generates test audio via OpenAI TTS, feeds through engine's /api/transcribe.
Records: input text, raw Whisper output, final output, timing.

Run: python test_full_pipeline.py
Requires: running engine on localhost:7878, OpenAI API key
"""

import os
import sys
import json
import time
import base64
import tempfile
import urllib.request

ENGINE = "http://127.0.0.1:7878"
API_KEY = ""

# Try to find API key
for path in [
    os.path.join(os.path.dirname(__file__), "api_key.txt"),
    os.path.expanduser("~/.lavrentiy/profiles/Default/api_key.txt"),
    r"C:\Users\georg\Documents\GitHub\lavrentiy\api_key.txt",
    r"C:\Users\georg\AppData\Local\Programs\Lavrentiy\engine\api_key.txt",
]:
    if os.path.exists(path):
        API_KEY = open(path).read().strip()
        break

if not API_KEY:
    print("ERROR: No API key found. Cannot generate test audio.")
    sys.exit(1)

# ── Test sentences ──────────────────────────────────────────────

SENTENCES = {
    "meeting": {
        "clean": "I need to schedule a meeting with the development team for next Thursday at two o'clock to discuss the quarterly roadmap and budget allocation.",
        "stuttered": "I I I need to sch- schedule a a meeting with the the development team for for next Thursday at at two o'clock to to discuss the the quarterly roadmap and and budget allocation.",
    },
    "financial": {
        "clean": "The quarterly financial report shows a fifteen percent increase in revenue compared to last year, which exceeded our initial projections by a significant margin.",
        "stuttered": "The the quarterly f- f- financial report shows a a fifteen p- percent increase in in revenue compared to to last year which which exceeded our our initial projections by by a significant margin.",
    },
    "contract": {
        "clean": "Can you please send me the contract for the Henderson project by end of day Friday, and make sure to include the revised pricing terms we discussed yesterday.",
        "stuttered": "Can you p- p- please send me the the contract for the H- Henderson project by by end of day Friday and and make sure to to include the the revised pricing terms we we discussed yesterday.",
    },
    "personal": {
        "clean": "My name is George and I've been working on voice recognition software for people who stutter, because existing tools like Dragon and Whisper don't handle disfluent speech well.",
        "stuttered": "My my name is is G- George and I've I've been working on on voice recognition software for for people who who stutter because because existing tools like like Dragon and and Whisper don't don't handle disfluent speech well.",
    },
}

# ── Test matrix ─────────────────────────────────────────────────

COMBOS = [
    {"layer": 1, "tone": "casual",       "situation": "default",     "label": "L1 casual default"},
    {"layer": 2, "tone": "casual",       "situation": "default",     "label": "L2 casual default"},
    {"layer": 2, "tone": "professional", "situation": "default",     "label": "L2 professional default"},
    {"layer": 2, "tone": "formal",       "situation": "default",     "label": "L2 formal default"},
    {"layer": 2, "tone": "friend",       "situation": "default",     "label": "L2 friend default"},
    {"layer": 2, "tone": "casual",       "situation": "high_stress", "label": "L2 casual high_stress"},
    {"layer": 2, "tone": "casual",       "situation": "reading",     "label": "L2 casual reading"},
    {"layer": 4, "tone": "casual",       "situation": "default",     "label": "L4 casual default"},
    {"layer": 4, "tone": "professional", "situation": "high_stress", "label": "L4 pro high_stress"},
]

# ── Helpers ─────────────────────────────────────────────────────

def post_json(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{ENGINE}{path}", body,
                                 {"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def set_engine(layer, tone, situation):
    post_json("/api/layer", {"layer": layer})
    post_json("/api/tone", {"tone": tone})
    post_json("/api/situation", {"situation": situation})
    # ALWAYS kill DAF after situation change — high_stress preset auto-starts it
    post_json("/api/daf", {"enabled": False})


def generate_tts(text, voice="nova", speed=1.0):
    """Generate WAV audio via OpenAI TTS API. Returns temp file path."""
    import openai
    client = openai.OpenAI(api_key=API_KEY)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
        response_format="wav",
        speed=speed,
    )
    response.stream_to_file(tmp.name)
    return tmp.name


def transcribe_via_engine(wav_path):
    """Send WAV to engine's /api/transcribe endpoint."""
    with open(wav_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()
    t0 = time.time()
    result = post_json("/api/transcribe", {"audio_b64": audio_b64})
    elapsed = time.time() - t0
    result["_elapsed_s"] = round(elapsed, 2)
    return result


# ── Main test run ───────────────────────────────────────────────

def main():
    print("=" * 80)
    print("  LAVRENTIY FULL PIPELINE TEST")
    print("=" * 80)
    print(f"  Engine: {ENGINE}")
    print(f"  Sentences: {len(SENTENCES)} × 2 (clean + stuttered) = {len(SENTENCES)*2} audio files")
    print(f"  Combos: {len(COMBOS)}")
    print(f"  Total tests: {len(SENTENCES) * 2 * len(COMBOS)}")
    print()

    # Step 1: Generate test audio
    print("[1/3] Generating test audio via OpenAI TTS...")
    audio_files = {}
    voices = ["nova", "alloy", "echo", "onyx"]  # variety
    for i, (name, texts) in enumerate(SENTENCES.items()):
        voice = voices[i % len(voices)]
        for variant in ["clean", "stuttered"]:
            key = f"{name}_{variant}"
            print(f"  Generating: {key} (voice={voice})...", end=" ", flush=True)
            try:
                path = generate_tts(texts[variant], voice=voice,
                                     speed=0.95 if variant == "stuttered" else 1.0)
                size_kb = os.path.getsize(path) // 1024
                audio_files[key] = {
                    "path": path,
                    "input_text": texts[variant],
                    "variant": variant,
                    "sentence": name,
                    "voice": voice,
                }
                print(f"{size_kb} KB")
            except Exception as e:
                print(f"FAILED: {e}")
                audio_files[key] = None

    generated = sum(1 for v in audio_files.values() if v is not None)
    print(f"  Generated {generated}/{len(SENTENCES)*2} audio files\n")

    # Step 2: Run tests
    print("[2/3] Running pipeline tests...")
    results = []
    test_num = 0
    total_tests = generated * len(COMBOS)

    for combo in COMBOS:
        set_engine(combo["layer"], combo["tone"], combo["situation"])
        time.sleep(0.3)  # let engine settle

        for key, audio in audio_files.items():
            if audio is None:
                continue
            test_num += 1
            label = f"[{test_num}/{total_tests}] {combo['label']} | {key}"
            print(f"  {label}...", end=" ", flush=True)

            result = transcribe_via_engine(audio["path"])

            row = {
                "test": test_num,
                "combo": combo["label"],
                "layer": combo["layer"],
                "tone": combo["tone"],
                "situation": combo["situation"],
                "sentence": audio["sentence"],
                "variant": audio["variant"],
                "input_text": audio["input_text"],
                "raw": result.get("raw", result.get("whisper_raw", "")),
                "output": result.get("clean", result.get("text", "")),
                "elapsed_s": result.get("_elapsed_s", 0),
                "confidence": result.get("gamma", result.get("confidence", "")),
                "falcon": result.get("falcon_ok", ""),
                "error": result.get("error", ""),
            }
            results.append(row)

            elapsed = row["elapsed_s"]
            out_preview = (row["output"] or "")[:60]
            status = "OK" if not row["error"] else f"ERR: {row['error'][:40]}"
            print(f"{elapsed}s | {status} | \"{out_preview}\"")

    # Step 3: Report
    print(f"\n[3/3] Results summary\n")
    print("=" * 120)
    print(f"{'#':>3} {'Combo':<25} {'Variant':<10} {'Sentence':<12} {'Time':>5} {'Status':<6} {'Output (first 70 chars)'}")
    print("-" * 120)
    for r in results:
        status = "OK" if not r["error"] else "ERR"
        out = (r["output"] or "")[:70]
        print(f"{r['test']:>3} {r['combo']:<25} {r['variant']:<10} {r['sentence']:<12} {r['elapsed_s']:>5.1f}s {status:<6} {out}")

    print("\n" + "=" * 120)

    # Timing summary by layer
    print("\nTiming by layer:")
    for layer in [1, 2, 4]:
        layer_results = [r for r in results if r["layer"] == layer and not r["error"]]
        if layer_results:
            times = [r["elapsed_s"] for r in layer_results]
            print(f"  L{layer}: avg={sum(times)/len(times):.1f}s  min={min(times):.1f}s  max={max(times):.1f}s  (n={len(times)})")

    # Timing by combo
    print("\nTiming by combo:")
    for combo in COMBOS:
        combo_results = [r for r in results if r["combo"] == combo["label"] and not r["error"]]
        if combo_results:
            times = [r["elapsed_s"] for r in combo_results]
            print(f"  {combo['label']:<30} avg={sum(times)/len(times):.1f}s  range={min(times):.1f}-{max(times):.1f}s")

    # Stuttered vs clean comparison
    print("\nStuttered vs clean output comparison:")
    for name in SENTENCES:
        for combo in COMBOS:
            clean_r = [r for r in results if r["sentence"] == name and r["variant"] == "clean"
                       and r["combo"] == combo["label"] and not r["error"]]
            stut_r = [r for r in results if r["sentence"] == name and r["variant"] == "stuttered"
                      and r["combo"] == combo["label"] and not r["error"]]
            if clean_r and stut_r and combo["layer"] >= 2:
                c = clean_r[0]
                s = stut_r[0]
                match = "MATCH" if c["output"].strip().lower() == s["output"].strip().lower() else "DIFFER"
                print(f"  {combo['label']:<25} {name:<12} clean->\"{c['output'][:50]}\"")
                print(f"  {'':25} {'':12} stut ->\"{s['output'][:50]}\"  [{match}]")

    # Save full results as JSON
    out_path = os.path.join(os.path.dirname(__file__), "test_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved to: {out_path}")

    # Generate HTML report
    html_path = os.path.join(os.path.dirname(__file__), "test_report.html")
    _generate_html_report(results, SENTENCES, COMBOS, html_path)
    print(f"HTML report saved to: {html_path}")

    # Cleanup audio files
    for key, audio in audio_files.items():
        if audio and os.path.exists(audio["path"]):
            os.unlink(audio["path"])

    print("\nDone.")


def _generate_html_report(results, sentences, combos, html_path):
    """Generate a comprehensive HTML report from test results."""
    from datetime import datetime

    html = []
    html.append("""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Lavrentiy Pipeline Test Report</title>
<style>
body { font-family: 'Segoe UI', sans-serif; margin: 40px; background: #f5f5f5; color: #222; }
h1 { color: #1a1a1e; border-bottom: 3px solid #ee5a24; padding-bottom: 10px; }
h2 { color: #333; margin-top: 40px; border-bottom: 1px solid #ccc; padding-bottom: 5px; }
h3 { color: #555; }
table { border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 13px; }
th { background: #1a1a1e; color: #d4d4d8; padding: 8px 10px; text-align: left; }
td { padding: 6px 10px; border-bottom: 1px solid #ddd; vertical-align: top; }
tr:nth-child(even) { background: #f9f9f9; }
.clean { color: #2d7d2d; }
.stuttered { color: #b55050; }
.time { font-family: monospace; color: #666; }
.match { color: #2d7d2d; font-weight: bold; }
.differ { color: #b55050; font-weight: bold; }
.section { background: white; padding: 20px 25px; margin: 20px 0; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.input-text { background: #f0f0f0; padding: 10px; border-radius: 4px; margin: 5px 0; font-size: 13px; line-height: 1.5; }
.label { font-weight: bold; font-size: 11px; text-transform: uppercase; color: #888; letter-spacing: 1px; }
</style></head><body>""")

    html.append(f"<h1>Lavrentiy Pipeline Test Report</h1>")
    html.append(f"<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>")
    html.append(f"<p>Tests: {len(results)} | Sentences: {len(sentences)} x 2 | Combos: {len(combos)}</p>")

    # Section 1: Test Sentences
    html.append('<div class="section"><h2>Test Sentences (Input Audio)</h2>')
    html.append("<p>Each sentence was generated via OpenAI TTS in both clean and stuttered versions (10-20 seconds each).</p>")
    for name, texts in sentences.items():
        html.append(f'<h3>{name.title()}</h3>')
        html.append(f'<div class="label">Clean version:</div>')
        html.append(f'<div class="input-text clean">{texts["clean"]}</div>')
        html.append(f'<div class="label">Stuttered version:</div>')
        html.append(f'<div class="input-text stuttered">{texts["stuttered"]}</div>')
    html.append('</div>')

    # Section 2: Timing Summary
    html.append('<div class="section"><h2>Timing Summary</h2>')
    html.append('<table><tr><th>Combo</th><th>Avg</th><th>Min</th><th>Max</th><th>Tests</th></tr>')
    for combo in combos:
        cr = [r for r in results if r["combo"] == combo["label"] and not r.get("error")]
        if cr:
            times = [r["elapsed_s"] for r in cr]
            html.append(f'<tr><td>{combo["label"]}</td>'
                        f'<td class="time">{sum(times)/len(times):.1f}s</td>'
                        f'<td class="time">{min(times):.1f}s</td>'
                        f'<td class="time">{max(times):.1f}s</td>'
                        f'<td>{len(times)}</td></tr>')
    html.append('</table></div>')

    # Section 3: Full Results by Combo
    html.append('<div class="section"><h2>Full Results</h2>')
    for combo in combos:
        cr = [r for r in results if r["combo"] == combo["label"]]
        if not cr:
            continue
        html.append(f'<h3>{combo["label"]}</h3>')
        html.append('<table><tr><th>#</th><th>Variant</th><th>Sentence</th>'
                     '<th>Output</th><th>Time</th></tr>')
        for r in cr:
            variant_class = "clean" if r["variant"] == "clean" else "stuttered"
            output = r.get("output", r.get("error", ""))
            html.append(f'<tr><td>{r["test"]}</td>'
                        f'<td class="{variant_class}">{r["variant"]}</td>'
                        f'<td>{r["sentence"]}</td>'
                        f'<td>{output}</td>'
                        f'<td class="time">{r["elapsed_s"]}s</td></tr>')
        html.append('</table>')
    html.append('</div>')

    # Section 4: Clean vs Stuttered Comparison
    html.append('<div class="section"><h2>Clean vs Stuttered Output Comparison</h2>')
    html.append('<p>Do clean and stuttered versions of the same sentence produce similar output after reconstruction?</p>')
    html.append('<table><tr><th>Combo</th><th>Sentence</th><th>Clean Output</th>'
                 '<th>Stuttered Output</th><th>Match?</th></tr>')
    for combo in combos:
        if combo["layer"] < 2:
            continue
        for name in sentences:
            clean_r = [r for r in results if r["sentence"] == name and r["variant"] == "clean"
                       and r["combo"] == combo["label"] and not r.get("error")]
            stut_r = [r for r in results if r["sentence"] == name and r["variant"] == "stuttered"
                      and r["combo"] == combo["label"] and not r.get("error")]
            if clean_r and stut_r:
                c_out = clean_r[0].get("output", "")
                s_out = stut_r[0].get("output", "")
                match = c_out.strip().lower() == s_out.strip().lower()
                match_cls = "match" if match else "differ"
                match_txt = "MATCH" if match else "DIFFER"
                html.append(f'<tr><td>{combo["label"]}</td><td>{name}</td>'
                            f'<td class="clean">{c_out}</td>'
                            f'<td class="stuttered">{s_out}</td>'
                            f'<td class="{match_cls}">{match_txt}</td></tr>')
    html.append('</table></div>')

    html.append("</body></html>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html))


if __name__ == "__main__":
    main()
