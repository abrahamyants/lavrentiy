"""Diff Current baseline vs Eval v1.2.1 matrix outputs.
Shows for each (SID, tone) whether the reconstruction changed + classifies the delta.
"""
import json, difflib

with open(r"C:\Users\georg\Documents\GitHub\lavrentiy\_phase3_CURRENT_baseline.json", encoding="utf-8") as f:
    cur = {r["sid"]: r for r in json.load(f)}
with open(r"C:\Users\georg\Documents\GitHub\lavrentiy\_phase3_EVAL_v121.json", encoding="utf-8") as f:
    evl = {r["sid"]: r for r in json.load(f)}

TONES = ["casual", "professional", "formal", "friend"]

print("=" * 100)
print(f"{'SID':<6} {'tone':<13} {'delta':<8} {'falcon':<20} {'len ratio (eval/cur)'}")
print("=" * 100)

changes = {"same": 0, "minor_edit": 0, "major_edit": 0, "falcon_delta": 0, "length_delta": 0}

for sid in cur:
    if sid not in evl:
        continue
    c = cur[sid]
    e = evl[sid]
    for tone in TONES:
        cc = c["L4_by_tone"][tone]["clean"] or ""
        ec = e["L4_by_tone"][tone]["clean"] or ""
        cfalcon = c["L4_by_tone"][tone]["falcon_ok"]
        efalcon = e["L4_by_tone"][tone]["falcon_ok"]

        if cc == ec:
            delta_tag = "same"
            changes["same"] += 1
        else:
            # similarity ratio
            sim = difflib.SequenceMatcher(None, cc.lower(), ec.lower()).ratio()
            if sim >= 0.85:
                delta_tag = "minor"
                changes["minor_edit"] += 1
            else:
                delta_tag = "MAJOR"
                changes["major_edit"] += 1

        falcon_tag = f"cur={cfalcon} eval={efalcon}"
        if cfalcon != efalcon:
            changes["falcon_delta"] += 1
            falcon_tag = "*** FALCON FLIP *** " + falcon_tag

        cur_len = len(cc)
        eval_len = len(ec)
        ratio = eval_len / cur_len if cur_len else float('inf')
        if abs(ratio - 1.0) > 0.3:
            changes["length_delta"] += 1

        print(f"{sid:<6} {tone:<13} {delta_tag:<8} {falcon_tag:<35} {ratio:.2f}")

print("=" * 100)
print(f"Totals: same={changes['same']}, minor={changes['minor_edit']}, MAJOR={changes['major_edit']}, falcon_flips={changes['falcon_delta']}, big length delta={changes['length_delta']}")
print()
print("=" * 100)
print("MAJOR CHANGES — what's different between Current and Eval on the same input:")
print("=" * 100)
for sid in cur:
    if sid not in evl:
        continue
    c = cur[sid]
    e = evl[sid]
    for tone in TONES:
        cc = c["L4_by_tone"][tone]["clean"] or ""
        ec = e["L4_by_tone"][tone]["clean"] or ""
        if cc == ec:
            continue
        sim = difflib.SequenceMatcher(None, cc.lower(), ec.lower()).ratio()
        if sim >= 0.85:
            continue  # minor only
        print()
        print(f"SID={sid}  tone={tone}  similarity={sim:.2f}")
        print(f"  RAW   : {c['raw'][:140]}")
        print(f"  CUR   : {cc[:140]}")
        print(f"  EVAL  : {ec[:140]}")
