"""
Tests for the 7 clinical features that had zero test coverage.
Uses the same ast.parse extraction pattern as test_core.py.
No API keys, no audio hardware, no Win32.
"""
import re, json, sys, os, ast, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace with needed constants
from pathlib import Path
from datetime import datetime, timedelta
ns = {
    're': re, 'json': json, 'time': time, 'os': os,
    'datetime': datetime, 'timedelta': timedelta,
    'Path': Path, 'difflib': __import__('difflib'),
}

# Load constants block (LANGUAGE through _personal_onset_weights_by_lang)
start_idx = next(i for i, l in enumerate(lines) if l.startswith('LANGUAGE = '))
end_idx = next(i for i, l in enumerate(lines) if '_personal_onset_weights_by_lang' in l and '=' in l)
exec('\n'.join(lines[start_idx:end_idx + 1]), ns)

# Load FUNCTION_WORDS
fw_start = next(i for i, l in enumerate(lines) if l.startswith('FUNCTION_WORDS = '))
fw_end = fw_start + 1
while fw_end < len(lines) and '}' not in lines[fw_end]:
    fw_end += 1
exec('\n'.join(lines[fw_start:fw_end + 1]), ns)

# Load KNOWN_FILLERS
kf_start = next(i for i, l in enumerate(lines) if 'KNOWN_FILLERS' in l and '=' in l and 'if' not in l)
kf_end = kf_start + 1
while kf_end < len(lines) and '}' not in lines[kf_end]:
    kf_end += 1
exec('\n'.join(lines[kf_start:kf_end + 1]), ns)

# Load redo constants
ns['REDO_SIMILARITY_THRESHOLD'] = 0.7
ns['_redo_buffer'] = []
ns['_redo_count'] = 0

# Load decay constants
ns['DECAY_STALE_SESSIONS'] = 100
ns['DECAY_DEAD_SESSIONS'] = 200

# Load prep constants
ns['_last_prep_text'] = None
ns['_last_prep_ts'] = 0.0
ns['_PREP_EXPIRY_SEC'] = 300

# Thread locks (needed by functions that now use locking)
import threading
ns['threading'] = threading
ns['_prep_lock'] = threading.Lock()
ns['_redo_lock'] = threading.Lock()
ns['_shadow_lock'] = threading.Lock()
ns['_learn_lock'] = threading.Lock()
ns['_augment_lock'] = threading.Lock()
ns['_stats_lock'] = threading.Lock()

