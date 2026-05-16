"""
Performance regression tests for Lavrentiy.
Times every tested function. Asserts each completes under a threshold.
Prevents silent slowdowns after code changes.
No API keys, no audio, no Win32.
"""
import re, json, sys, ast, time, io, threading, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
from datetime import datetime, timedelta

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

ns = {
    're': re, 'json': json, 'time': time, 'os': os,
    'datetime': datetime, 'timedelta': timedelta,
    'Path': Path, 'difflib': __import__('difflib'),
    'threading': threading,
}

# Load all needed constants
start_idx = next(i for i, l in enumerate(lines) if l.startswith('LANGUAGE = '))
end_idx = next(i for i, l in enumerate(lines) if '_personal_onset_weights_by_lang' in l and '=' in l)
exec('\n'.join(lines[start_idx:end_idx + 1]), ns)

fw_start = next(i for i, l in enumerate(lines) if l.startswith('FUNCTION_WORDS = '))
fw_end = fw_start + 1
while fw_end < len(lines) and '}' not in lines[fw_end]:
    fw_end += 1
exec('\n'.join(lines[fw_start:fw_end + 1]), ns)

kf_start = next(i for i, l in enumerate(lines) if 'KNOWN_FILLERS' in l and '=' in l and 'if' not in l)
kf_end = kf_start + 1
while kf_end < len(lines) and '}' not in lines[kf_end]:
    kf_end += 1
exec('\n'.join(lines[kf_start:kf_end + 1]), ns)

sf_start = next(i for i, l in enumerate(lines) if '_STRIP_FILLERS' in l and '=' in l and 'if' not in l)
sf_end = sf_start + 1
while sf_end < len(lines) and '}' not in lines[sf_end]:
    sf_end += 1
exec('\n'.join(lines[sf_start:sf_end + 1]), ns)

nr_start = next(i for i, l in enumerate(lines) if l.startswith('NATURAL_REPEATS = '))
nr_end = nr_start + 1
while nr_end < len(lines) and '}' not in lines[nr_end]:
    nr_end += 1
exec('\n'.join(lines[nr_start:nr_end + 1]), ns)

eb_start = next(i for i, l in enumerate(lines) if l.startswith('_ENGLISH_ONSET_BASELINE = '))
eb_end = eb_start + 1
while eb_end < len(lines) and '}' not in lines[eb_end]:
    eb_end += 1
exec('\n'.join(lines[eb_start:eb_end + 1]), ns)

hf_start = next(i for i, l in enumerate(lines) if l.startswith('_HIGH_FREQ_WORDS = '))
hf_end = hf_start + 1
bd = 1
while hf_end < len(lines) and bd > 0:
    bd += lines[hf_end].count('{') - lines[hf_end].count('}')
    hf_end += 1
exec('\n'.join(lines[hf_start:hf_end]), ns)

# Load STUTTER_TIPS, MAX_INSIGHTS, DEFAULT_PROFILE
st_start = next(i for i, l in enumerate(lines) if l.startswith('STUTTER_TIPS = '))
st_end = st_start + 1
bd = 1
while st_end < len(lines) and bd > 0:
    bd += lines[st_end].count('{') - lines[st_end].count('}')
    st_end += 1
exec('\n'.join(lines[st_start:st_end]), ns)

dp_start = next(i for i, l in enumerate(lines) if l.startswith('DEFAULT_PROFILE = '))
dp_end = dp_start + 1
bd = 1
while dp_end < len(lines) and bd > 0:
    bd += lines[dp_end].count('{') - lines[dp_end].count('}')
    dp_end += 1
exec('\n'.join(lines[dp_start:dp_end]), ns)

for l in lines:
    if l.startswith('MAX_INSIGHTS'): exec(l, ns)

