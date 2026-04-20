"""Phase 3: L4 × tones matrix against real utterances from George's own history.db.

Pulls the top N hardest sessions (high editorial_distance, layer >= 2, non-trivial length)
and reruns each through the LIVE engine's /api/reconstruct_test endpoint across all
four tones at Layer 4. Outputs a grid showing how the reconstruction changes with tone.

NOTE: running engine is the Apr 13 snapshot (PRE-fix), so this shows BASELINE behavior —
not the v1.2.1 Eval-build behavior. Run this same script against the Eval install to
compare post-fix behavior.
"""
import json, sqlite3, time, urllib.request

DB = r"C:\Users\georg\.lavrentiy\profiles\gugosf\history.db"
ENGINE = "http://127.0.0.1:7878"
N = 10
TONES = ["casual", "professional", "formal", "friend"]


def post(path, data):
    req = urllib.request.Request(
        f"{ENGINE}{path}",
        json.dumps(data).encode(),
        {"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("""
    SELECT id, ts, raw, out, tone, layer, words, falcon, situation, editorial_distance
    FROM sessions
    WHERE layer >= 2
      AND words BETWEEN 5 AND 50
      AND raw IS NOT NULL
      AND length(raw) BETWEEN 25 AND 400
      AND editorial_distance BETWEEN 0.3 AND 0.8
      AND lower(raw) NOT LIKE '%transcribed by%'
      AND lower(raw) NOT LIKE '%otter.ai%'
      AND lower(raw) NOT LIKE '%like and subscribe%'
      AND lower(raw) NOT LIKE '%thank you for watching%'
      AND lower(raw) NOT LIKE '%translation by%'
      AND lower(raw) NOT LIKE '%captions by%'
      AND lower(raw) NOT LIKE '%transcribe intended words%'
      AND lower(raw) NOT LIKE '%thanks for watching%'
      AND lower(raw) NOT LIKE '%subscribe to%'
      AND raw GLOB '*[A-Za-z]*'
    ORDER BY editorial_distance DESC
    LIMIT ?
""", (N,))
rows = cur.fetchall()
conn.close()
print(f"Selected {len(rows)} hardest sessions (by editorial_distance):")
print()

results = []
for i, (sid, ts, raw, out, orig_tone, orig_layer, words, orig_falcon, situ, ed) in enumerate(rows, 1):
    print(f"[{i}/{len(rows)}] SID={sid}  words={words}  ed={ed:.3f}  orig(L{orig_layer}/{orig_tone})")
    print(f"  RAW  : {raw[:140]}")
    print(f"  HIST : {out[:140]}")
    row = {
        "sid": sid, "ts": ts, "raw": raw, "historical_out": out,
        "original": {"tone": orig_tone, "layer": orig_layer, "falcon": orig_falcon},
        "situation": situ or "default", "editorial_distance": ed, "words": words,
        "L4_by_tone": {}
    }
    for tone in TONES:
        t0 = time.time()
        try:
            r = post("/api/reconstruct_test", {
                "raw": raw, "tone": tone, "layer": 4,
                "situation": situ or "default",
            })
            ms = int((time.time() - t0) * 1000)
        except Exception as e:
            r = {"error": str(e)}; ms = 0
        row["L4_by_tone"][tone] = {
            "clean": r.get("clean", r.get("error", "")),
            "filtered": r.get("filtered", ""),
            "falcon_ok": r.get("falcon_ok"),
            "wer": r.get("wer"),
            "recon_ms": r.get("recon_ms", ms),
        }
        c = row["L4_by_tone"][tone]["clean"]
        fo = row["L4_by_tone"][tone]["falcon_ok"]
        print(f"  L4 {tone:<12}: falcon={fo} ms={row['L4_by_tone'][tone]['recon_ms']}")
        print(f"     -> {c[:140]}")
    results.append(row)
    print()

out_json = r"C:\Users\georg\Documents\GitHub\lavrentiy\_phase3_l4_tones_out.json"
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"Saved: {out_json}")

print()
print("=" * 90)
print("TONE DIVERGENCE SUMMARY (does tone affect the reconstruction?)")
print("=" * 90)
for row in results:
    tones_out = {t: row["L4_by_tone"][t]["clean"] for t in TONES}
    unique = set(tones_out.values())
    print(f"SID={row['sid']}: {len(unique)} unique reconstruction(s) across {len(TONES)} tones")
    if len(unique) > 1:
        for t in TONES:
            print(f"    {t:<12}: {tones_out[t][:100]}")