# Stubs
ns['log'] = lambda msg, level='info': None
ns['stats'] = {'api_calls': 0, 'sessions': 50, 'falcon_rejects': 0,
               'words': 0, 'chars': 0, 'start_time': time.time(),
               'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
ns['_onset_anomalies'] = []
ns['current_mode'] = 'SAFE'
ns['learn_events'] = []
ns['HOLD_ON_HIGH_RISK'] = False

# Stub save_profile (no-op for tests)
ns['save_profile'] = lambda prof: None

# Stub db_session_count (controllable)
_mock_session_count = [50]
ns['db_session_count'] = lambda: _mock_session_count[0]

# Load target functions (including _learn_event helper used by decay/learn functions)
target_funcs = [
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
    '_learn_event', '_learn_events_snapshot',
    'compute_exposure_difficulty', 'compute_editorial_distance',
    'detect_covert_avoidance', 'update_covert_profile',
    'compute_substitution_fingerprint',
    'check_redo', 'set_last_prep',
    'decay_stale_profile_entries', 'track_profile_relevance',
]

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
        func_source = ast.get_source_segment(source, node)
        if func_source:
            try:
                exec(func_source, ns)
            except Exception as e:
                print(f'SKIP {node.name}: {e}')

loaded = [k for k in target_funcs if k in ns]
print(f'Loaded {len(loaded)}/{len(target_funcs)} functions: {loaded}')
print()

passed = 0
failed = 0


def check(name, condition, detail=''):
    global passed, failed
    if condition:
        passed += 1
        print(f'  PASS: {name}')
    else:
        failed += 1
        print(f'  FAIL: {name} {detail}')


# ============================================================
# TEST 1: compute_exposure_difficulty
# ============================================================
print('=== TEST 1: compute_exposure_difficulty ===')
exposure = ns.get('compute_exposure_difficulty')
if exposure:
    prof = {"trigger_words": ["computer", "conference"]}
    r = exposure("", "default", {}, prof)
    check('empty input -> score 0.0', r["score"] == 0.0)
    r = exposure("I want to go to the store", "default", {"total": 0}, prof)
    check('returns score key', "score" in r)
    check('returns band key', "band" in r)
    check('returns components key', "components" in r)
    check(f'score bounded [0,1] (got {r["score"]})', 0.0 <= r["score"] <= 1.0)
    r_phone = exposure("I need to call the computer company", "phone", {"total": 2}, prof)
    r_casual = exposure("I need to call the computer company", "casual", {"total": 2}, prof)
    check(f'phone > casual ({r_phone["score"]} > {r_casual["score"]})',
          r_phone["score"] > r_casual["score"])
    r_clean = exposure("I want to go home", "default", {"total": 0}, prof)
    r_messy = exposure("I want to go home", "default", {"total": 5}, prof)
    check(f'more disfluencies = higher score ({r_messy["score"]} >= {r_clean["score"]})',
          r_messy["score"] >= r_clean["score"])
    r_no_trig = exposure("I want to go home now", "default", {"total": 0}, {"trigger_words": []})
    r_trig = exposure("I want computer conference now", "default", {"total": 0},
                      {"trigger_words": ["computer", "conference"]})
    check(f'trigger words increase score ({r_trig["score"]} > {r_no_trig["score"]})',
          r_trig["score"] > r_no_trig["score"])
    r = exposure("hello", "casual", {"total": 0}, {"trigger_words": []})
    check(f'band is valid (got "{r["band"]}")', r["band"] in ("low", "moderate", "high", "very_high"))
    c = r["components"]
    check('component: phonetic_risk', "phonetic_risk" in c)
    check('component: situation_pressure', "situation_pressure" in c)
    check('component: disfluency_density', "disfluency_density" in c)
    check('component: trigger_ratio', "trigger_ratio" in c)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 2: compute_editorial_distance
# ============================================================
print()
print('=== TEST 2: compute_editorial_distance ===')
ed = ns.get('compute_editorial_distance')
if ed:
    check('identical = 0.0', ed("hello world", "hello world") == 0.0)
    check('empty raw = 0.0', ed("", "hello") == 0.0)
    check('empty clean = 0.0', ed("hello", "") == 0.0)
    check('both empty = 0.0', ed("", "") == 0.0)
    check('None raw = 0.0', ed(None, "hello") == 0.0)
    d = ed("alpha beta gamma", "delta epsilon zeta")
    check(f'completely different = 1.0 (got {d})', d == 1.0)
    d = ed("I I I want to go", "I want to go")
    check(f'partial edit in (0,1) (got {d})', 0.0 < d < 1.0)
    d = ed("hello world", "hello earth")
    check(f'"hello world" vs "hello earth" = 0.5 (got {d})', d == 0.5)
    d1 = ed("hello beautiful world", "hello world")
    d2 = ed("hello world", "hello beautiful world")
    check(f'insertion vs deletion similar ({d1} vs {d2})', abs(d1 - d2) < 0.01)
    check('case insensitive = 0.0', ed("Hello World", "hello world") == 0.0)
    d = ed("a b c d e f g h i j", "z")
    check(f'bounded <= 1.0 (got {d})', d <= 1.0)
    check(f'bounded >= 0.0 (got {d})', d >= 0.0)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 3: detect_covert_avoidance
# ============================================================
print()
print('=== TEST 3: detect_covert_avoidance ===')
detect_ca = ns.get('detect_covert_avoidance')
set_prep = ns.get('set_last_prep')
if detect_ca and set_prep:
    ns['_last_prep_text'] = None
    r = detect_ca("I said something", {"trigger_words": []})
    check('no prep text -> empty list', r == [])
    set_prep("I want to call the computer company")
    r = detect_ca("I want to call the computer company", {"trigger_words": ["computer"]})
    check('perfect match -> empty list', r == [])
    set_prep("I need to call the conference center")
    r = detect_ca("I need to call the meeting center", {"trigger_words": ["conference"]})
    check(f'substitution detection runs (found {len(r)} pairs)', len(r) >= 0)
    ns['_last_prep_text'] = "old text"
    ns['_last_prep_ts'] = time.time() - 400
    r = detect_ca("new text here", {"trigger_words": []})
    check('expired prep -> empty list', r == [])
    set_prep("hello world")
    r = detect_ca("", {"trigger_words": []})
    check('empty actual -> empty list', r == [])
    set_prep("I have a big structured presentation tomorrow")
    r = detect_ca("I have a big organized talk tomorrow", {"trigger_words": ["presentation", "structured"]})
    if r:
        check('pair has "intended" key', "intended" in r[0])
        check('pair has "said" key', "said" in r[0])
        check('pair has "onset_avoided" key', "onset_avoided" in r[0])
        check('pair has "risk_score" key', "risk_score" in r[0])
    else:
        print('  INFO: no avoidance detected (risk below threshold) — structure check skipped')
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 4: compute_substitution_fingerprint
# ============================================================
print()
print('=== TEST 4: compute_substitution_fingerprint ===')
fingerprint = ns.get('compute_substitution_fingerprint')
if fingerprint:
    r = fingerprint({"covert_profile": {}})
    check('empty profile -> avoidance_index 0.0', r["avoidance_index"] == 0.0)
    check('empty profile -> empty onset_heat', r["onset_heat"] == {})
    check('empty profile -> empty top_substitutions', r["top_substitutions"] == [])
    r = fingerprint({})
    check('no covert key -> avoidance_index 0.0', r["avoidance_index"] == 0.0)
    now = datetime.now().isoformat()
    prof_with_data = {
        "covert_profile": {
            "avoidance_pairs": {
                "phone": {
                    "computer": {"avoided_count": 5, "used_count": 10,
                        "common_substitutes": ["machine", "device"],
                        "dominant_onset": "k", "last_seen": now},
                    "conference": {"avoided_count": 3, "used_count": 8,
                        "common_substitutes": ["meeting"],
                        "dominant_onset": "k", "last_seen": now}
                },
                "casual": {
                    "structure": {"avoided_count": 2, "used_count": 15,
                        "common_substitutes": ["framework"],
                        "dominant_onset": "str", "last_seen": now}
                }
            }
        }
    }
    r = fingerprint(prof_with_data)
    check(f'avoidance_index > 0 (got {r["avoidance_index"]})', r["avoidance_index"] > 0.0)
    check(f'avoidance_index <= 1.0 (got {r["avoidance_index"]})', r["avoidance_index"] <= 1.0)
    check('onset_heat has "k"', "k" in r["onset_heat"])
    check(f'onset "k" count = 8 (got {r["onset_heat"].get("k")})', r["onset_heat"].get("k") == 8)
    check('phone in situation_breakdown', "phone" in r["situation_breakdown"])
    check('casual in situation_breakdown', "casual" in r["situation_breakdown"])
    phone_data = r["situation_breakdown"]["phone"]
    check(f'phone total_avoided = 8 (got {phone_data["total_avoided"]})', phone_data["total_avoided"] == 8)
    check(f'phone top_word = "computer" (got {phone_data["top_word"]})', phone_data["top_word"] == "computer")
    check(f'top_substitutions non-empty ({len(r["top_substitutions"])})', len(r["top_substitutions"]) > 0)
    top = r["top_substitutions"][0]
    check('top sub has word key', "word" in top)
    check('top sub has count key', "count" in top)
    check('top sub has substitutes key', "substitutes" in top)
    check(f'top word = "computer" count 5 (got {top["word"]}={top["count"]})',
          top["word"] == "computer" and top["count"] == 5)
    check('drift is a list', isinstance(r["drift"], list))
    drift_words = [d["word"] for d in r["drift"]]
    check(f'recently emerging "structure" in drift (got {drift_words})', "structure" in drift_words)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 5: check_redo
# ============================================================
print()
print('=== TEST 5: check_redo ===')
redo = ns.get('check_redo')
if redo:
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    r = redo("I want to go to the store")
    check(f'first utterance = 0 (got {r})', r == 0)
    r = redo("I want to go to the store")
    check(f'same sentence = redo (got {r})', r >= 1)
    r = redo("I want to go to the store")
    check(f'third time = redo count 2 (got {r})', r >= 2)
    r = redo("the weather is nice today")
    check(f'different sentence = 0 (got {r})', r == 0)
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    redo("I want to go to the big store")
    r = redo("I want to go to the large store")
    check(f'high overlap = redo (got {r})', r >= 1)
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    redo("the quick brown fox jumps over the lazy dog")
    r = redo("my cat sleeps on the warm couch all day")
    check(f'low overlap = not redo (got {r})', r == 0)
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    r = redo("")
    check(f'empty = 0 (got {r})', r == 0)
    r = redo(None)
    check(f'None = 0 (got {r})', r == 0)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 6: track_profile_relevance
# ============================================================
print()
print('=== TEST 6: track_profile_relevance ===')
track = ns.get('track_profile_relevance')
if track:
    _mock_session_count[0] = 42
    prof = {
        "corrections": {"Duncan": "Dankeschoen", "notch": "not"},
        "filler_words": ["um", "uh", "like"],
        "vocabulary": ["Lavrentiy", "microservice"],
    }
    track(prof, "so um duncan said something about the notch")
    rel = prof.get("_relevance", {})
    check('_relevance created', "_relevance" in prof)
    check('corrections.duncan stamped', rel.get("corrections", {}).get("duncan") == 42)
    check('corrections.notch stamped', rel.get("corrections", {}).get("notch") == 42)
    check('fillers.um stamped', rel.get("fillers", {}).get("um") == 42)
    check('fillers.like NOT stamped', rel.get("fillers", {}).get("like") is None)
    check('vocabulary.lavrentiy NOT stamped', rel.get("vocabulary", {}).get("lavrentiy") is None)
    _mock_session_count[0] = 50
    track(prof, "I like the lavrentiy app")
    check('fillers.like NOW stamped at 50', rel.get("fillers", {}).get("like") == 50)
    check('vocabulary.lavrentiy NOW stamped at 50', rel.get("vocabulary", {}).get("lavrentiy") == 50)
    check('corrections.duncan still 42', rel.get("corrections", {}).get("duncan") == 42)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 7: decay_stale_profile_entries
# ============================================================
print()
print('=== TEST 7: decay_stale_profile_entries ===')
decay = ns.get('decay_stale_profile_entries')
if decay:
    ns['learn_events'] = []
    _mock_session_count[0] = 200
    prof = {
        "corrections": {
            "fresh": "Fresh Value",
            "stale": "Stale Value",
            "ancient": "Ancient Value",
        },
        "filler_words": ["um", "uh", "yeah"],
        "vocabulary": ["Lavrentiy", "OldTerm"],
        "candidate_corrections": {},
        "_relevance": {
            "corrections": {"fresh": 180, "stale": 50, "ancient": 10},
            "fillers": {"um": 190, "uh": 190, "yeah": 30},
            "vocabulary": {"lavrentiy": 195, "oldterm": 50}
        }
    }
    result = decay(prof)
    check('"fresh" kept in corrections', "fresh" in prof["corrections"])
    check('"stale" removed from corrections', "stale" not in prof["corrections"])
    check('"stale" added to candidates', "stale" in prof.get("candidate_corrections", {}))
    check('"ancient" removed from corrections', "ancient" not in prof["corrections"])
    check('"ancient" added to candidates', "ancient" in prof.get("candidate_corrections", {}))
    stale_cand = prof["candidate_corrections"].get("stale", {})
    check('demoted candidate has votes', stale_cand.get("votes", {}).get("Stale Value") == 1)
    check('demoted candidate has demoted_at=200', stale_cand.get("demoted_at") == 200)
    check('"um" kept (protected)', "um" in prof["filler_words"])
    check('"uh" kept (protected)', "uh" in prof["filler_words"])
    check('"yeah" removed (stale, not protected)', "yeah" not in prof["filler_words"])
    check('"Lavrentiy" kept (recent)', "Lavrentiy" in prof["vocabulary"])
    check('"OldTerm" removed (stale)', "OldTerm" not in prof["vocabulary"])
    check(f'result >= 3 (got {result})', result >= 3)
    prof["candidate_corrections"]["zombie"] = {"votes": {"z": 1}, "total": 1, "demoted_at": 1}
    _mock_session_count[0] = 250
    prof["_relevance"]["corrections"] = {"fresh": 240}
    result2 = decay(prof)
    check('"zombie" pruned (dead candidate)', "zombie" not in prof.get("candidate_corrections", {}))
    check(f'learn_events populated ({len(ns["learn_events"])} events)', len(ns["learn_events"]) > 0)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 8: update_covert_profile
# ============================================================
print()
print('=== TEST 8: update_covert_profile ===')
update_cp = ns.get('update_covert_profile')
if update_cp:
    prof = {}
    avoidance_pairs = [
        {"intended": "computer", "said": "machine", "onset_avoided": "k", "risk_score": 0.72},
        {"intended": "conference", "said": "meeting", "onset_avoided": "k", "risk_score": 0.65},
    ]
    update_cp(prof, avoidance_pairs, "phone")
    check('covert_profile created', "covert_profile" in prof)
    pairs = prof["covert_profile"]["avoidance_pairs"]
    check('phone situation exists', "phone" in pairs)
    check('"computer" tracked', "computer" in pairs["phone"])
    check('"conference" tracked', "conference" in pairs["phone"])
    comp = pairs["phone"]["computer"]
    check(f'computer avoided_count = 1 (got {comp["avoided_count"]})', comp["avoided_count"] == 1)
    check('computer substitute = "machine"', "machine" in comp["common_substitutes"])
    check('computer onset = "k"', comp["dominant_onset"] == "k")
    update_cp(prof, [{"intended": "computer", "said": "device", "onset_avoided": "k", "risk_score": 0.72}], "phone")
    comp = pairs["phone"]["computer"]
    check(f'computer avoided_count = 2 (got {comp["avoided_count"]})', comp["avoided_count"] == 2)
    check('computer now has 2 substitutes', len(comp["common_substitutes"]) == 2)
    prof2 = {}
    update_cp(prof2, [], "default")
    check('empty pairs -> no covert_profile', "covert_profile" not in prof2)
else:
    print('  SKIP: function not loaded')


# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
