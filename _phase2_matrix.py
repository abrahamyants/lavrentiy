"""
Phase 2 diagnostic: feed Input A (fluent) and Input B (heavy disfluency
with paralinguistic tags) through L1-L4 of the live engine via
/api/reconstruct_test. Engine must be running on 127.0.0.1:7878.

Mode (RAW/FAST/SAFE) is documented from make_decision() in lavrentiy.py;
/api/reconstruct_test hardcodes SAFE behavior, so we don't vary it here.
"""
import json, time, urllib.request

ENGINE = "http://127.0.0.1:7878"

INPUT_A = (
    "I would like to schedule a meeting for next Thursday to discuss the "
    "enterprise software deployment."
)
INPUT_B = (
    "I I I w-w-want to to [Pause] s-schedule a m-m-m-meeting for for "
    "n-next Thursday to d-d-discuss the the [Laughter] ent-enterprise "
    "s-s-software."
)

def post(path, data):
    req = urllib.request.Request(
        f"{ENGINE}{path}",
        json.dumps(data).encode(),
        {"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

rows = []
for label, raw in [("A_fluent", INPUT_A), ("B_disfluent", INPUT_B)]:
    for layer in (1, 2, 3, 4):
        t0 = time.time()
        try:
            r = post("/api/reconstruct_test", {
                "raw": raw, "tone": "casual", "layer": layer,
                "situation": "default",
            })
            r["_elapsed_s"] = round(time.time() - t0, 2)
        except Exception as e:
            r = {"error": str(e), "_elapsed_s": round(time.time() - t0, 2)}
        r["_label"] = label
        r["_layer"] = layer
        rows.append(r)
        status = r.get("error") or (
            f"falcon={r.get('falcon_ok')} wer={r.get('wer')} "
            f"ms={r.get('recon_ms')}"
        )
        print(f"{label} L{layer}: {status}")
        clean = r.get("clean", "")
        print(f"    clean: {clean!r}")
        if layer == 1:
            print(f"    filtered (L1 output): {r.get('filtered','')!r}")

with open("_phase2_matrix_out.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, indent=2, ensure_ascii=False)
print("\nSaved: _phase2_matrix_out.json")
