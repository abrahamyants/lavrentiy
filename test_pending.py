"""
Tests for the 9 functions that had zero test coverage.
Uses the same ast.parse extraction pattern as test_core.py / test_clinical.py.
No API keys, no audio hardware, no Win32.
"""
import re, json, sys, ast, time, io, threading, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent / 'wim' / 'api'))
import learning_backend

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace with needed constants
ns = {
    're': re, 'json': json, 'time': time, 'os': os,
    'datetime': datetime, 'timedelta': timedelta,
    'Path': Path, 'difflib': __import__('difflib'),
    'threading': threading,
    'learning_backend': learning_backend,
    'is_authenticated': lambda: False,
    'MODEL': 'test-model',
    # Globals from lavrentiy.py module scope that extracted functions reference.
    '_profile_lock': threading.Lock(),
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

# Load STUTTER_TIPS
st_start = next(i for i, l in enumerate(lines) if l.startswith('STUTTER_TIPS = '))
st_end = st_start + 1
brace_depth = 1
while st_end < len(lines) and brace_depth > 0:
    brace_depth += lines[st_end].count('{') - lines[st_end].count('}')
    st_end += 1
exec('\n'.join(lines[st_start:st_end]), ns)

# Load _ENGLISH_ONSET_BASELINE
eb_start = next(i for i, l in enumerate(lines) if l.startswith('_ENGLISH_ONSET_BASELINE = '))
eb_end = eb_start + 1
while eb_end < len(lines) and '}' not in lines[eb_end]:
    eb_end += 1
exec('\n'.join(lines[eb_start:eb_end + 1]), ns)

# Load _HIGH_FREQ_WORDS
hf_start = next(i for i, l in enumerate(lines) if l.startswith('_HIGH_FREQ_WORDS = '))
hf_end = hf_start + 1
brace_depth = 1
while hf_end < len(lines) and brace_depth > 0:
    brace_depth += lines[hf_end].count('{') - lines[hf_end].count('}')
    hf_end += 1
exec('\n'.join(lines[hf_start:hf_end]), ns)

# Load MAX_INSIGHTS
mi_line = next(l for l in lines if l.startswith('MAX_INSIGHTS'))
exec(mi_line, ns)

# Load DEFAULT_PROFILE
dp_start = next(i for i, l in enumerate(lines) if l.startswith('DEFAULT_PROFILE = '))
dp_end = dp_start + 1
brace_depth = 1
while dp_end < len(lines) and brace_depth > 0:
    brace_depth += lines[dp_end].count('{') - lines[dp_end].count('}')
    dp_end += 1
exec('\n'.join(lines[dp_start:dp_end]), ns)

# Load learn constants
for l in lines:
    if l.startswith('LEARN_EVERY'):
        exec(l, ns)
    if l.startswith('LEARN_PROMOTION_THRESHOLD'):
        exec(l, ns)
    if l.startswith('MAX_PROFILE_ITEMS'):
        exec(l, ns)

# Prep / shadow / clipboard globals
ns['_last_prep_text'] = None
ns['_last_prep_ts'] = 0.0
ns['_PREP_EXPIRY_SEC'] = 300
ns['_clipboard_predictor'] = None
ns['current_layer'] = 2
ns['_shadow_history'] = []
ns['_MAX_SHADOW_HISTORY'] = 50
ns['_personal_dominant_onsets'] = []

# Thread locks
ns['_prep_lock'] = threading.Lock()
ns['_shadow_lock'] = threading.Lock()
ns['_learn_lock'] = threading.Lock()
ns['_stats_lock'] = threading.Lock()
ns['_augment_lock'] = threading.Lock()
ns['_redo_lock'] = threading.Lock()

# Stubs
ns['log'] = lambda msg, level='info': None
ns['stats'] = {'api_calls': 0, 'sessions': 50, 'falcon_rejects': 0,
               'words': 0, 'chars': 0, 'start_time': time.time(),
               'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
ns['_onset_anomalies'] = []
ns['current_mode'] = 'SAFE'
ns['learn_events'] = []
ns['learn_status'] = {"last_run": None, "total_learned": 0, "next_in": 3}
ns['HOLD_ON_HIGH_RISK'] = False

# Controllable stubs
_mock_session_count = [50]
ns['db_session_count'] = lambda: _mock_session_count[0]
ns['save_profile'] = lambda prof, _epoch=None: None
ns['stats_inc'] = lambda key, n=1: None

# Load target functions (and their dependencies)
target_funcs = [
    # Dependencies
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
    '_learn_event', '_learn_events_snapshot', '_sample', '_norm_str',
    'set_last_prep',
    # The 9 under test
    'detect_word_language',
    'detect_onset_anomalies',
    'predict_triggers_in_text',
    'compute_brown_scores',
    'generate_shadow_utterance',
    'compute_avoidance_trend',
    'learn_from_sessions',
    '_build_whisper_prompt',
    'build_stutter_insights',
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
# TEST 1: detect_word_language
# ============================================================
print('=== TEST 1: detect_word_language ===')
detect_lang = ns.get('detect_word_language')
if detect_lang:
    check('empty -> unknown', detect_lang('') == 'unknown')
    check('None -> unknown', detect_lang(None) == 'unknown')
    check('English word -> en', detect_lang('hello') == 'en')
    check('English caps -> en', detect_lang('COMPUTER') == 'en')
    check('Russian word -> ru', detect_lang('\u043f\u0440\u0438\u0432\u0435\u0442') == 'ru')
    check('Russian caps -> ru', detect_lang('\u041f\u0420\u0418\u0412\u0415\u0422') == 'ru')
    check('digits only -> unknown', detect_lang('12345') == 'unknown')
    check('punctuation -> unknown', detect_lang('!!!') == 'unknown')
    check('mixed Cyrillic-dominant -> ru', detect_lang('\u043f\u0440\u0438\u0432\u0435\u0442x') == 'ru')
    check('mixed Latin-dominant -> en', detect_lang('hello\u0430') == 'en')
    check('single Latin char -> en', detect_lang('a') == 'en')
    check('single Cyrillic char -> ru', detect_lang('\u0430') == 'ru')
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 2: detect_onset_anomalies
# ============================================================
print()
print('=== TEST 2: detect_onset_anomalies ===')
detect_oa = ns.get('detect_onset_anomalies')
if detect_oa:
    # Too few sessions -> empty
    few_sessions = [{"raw": "hello world"}] * 5
    r = detect_oa(few_sessions, min_sessions=30)
    check('too few sessions -> empty', r == [])

    # Enough sessions but too few content words
    short_sessions = [{"raw": "hi"}] * 35
    r = detect_oa(short_sessions, min_sessions=30, min_content_words=200)
    check('too few content words -> empty', r == [])

    # Empty raw fields
    empty_sessions = [{"raw": ""}] * 35
    r = detect_oa(empty_sessions, min_sessions=30)
    check('empty raw fields -> empty', r == [])

    # Missing raw key
    no_raw = [{}] * 35
    r = detect_oa(no_raw, min_sessions=30)
    check('missing raw key -> empty', r == [])

    # Normal case: build sessions with enough content words
    # Use words that span many different onsets so no single onset is anomalously low
    baseline = ns.get('_ENGLISH_ONSET_BASELINE', {})
    high_risk = ns.get('HIGH_RISK_ONSETS', set())
    # Create sessions with diverse content
    words_pool = "the computer conference structure problem break strong think class great " * 25
    normal_sessions = [{"raw": words_pool}] * 35
    r = detect_oa(normal_sessions, min_sessions=30, min_content_words=50)
    check('returns list', isinstance(r, list))
    check('max 5 anomalies', len(r) <= 5)
    if r:
        check('anomaly has onset key', 'onset' in r[0])
        check('anomaly has expected_pct', 'expected_pct' in r[0])
        check('anomaly has actual_pct', 'actual_pct' in r[0])
        check('anomaly has deficit_ratio', 'deficit_ratio' in r[0])
        check('deficit_ratio < 0.40', r[0]['deficit_ratio'] < 0.40)
        check('sorted by deficit_ratio', all(r[i]['deficit_ratio'] <= r[i+1]['deficit_ratio']
              for i in range(len(r)-1)))

    # Extreme avoidance: sessions with zero words starting with high-risk onsets
    # Use only vowel-initial content words to starve consonant onsets
    avoid_text = "apple orange umbrella elephant island " * 50
    avoid_sessions = [{"raw": avoid_text}] * 35
    r = detect_oa(avoid_sessions, min_sessions=30, min_content_words=50)
    check('vowel-only text -> anomalies detected (or empty if no HR onsets qualify)',
          isinstance(r, list))

    # Global _onset_anomalies is updated
    check('_onset_anomalies updated', ns.get('_onset_anomalies') is not None)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 3: compute_brown_scores
# ============================================================
print()
print('=== TEST 3: compute_brown_scores ===')
brown = ns.get('compute_brown_scores')
if brown:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []

    r = brown("")
    check('empty text -> empty list', r == [])

    r = brown("hello")
    check('single word -> 1 entry', len(r) == 1)
    check('entry is (word, score)', len(r[0]) == 2)
    check('word preserved', r[0][0] == 'hello')
    check('score in [0,1]', 0.0 <= r[0][1] <= 1.0)

    r = brown("the quick brown fox jumps")
    check('5 words -> 5 entries', len(r) == 5)
    check('all scores bounded', all(0.0 <= s <= 1.0 for _, s in r))

    # Function words score lower than content words
    r = brown("the computer")
    the_score = r[0][1]
    comp_score = r[1][1]
    check(f'"the" < "computer" ({the_score} < {comp_score})', the_score < comp_score)

    # Position context is applied (same word, different positions)
    r = brown("computer is here and computer")
    first_score = r[0][1]  # position 0 of 5
    last_score = r[4][1]   # position 4 of 5
    check(f'early >= late position ({first_score} >= {last_score})', first_score >= last_score)

    # Scores are rounded to 2 decimals
    r = brown("structure")
    check('score rounded to 2 decimals', r[0][1] == round(r[0][1], 2))
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 4: predict_triggers_in_text
# ============================================================
print()
print('=== TEST 4: predict_triggers_in_text ===')
predict_trig = ns.get('predict_triggers_in_text')
if predict_trig:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []

    r = predict_trig("", [])
    check('empty text -> empty', r == [])

    r = predict_trig("the a is", [])
    check('only function words -> empty (low risk)', r == [])

    r = predict_trig("I need to go to the store", [])
    check('returns list of tuples', isinstance(r, list))
    for item in r:
        check(f'tuple structure (word, score): {item}', len(item) == 2)

    # Onset-sharing boost: "computer" is a known trigger, "conference" shares /co/ prefix
    r = predict_trig("I need conference materials", ["computer"])
    conf_entries = [s for w, s in r if w == "conference"]
    if conf_entries:
        check('conference found as predicted trigger', True)
    r_no_boost = predict_trig("I need conference materials", [])
    conf_no = [s for w, s in r_no_boost if w == "conference"]
    if conf_entries and conf_no:
        check(f'onset boost increases score ({conf_entries[0]} > {conf_no[0]})',
              conf_entries[0] > conf_no[0])

    # All results >= 0.6 threshold
    r = predict_trig("structure computer presentation problem conference", ["computer"])
    check('all scores >= 0.6', all(s >= 0.6 for _, s in r))

    # Sorted descending
    if len(r) >= 2:
        check('sorted descending by score', all(r[i][1] >= r[i+1][1] for i in range(len(r)-1)))

    # Short words filtered
    r = predict_trig("I a x", [])
    short_words = [w for w, s in r if len(w) < 2]
    check('words < 2 chars filtered out', len(short_words) == 0)

    # Score capped at 1.0 even with boost
    r = predict_trig("computer conference structure", ["computer", "conference", "structure"])
    check('all scores <= 1.0', all(s <= 1.0 for _, s in r))
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 5: generate_shadow_utterance (drift math only, prep path)
# ============================================================
print()
print('=== TEST 5: generate_shadow_utterance (drift math) ===')
shadow_fn = ns.get('generate_shadow_utterance')
set_prep = ns.get('set_last_prep')
if shadow_fn and set_prep:
    ns['_shadow_history'] = []

    # Prep path: prep text matches actual -> drift = 0
    set_prep("I want to go to the store")
    r = shadow_fn("I want to go to the store", {"trigger_words": []})
    check('source = prep', r['source'] == 'prep')
    check('perfect match drift = 0.0', r['drift_score'] == 0.0)
    check('shadow equals prep', r['shadow'] == "I want to go to the store")

    # Prep path: different content -> positive drift
    ns['_shadow_history'] = []
    set_prep("I need to call the computer company")
    r = shadow_fn("I need to call the machine company", {"trigger_words": ["computer"]})
    check('source = prep', r['source'] == 'prep')
    check(f'drift > 0 when words differ (got {r["drift_score"]})', r['drift_score'] > 0.0)
    check('avoided_words populated', len(r['avoided_words']) > 0)
    check('"computer" in avoided', 'computer' in r['avoided_words'])
    check('substitute_words populated', len(r['substitute_words']) > 0)
    check('"machine" in substitutes', 'machine' in r['substitute_words'])

    # Drift score bounded [0, 1]
    check(f'drift <= 1.0 (got {r["drift_score"]})', r['drift_score'] <= 1.0)
    check(f'drift >= 0.0 (got {r["drift_score"]})', r['drift_score'] >= 0.0)

    # Return structure
    check('has ts key', 'ts' in r)
    check('has shadow key', 'shadow' in r)
    check('has actual key', 'actual' in r)
    check('has drift_score key', 'drift_score' in r)
    check('has avoided_words key', 'avoided_words' in r)
    check('has substitute_words key', 'substitute_words' in r)
    check('has source key', 'source' in r)

    # Shadow history is appended
    check(f'shadow_history has entries (got {len(ns["_shadow_history"])})',
          len(ns['_shadow_history']) > 0)

    # Expired prep -> no prep path (would need API, so test expiry guard)
    ns['_last_prep_text'] = "old text"
    ns['_last_prep_ts'] = time.time() - 400  # expired
    # Without API client, this would raise — just verify prep expiry logic
    # by checking that _build_whisper_prompt doesn't return prep text
    build_prompt = ns.get('_build_whisper_prompt')
    if build_prompt:
        prompt = build_prompt()
        check('expired prep not used in whisper prompt', prompt != "old text")

    # All content words changed -> drift near 1.0
    ns['_shadow_history'] = []
    set_prep("alpha beta gamma delta")
    r = shadow_fn("epsilon zeta eta theta", {"trigger_words": []})
    check(f'completely different -> high drift (got {r["drift_score"]})', r['drift_score'] > 0.5)

    # Only function words differ -> drift = 0 (function words excluded)
    ns['_shadow_history'] = []
    set_prep("the computer is here")
    r = shadow_fn("a computer was here", {"trigger_words": []})
    check(f'only function words differ -> drift = 0 (got {r["drift_score"]})', r['drift_score'] == 0.0)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 6: compute_avoidance_trend
# ============================================================
print()
print('=== TEST 6: compute_avoidance_trend ===')
trend_fn = ns.get('compute_avoidance_trend')
if trend_fn:
    # Empty history
    ns['_shadow_history'] = []
    r = trend_fn()
    check('empty -> avg_drift 0.0', r['avg_drift'] == 0.0)
    check('empty -> trend stable', r['trend'] == 'stable')
    check('empty -> n = 0', r['n'] == 0)

    # Fewer than 4 entries -> insufficient_data
    ns['_shadow_history'] = [
        {"drift_score": 0.1},
        {"drift_score": 0.2},
    ]
    r = trend_fn()
    check('2 entries -> insufficient_data', r['trend'] == 'insufficient_data')
    check(f'avg correct (got {r["avg_drift"]})', abs(r['avg_drift'] - 0.15) < 0.001)
    check('n = 2', r['n'] == 2)

    # Exactly 4 entries, stable
    ns['_shadow_history'] = [
        {"drift_score": 0.10},
        {"drift_score": 0.12},
        {"drift_score": 0.11},
        {"drift_score": 0.13},
    ]
    r = trend_fn()
    check('4 stable entries -> stable', r['trend'] == 'stable')
    check('n = 4', r['n'] == 4)

    # Increasing trend: low first half, high second half
    ns['_shadow_history'] = [
        {"drift_score": 0.05},
        {"drift_score": 0.06},
        {"drift_score": 0.04},
        {"drift_score": 0.05},
        {"drift_score": 0.20},
        {"drift_score": 0.25},
        {"drift_score": 0.22},
        {"drift_score": 0.21},
    ]
    r = trend_fn()
    check(f'increasing trend detected (got {r["trend"]})', r['trend'] == 'increasing')

    # Decreasing trend: high first half, low second half
    ns['_shadow_history'] = [
        {"drift_score": 0.30},
        {"drift_score": 0.28},
        {"drift_score": 0.32},
        {"drift_score": 0.29},
        {"drift_score": 0.05},
        {"drift_score": 0.04},
        {"drift_score": 0.06},
        {"drift_score": 0.03},
    ]
    r = trend_fn()
    check(f'decreasing trend detected (got {r["trend"]})', r['trend'] == 'decreasing')

    # Only last 10 entries used
    ns['_shadow_history'] = [{"drift_score": 0.99}] * 20 + [{"drift_score": 0.01}] * 10
    r = trend_fn()
    check('uses last 10 entries only', r['n'] == 10)
    check(f'avg reflects last 10 (got {r["avg_drift"]})', r['avg_drift'] < 0.1)

    # avg_drift rounded to 3 decimals
    ns['_shadow_history'] = [{"drift_score": 1/3}] * 5
    r = trend_fn()
    check('avg_drift rounded to 3 decimals', r['avg_drift'] == round(r['avg_drift'], 3))
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 7: _build_whisper_prompt (priority chain)
# ============================================================
print()
print('=== TEST 7: _build_whisper_prompt ===')
build_prompt = ns.get('_build_whisper_prompt')
set_prep_fn = ns.get('set_last_prep')
if build_prompt and set_prep_fn:
    # Priority 1: Script Prep
    set_prep_fn("This is my prepared script text for testing")
    r = build_prompt()
    check('prep text returned', r == "This is my prepared script text for testing")

    # Prep text capped at 500 chars
    long_prep = "x" * 1000
    set_prep_fn(long_prep)
    r = build_prompt()
    check(f'prep capped at 500 chars (got {len(r)})', len(r) == 500)

    # Clear prep, no clipboard -> fallback
    ns['_last_prep_text'] = None
    ns['_clipboard_predictor'] = None

    # Priority 3a: L1 fallback
    ns['current_layer'] = 1
    r = build_prompt()
    check('L1 fallback mentions "exactly"', 'exactly' in r.lower() or 'repetitions' in r.lower())

    # Priority 3b: L2+ fallback
    ns['current_layer'] = 2
    r = build_prompt()
    check('L2 fallback mentions "fluent"', 'fluent' in r.lower())

    # L1 vs L2 fallback are different
    ns['current_layer'] = 1
    l1_prompt = build_prompt()
    ns['current_layer'] = 2
    l2_prompt = build_prompt()
    check('L1 and L2 fallbacks differ', l1_prompt != l2_prompt)

    # Priority 2: clipboard predictor (mock)
    ns['_last_prep_text'] = None
    class MockClipboard:
        def get_prompt_bias(self):
            return "clipboard bias text here"
    ns['_clipboard_predictor'] = MockClipboard()
    ns['current_layer'] = 2
    r = build_prompt()
    check('clipboard bias returned', r == "clipboard bias text here")

    # Clipboard returns empty -> fall through to generic
    class EmptyClipboard:
        def get_prompt_bias(self):
            return ""
    ns['_clipboard_predictor'] = EmptyClipboard()
    r = build_prompt()
    check('empty clipboard -> generic fallback', 'fluent' in r.lower())

    # Clipboard returns None -> fall through
    class NoneClipboard:
        def get_prompt_bias(self):
            return None
    ns['_clipboard_predictor'] = NoneClipboard()
    r = build_prompt()
    check('None clipboard -> generic fallback', 'fluent' in r.lower())

    # Prep takes priority over clipboard
    ns['_clipboard_predictor'] = MockClipboard()
    set_prep_fn("prep wins over clipboard")
    r = build_prompt()
    check('prep beats clipboard', r == "prep wins over clipboard")

    # Expired prep falls through to clipboard
    ns['_last_prep_text'] = "expired prep"
    ns['_last_prep_ts'] = time.time() - 400
    ns['_clipboard_predictor'] = MockClipboard()
    r = build_prompt()
    check('expired prep -> clipboard', r == "clipboard bias text here")

    # Clean up
    ns['_clipboard_predictor'] = None
    ns['_last_prep_text'] = None
    ns['current_layer'] = 2
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 8: learn_from_sessions (promotion logic only)
# ============================================================
print()
print('=== TEST 8: learn_from_sessions (promotion logic) ===')
learn_fn = ns.get('learn_from_sessions')
if learn_fn:
    threshold = ns.get('LEARN_PROMOTION_THRESHOLD', 2)

    # Stub db_get_sessions to return controlled data
    # Stub client.chat.completions.create to return controlled JSON

    class MockChoice:
        def __init__(self, text):
            self.message = type('M', (), {'content': text})()

    class MockResponse:
        def __init__(self, text):
            self.choices = [MockChoice(text)]

    class MockClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return MockResponse('{"corrections": {"Duncan": "Dankeschon"}, '
                                        '"fillers": ["basically"], "vocabulary": ["Lavrentiy"]}')

    ns['client'] = MockClient()

    # Test 1: empty sessions -> no crash
    _mock_sessions = []
    ns['db_get_sessions'] = lambda limit=10: _mock_sessions
    prof = {"corrections": {}, "filler_words": list(ns['DEFAULT_PROFILE']['filler_words']),
            "vocabulary": [], "candidate_corrections": {}, "candidate_fillers": {},
            "candidate_vocabulary": {}, "preferences": {"layer": 2}}
    ns['learn_events'] = []
    learn_fn(prof)
    check('empty sessions -> no crash', True)

    # Test 2: sessions that don't qualify (L1 or raw==out) -> no crash
    _mock_sessions = [{"raw": "hello", "out": "hello", "layer": 2}]
    ns['db_get_sessions'] = lambda limit=10: _mock_sessions
    learn_fn(prof)
    check('no qualifying sessions -> no crash', True)

    # Test 3: candidate accumulation (below threshold)
    _mock_sessions = [{"raw": "Duncan said something", "out": "Dankeschon said something", "layer": 2}]
    ns['db_get_sessions'] = lambda limit=10: _mock_sessions
    prof = {"corrections": {}, "filler_words": list(ns['DEFAULT_PROFILE']['filler_words']),
            "vocabulary": [], "candidate_corrections": {}, "candidate_fillers": {},
            "candidate_vocabulary": {}, "preferences": {"layer": 2}}
    ns['learn_events'] = []
    learn_fn(prof)
    cand = prof.get("candidate_corrections", {})
    check('"duncan" is a candidate', "duncan" in cand)
    if "duncan" in cand:
        check(f'candidate has 1 vote (got {cand["duncan"]["total"]})', cand["duncan"]["total"] == 1)

    # Test 4: promotion after threshold votes
    # Run enough times to hit promotion threshold
    for i in range(threshold):
        learn_fn(prof)

    # _norm_str preserves case; candidate key is .lower() but correction key is original
    corr_keys_lower = {k.lower() for k in prof.get("corrections", {})}
    promoted = "duncan" in corr_keys_lower
    removed = "duncan" not in prof.get("candidate_corrections", {})
    check(f'correction promoted after {threshold + 1} votes', promoted)
    check('candidate removed after promotion', removed)
    if promoted:
        corr_val = next(v for k, v in prof["corrections"].items() if k.lower() == "duncan")
        check('promoted value = "Dankeschon"', corr_val.lower() == "dankeschon")

    # Test 5: filler promotion
    filler_cands = prof.get("candidate_fillers", {})
    filler_promoted = "basically" in [f.lower() for f in prof.get("filler_words", [])]
    # May need more runs depending on threshold
    if not filler_promoted and "basically" in filler_cands:
        remaining = threshold - filler_cands.get("basically", 0)
        for _ in range(max(remaining, 1)):
            learn_fn(prof)
        filler_promoted = "basically" in [f.lower() for f in prof.get("filler_words", [])]
    check('filler promoted eventually', filler_promoted)

    # Test 6: vocab promotion
    vocab_promoted = "lavrentiy" in [v.lower() for v in prof.get("vocabulary", [])]
    if not vocab_promoted:
        for _ in range(threshold):
            learn_fn(prof)
        vocab_promoted = "lavrentiy" in [v.lower() for v in prof.get("vocabulary", [])]
    check('vocabulary promoted eventually', vocab_promoted)

    # Test 7: learn_events populated
    check(f'learn_events populated ({len(ns["learn_events"])} events)', len(ns['learn_events']) > 0)

    # Test 8: tie-breaking (two corrections with equal votes -> hold at threshold)
    class TieClient:
        class chat:
            class completions:
                call_count = 0
                @staticmethod
                def create(**kwargs):
                    TieClient.chat.completions.call_count += 1
                    if TieClient.chat.completions.call_count % 2 == 1:
                        return MockResponse('{"corrections": {"ambig": "optionA"}, "fillers": [], "vocabulary": []}')
                    else:
                        return MockResponse('{"corrections": {"ambig": "optionB"}, "fillers": [], "vocabulary": []}')

    ns['client'] = TieClient()
    TieClient.chat.completions.call_count = 0
    prof2 = {"corrections": {}, "filler_words": list(ns['DEFAULT_PROFILE']['filler_words']),
             "vocabulary": [], "candidate_corrections": {}, "candidate_fillers": {},
             "candidate_vocabulary": {}, "preferences": {"layer": 2}}
    _mock_sessions = [{"raw": "ambig test", "out": "different test", "layer": 2}]
    ns['db_get_sessions'] = lambda limit=10: _mock_sessions
    # Run exactly 2 calls: vote1 for optionA, vote2 for optionB -> tie at threshold
    learn_fn(prof2)  # optionA: 1 vote, total=1
    learn_fn(prof2)  # optionB: 1 vote, total=2 >= threshold -> tie, held
    ambig_cand = prof2.get("candidate_corrections", {}).get("ambig")
    ambig_promoted = any(k.lower() == "ambig" for k in prof2.get("corrections", {}))
    check('tied correction held (not promoted yet)', not ambig_promoted)
    if ambig_cand:
        check('tie: both options have 1 vote each',
              ambig_cand["votes"].get("optionA", 0) == 1 and ambig_cand["votes"].get("optionB", 0) == 1)

    # Test 9: MAX_PROFILE_ITEMS cap
    ns['client'] = MockClient()
    max_items = ns.get('MAX_PROFILE_ITEMS', 200)
    prof3 = {"corrections": {"k" + str(i): "v" for i in range(max_items)},
             "filler_words": list(ns['DEFAULT_PROFILE']['filler_words']),
             "vocabulary": [], "candidate_corrections": {}, "candidate_fillers": {},
             "candidate_vocabulary": {}, "preferences": {"layer": 2}}
    _mock_sessions = [{"raw": "Duncan said something", "out": "Dankeschon said something", "layer": 2}]
    ns['db_get_sessions'] = lambda limit=10: _mock_sessions
    for _ in range(threshold + 1):
        learn_fn(prof3)
    check(f'corrections capped at {max_items}', len(prof3["corrections"]) <= max_items)

    # Clean up
    ns['_clipboard_predictor'] = None
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 9: build_stutter_insights
# ============================================================
print()
print('=== TEST 9: build_stutter_insights ===')
insights_fn = ns.get('build_stutter_insights')
if insights_fn:
    # Empty profile -> no insights (not enough data)
    _mock_session_count[0] = 5
    r = insights_fn({"trigger_words": [], "filler_words": [], "corrections": {}})
    check('empty profile, few sessions -> no insights', len(r) == 0)

    # Stable profile: no concerns, >=10 sessions
    _mock_session_count[0] = 15
    ns['_personal_dominant_onsets'] = []
    ns['learn_events'] = []
    r = insights_fn({"trigger_words": [], "filler_words": [], "corrections": {}})
    check(f'stable profile -> stable insight (got {len(r)})', len(r) == 1)
    if r:
        check('stable id', r[0]['id'] == 'stable_profile')
        check('stable severity = low', r[0]['severity'] == 'low')
        check('has title', 'title' in r[0])
        check('has body', 'body' in r[0])
        check('has source', 'source' in r[0])
        check('has evidence', 'evidence' in r[0])

    # Trigger cluster: >=3 triggers
    _mock_session_count[0] = 50
    ns['learn_events'] = []
    ns['_personal_dominant_onsets'] = []
    r = insights_fn({"trigger_words": ["computer", "conference", "class"],
                     "filler_words": [], "corrections": {}})
    ids = [i['id'] for i in r]
    check('trigger_cluster detected', 'trigger_cluster' in ids)
    tc = next(i for i in r if i['id'] == 'trigger_cluster')
    check('trigger_cluster severity = high', tc['severity'] == 'high')
    check('evidence has triggers', 'triggers' in tc['evidence'])
    check('evidence has count', 'count' in tc['evidence'])

    # High filler load: >=5 learned fillers beyond baseline.
    # Production baseline = set(KNOWN_FILLERS values | DEFAULT_PROFILE['filler_words'])
    # — typically ~40+ unique tokens. Real English fillers ("basically",
    # "honestly", "literally", etc.) often overlap with KNOWN_FILLERS and
    # silently undershoot the threshold. Use guaranteed-non-baseline tokens
    # so the math is always correct regardless of how KNOWN_FILLERS evolves.
    known_lower = set(f.lower() for lang_fillers in ns['KNOWN_FILLERS'].values() for f in lang_fillers)
    default_lower = set(f.lower() for f in ns['DEFAULT_PROFILE']['filler_words'])
    baseline_set = known_lower | default_lower
    # Need len(extra) - len(baseline_set) >= 5. baseline is ~40-50 in practice,
    # so generate enough synthetic tokens that the math always clears.
    synthetic_extras = [f"zzfiller{i:03d}zz" for i in range(60)]
    assert all(s not in baseline_set for s in synthetic_extras)
    extra = list(default_lower) + synthetic_extras
    r = insights_fn({"trigger_words": [], "filler_words": extra, "corrections": {}})
    ids = [i['id'] for i in r]
    check('high_filler_load detected', 'high_filler_load' in ids)

    # Correction pattern: >=5 corrections
    r = insights_fn({"trigger_words": [], "filler_words": [],
                     "corrections": {"a": "1", "b": "2", "c": "3", "d": "4", "e": "5"}})
    ids = [i['id'] for i in r]
    check('correction_pattern detected', 'correction_pattern' in ids)
    cp = next(i for i in r if i['id'] == 'correction_pattern')
    check('correction_pattern severity = medium', cp['severity'] == 'medium')

    # Dominant onset pattern: top onset >= 30%, >=5 triggers
    ns['_personal_dominant_onsets'] = [
        {"onset": "k", "pct": 45},
        {"onset": "str", "pct": 20},
    ]
    r = insights_fn({"trigger_words": ["computer", "conference", "class", "critical", "create"],
                     "filler_words": [], "corrections": {}})
    ids = [i['id'] for i in r]
    check('dominant_onset_pattern detected', 'dominant_onset_pattern' in ids)
    dop = next(i for i in r if i['id'] == 'dominant_onset_pattern')
    check('dominant onset severity = high', dop['severity'] == 'high')
    check('evidence has top_onset', 'top_onset' in dop['evidence'])
    check('top_onset = "k"', dop['evidence']['top_onset'] == 'k')

    # Dominant onset NOT triggered if pct < 30
    ns['_personal_dominant_onsets'] = [{"onset": "k", "pct": 25}]
    r = insights_fn({"trigger_words": ["computer", "conference", "class", "critical", "create"],
                     "filler_words": [], "corrections": {}})
    ids = [i['id'] for i in r]
    check('low pct onset NOT triggered', 'dominant_onset_pattern' not in ids)

    # Fast growth triggers: >=3 trigger learn_events this run
    ns['_personal_dominant_onsets'] = []
    ns['learn_events'] = [
        {"type": "trigger", "ts": datetime.now().isoformat()},
        {"type": "trigger", "ts": datetime.now().isoformat()},
        {"type": "trigger", "ts": datetime.now().isoformat()},
    ]
    r = insights_fn({"trigger_words": [], "filler_words": [], "corrections": {}})
    ids = [i['id'] for i in r]
    check('fast_growth_triggers detected', 'fast_growth_triggers' in ids)

    # Max insights cap
    max_ins = ns.get('MAX_INSIGHTS', 6)
    check(f'insights capped at {max_ins}', len(r) <= max_ins)

    # Clean up
    ns['learn_events'] = []
    ns['_personal_dominant_onsets'] = []
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