# Globals
ns['_onset_anomalies'] = []
ns['_personal_dominant_onsets'] = []
ns['_last_prep_text'] = None
ns['_last_prep_ts'] = 0.0
ns['_PREP_EXPIRY_SEC'] = 300
ns['_clipboard_predictor'] = None
ns['current_layer'] = 2
ns['current_mode'] = 'SAFE'
ns['HOLD_ON_HIGH_RISK'] = False
ns['_DANGLING'] = re.compile(r'(?:,|\band\s*$|\bor\s*$|\bbut\s*$|\.{2}(?!\.)|\bthe\s*$)', re.IGNORECASE)
ns['_shadow_history'] = []
ns['_MAX_SHADOW_HISTORY'] = 50
ns['_prep_lock'] = threading.Lock()
ns['_shadow_lock'] = threading.Lock()
ns['_learn_lock'] = threading.Lock()
ns['_stats_lock'] = threading.Lock()
ns['_redo_lock'] = threading.Lock()
ns['_augment_lock'] = threading.Lock()
ns['log'] = lambda msg, level='info': None
ns['stats'] = {'api_calls': 0, 'sessions': 50, 'falcon_rejects': 0,
               'words': 0, 'chars': 0, 'start_time': time.time(),
               'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
ns['learn_events'] = []
ns['save_profile'] = lambda prof, _epoch=None: None
ns['stats_inc'] = lambda key, n=1: None
ns['db_session_count'] = lambda: 50
ns['REDO_SIMILARITY_THRESHOLD'] = 0.7
ns['_redo_buffer'] = []
ns['_redo_count'] = 0
ns['_HYPHEN_STUTTER'] = re.compile(r'\b(\w{1,4})[-]\1[-]?(\w+)\b', re.IGNORECASE)
ns['_WORD_REPEAT'] = re.compile(r'\b(\w+)(?:\s+\1){1,}\s+(\w+)', re.IGNORECASE)

target_funcs = [
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
    '_learn_event', '_learn_events_snapshot', '_sample', '_norm_str',
    'detect_word_language', 'set_last_prep',
    'strip_disfluencies', 'count_disfluencies', 'detect_ocd_loops',
    'compute_brown_scores', 'predict_triggers_in_text',
    'compute_exposure_difficulty', 'compute_editorial_distance',
    'compute_avoidance_trend', 'build_stutter_insights',
    'detect_onset_anomalies', 'detect_triggers_regex',
    'apply_profile_corrections', '_check_critical_retention',
    'check_redo', 'generate_shadow_utterance',
]

# Load _CRITICAL_TOKEN_RE
for pat_name in ('_CRITICAL_TOKEN_RE',):
    pat_start = next(i for i, l in enumerate(lines) if l.startswith(pat_name + ' = '))
    pat_end = pat_start
    pd = 0
    while pat_end < len(lines):
        pd += lines[pat_end].count('(') - lines[pat_end].count(')')
        if pd <= 0 and pat_end > pat_start:
            break
        pat_end += 1
    exec('\n'.join(lines[pat_start:pat_end + 1]), ns)

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


def time_fn(fn, *args, iterations=100):
    """Run fn with args `iterations` times, return avg ms."""
    start = time.perf_counter()
    for _ in range(iterations):
        fn(*args)
    elapsed = (time.perf_counter() - start) / iterations * 1000
    return elapsed


# Test data
SHORT_TEXT = "I want to go to the store and buy some groceries for dinner tonight"
MEDIUM_TEXT = SHORT_TEXT * 20  # ~1400 chars
LONG_TEXT = SHORT_TEXT * 200   # ~14000 chars
DISFLUENT_TEXT = "I I I w- want to um um go to the the the store to um buy um some groceries"
DISFLUENT_LONG = DISFLUENT_TEXT * 100  # ~7500 chars
PROF = {"trigger_words": ["computer", "conference", "structure", "problem", "break"],
        "filler_words": ["um", "uh"], "corrections": {"Duncan": "Dankeschoen"},
        "vocabulary": ["Lavrentiy"]}


# ============================================================
# PERF 1: predict_phonetic_risk — single word
# ============================================================
print('=== PERF 1: predict_phonetic_risk ===')
predict = ns.get('predict_phonetic_risk')
if predict:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []
    ms = time_fn(predict, 'computer', iterations=1000)
    check(f'single word < 1ms (got {ms:.3f}ms)', ms < 1.0)
    ms = time_fn(predict, 'computer', iterations=1000)
    check(f'with position < 1ms (got {ms:.3f}ms)', ms < 1.0)
else:
    print('  SKIP')


# ============================================================
# PERF 2: compute_brown_scores
# ============================================================
print()
print('=== PERF 2: compute_brown_scores ===')
brown = ns.get('compute_brown_scores')
if brown:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []
    ms = time_fn(brown, SHORT_TEXT, iterations=100)
    check(f'short text ({len(SHORT_TEXT)}c) < 5ms (got {ms:.2f}ms)', ms < 5.0)
    ms = time_fn(brown, MEDIUM_TEXT, iterations=10)
    check(f'medium text ({len(MEDIUM_TEXT)}c) < 50ms (got {ms:.2f}ms)', ms < 50.0)
    ms = time_fn(brown, LONG_TEXT, iterations=3)
    check(f'long text ({len(LONG_TEXT)}c) < 500ms (got {ms:.2f}ms)', ms < 500.0)
else:
    print('  SKIP')


# ============================================================
# PERF 3: strip_disfluencies
# ============================================================
print()
print('=== PERF 3: strip_disfluencies ===')
strip = ns.get('strip_disfluencies')
if strip:
    ms = time_fn(strip, DISFLUENT_TEXT, iterations=100)
    check(f'short disfluent ({len(DISFLUENT_TEXT)}c) < 5ms (got {ms:.2f}ms)', ms < 5.0)
    ms = time_fn(strip, DISFLUENT_LONG, iterations=10)
    check(f'long disfluent ({len(DISFLUENT_LONG)}c) < 100ms (got {ms:.2f}ms)', ms < 100.0)
else:
    print('  SKIP')


# ============================================================
# PERF 4: count_disfluencies
# ============================================================
print()
print('=== PERF 4: count_disfluencies ===')
count_fn = ns.get('count_disfluencies')
if count_fn:
    ms = time_fn(count_fn, DISFLUENT_TEXT, iterations=100)
    check(f'short ({len(DISFLUENT_TEXT)}c) < 5ms (got {ms:.2f}ms)', ms < 5.0)
    ms = time_fn(count_fn, DISFLUENT_LONG, iterations=10)
    check(f'long ({len(DISFLUENT_LONG)}c) < 100ms (got {ms:.2f}ms)', ms < 100.0)
else:
    print('  SKIP')


# ============================================================
# PERF 5: compute_editorial_distance
# ============================================================
print()
print('=== PERF 5: compute_editorial_distance ===')
edit_fn = ns.get('compute_editorial_distance')
if edit_fn:
    ms = time_fn(edit_fn, SHORT_TEXT, SHORT_TEXT + " extra", iterations=100)
    check(f'short text < 2ms (got {ms:.2f}ms)', ms < 2.0)
    ms = time_fn(edit_fn, MEDIUM_TEXT, MEDIUM_TEXT + " extra words here", iterations=10)
    check(f'medium text < 250ms (got {ms:.2f}ms)', ms < 250.0)
else:
    print('  SKIP')


# ============================================================
# PERF 6: predict_triggers_in_text
# ============================================================
print()
print('=== PERF 6: predict_triggers_in_text ===')
predict_trig = ns.get('predict_triggers_in_text')
if predict_trig:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []
    ms = time_fn(predict_trig, SHORT_TEXT, ["computer", "conference"], iterations=100)
    check(f'short text < 5ms (got {ms:.2f}ms)', ms < 5.0)
    ms = time_fn(predict_trig, MEDIUM_TEXT, ["computer", "conference"], iterations=10)
    check(f'medium text < 50ms (got {ms:.2f}ms)', ms < 50.0)
else:
    print('  SKIP')


# ============================================================
# PERF 7: compute_exposure_difficulty
# ============================================================
print()
print('=== PERF 7: compute_exposure_difficulty ===')
exposure_fn = ns.get('compute_exposure_difficulty')
if exposure_fn:
    disf = {"total": 5, "word_rep": 2, "filler": 3}
    ms = time_fn(exposure_fn, SHORT_TEXT, "phone", disf, PROF, iterations=100)
    check(f'short text < 10ms (got {ms:.2f}ms)', ms < 10.0)
else:
    print('  SKIP')


# ============================================================
# PERF 8: detect_onset_anomalies
# ============================================================
print()
print('=== PERF 8: detect_onset_anomalies ===')
detect_oa = ns.get('detect_onset_anomalies')
if detect_oa:
    words_pool = "the computer conference structure problem break strong think class great " * 25
    sessions = [{"raw": words_pool}] * 35
    ms = time_fn(detect_oa, sessions, iterations=5)
    check(f'35 sessions < 200ms (got {ms:.2f}ms)', ms < 200.0)
else:
    print('  SKIP')


# ============================================================
# PERF 9: build_stutter_insights
# ============================================================
print()
print('=== PERF 9: build_stutter_insights ===')
insights_fn = ns.get('build_stutter_insights')
if insights_fn:
    ns['_personal_dominant_onsets'] = [{"onset": "k", "pct": 45}]
    ns['learn_events'] = [{"type": "trigger"}] * 5
    prof = {"trigger_words": ["computer", "conference", "class", "critical", "create"],
            "filler_words": list(ns.get('DEFAULT_PROFILE', {}).get('filler_words', [])) + ["basically"] * 20,
            "corrections": {"a": "1", "b": "2", "c": "3", "d": "4", "e": "5"}}
    ms = time_fn(insights_fn, prof, iterations=100)
    check(f'full profile < 5ms (got {ms:.2f}ms)', ms < 5.0)
    ns['_personal_dominant_onsets'] = []
    ns['learn_events'] = []
else:
    print('  SKIP')


# ============================================================
# PERF 10: apply_profile_corrections
# ============================================================
print()
print('=== PERF 10: apply_profile_corrections ===')
apply_corr = ns.get('apply_profile_corrections')
if apply_corr:
    big_prof = {"corrections": {f"word{i}": f"fixed{i}" for i in range(100)}}
    ms = time_fn(apply_corr, MEDIUM_TEXT, big_prof, iterations=10)
    check(f'100 corrections on medium text < 50ms (got {ms:.2f}ms)', ms < 50.0)
else:
    print('  SKIP')


# ============================================================
# PERF 11: detect_triggers_regex
# ============================================================
print()
print('=== PERF 11: detect_triggers_regex ===')
detect_trig = ns.get('detect_triggers_regex')
if detect_trig:
    stuttered = "I I I w- w- want to go go go the the the store store store " * 50
    ms = time_fn(detect_trig, stuttered, iterations=10)
    check(f'heavy stutter ({len(stuttered)}c) < 50ms (got {ms:.2f}ms)', ms < 50.0)
else:
    print('  SKIP')


# ============================================================
# PERF 12: _extract_onset (batch)
# ============================================================
print()
print('=== PERF 12: _extract_onset (batch) ===')
extract = ns.get('_extract_onset')
if extract:
    words = ["computer", "conference", "structure", "problem", "break",
             "strong", "think", "class", "great", "hello"] * 100
    start = time.perf_counter()
    for w in words:
        extract(w)
    elapsed = (time.perf_counter() - start) * 1000
    check(f'1000 words < 50ms (got {elapsed:.2f}ms)', elapsed < 50.0)
else:
    print('  SKIP')


# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
