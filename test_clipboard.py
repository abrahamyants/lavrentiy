"""
Tests for ClipboardPredictor scoring logic.
Extracts the class, tests compute_brown_scores integration, bias cache TTL,
situation-change invalidation, and the priority chain (prep > clipboard > fallback).
No API keys, no audio, no Win32. No pyperclip needed (clipboard mocked).
"""
import re, json, sys, ast, time, io, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
from datetime import datetime, timedelta

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

ns = {
    're': re, 'json': json, 'time': time,
    'datetime': datetime, 'timedelta': timedelta,
    'Path': Path, 'difflib': __import__('difflib'),
    'threading': threading,
}

# Load constants
start_idx = next(i for i, l in enumerate(lines) if l.startswith('LANGUAGE = '))
end_idx = next(i for i, l in enumerate(lines) if '_personal_onset_weights_by_lang' in l and '=' in l)
exec('\n'.join(lines[start_idx:end_idx + 1]), ns)

fw_start = next(i for i, l in enumerate(lines) if l.startswith('FUNCTION_WORDS = '))
fw_end = fw_start + 1
while fw_end < len(lines) and '}' not in lines[fw_end]:
    fw_end += 1
exec('\n'.join(lines[fw_start:fw_end + 1]), ns)

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

# Clipboard constants
for l in lines:
    for prefix in ('_CLIPBOARD_CACHE_TTL', '_CLIPBOARD_POLL_INTERVAL',
                   '_CLIPBOARD_RISK_THRESHOLD', '_CLIPBOARD_TOP_N',
                   '_CLIPBOARD_MIN_TRIGGERS'):
        if l.startswith(prefix):
            exec(l, ns)
hs_line = next(l for l in lines if l.startswith('_CLIPBOARD_HIGH_PRESSURE'))
exec(hs_line, ns)

# Globals
ns['_onset_anomalies'] = []
ns['_personal_onset_weights'] = {}
ns['_personal_dominant_onsets'] = []
ns['_last_prep_text'] = None
ns['_last_prep_ts'] = 0.0
ns['_PREP_EXPIRY_SEC'] = 300
ns['current_layer'] = 2
ns['current_situation'] = 'default'
ns['_stats_lock'] = threading.Lock()
ns['_prep_lock'] = threading.Lock()
ns['_shadow_lock'] = threading.Lock()
ns['_learn_lock'] = threading.Lock()
ns['stats'] = {'api_calls': 0}
ns['log'] = lambda msg, level='info': None
ns['stats_inc'] = lambda key, n=1: None
ns['HOLD_ON_HIGH_RISK'] = False
ns['current_mode'] = 'SAFE'
ns['MODEL'] = 'gpt-4o-mini'

# Extract functions and class
target_funcs = [
    '_extract_onset', 'predict_phonetic_risk', 'compute_brown_scores',
    'set_last_prep', '_build_whisper_prompt',
]

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
        func_source = ast.get_source_segment(source, node)
        if func_source:
            try:
                exec(func_source, ns)
            except Exception as e:
                print(f'SKIP {node.name}: {e}')

# Extract ClipboardPredictor class
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'ClipboardPredictor':
        cls_source = ast.get_source_segment(source, node)
        if cls_source:
            try:
                exec(cls_source, ns)
            except Exception as e:
                print(f'SKIP ClipboardPredictor: {e}')

loaded = [k for k in target_funcs if k in ns]
cp_loaded = 'ClipboardPredictor' in ns
print(f'Loaded {len(loaded)}/{len(target_funcs)} functions + ClipboardPredictor={cp_loaded}')
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
# TEST 1: ClipboardPredictor — cache TTL
# ============================================================
print('=== TEST 1: ClipboardPredictor — cache TTL ===')
CP = ns.get('ClipboardPredictor')
if CP:
    cp = CP()
    # Initially empty
    check('initial bias is None', cp.get_prompt_bias() is None)

    # Set bias manually
    with cp._lock:
        cp._bias = "test bias text"
        cp._bias_ts = time.time()
    check('fresh bias returned', cp.get_prompt_bias() == "test bias text")

    # Expire the cache
    with cp._lock:
        cp._bias_ts = time.time() - ns['_CLIPBOARD_CACHE_TTL'] - 1
    check('expired bias returns None', cp.get_prompt_bias() is None)

    # Just barely fresh
    with cp._lock:
        cp._bias = "still fresh"
        cp._bias_ts = time.time() - ns['_CLIPBOARD_CACHE_TTL'] + 5
    check('barely fresh -> returned', cp.get_prompt_bias() == "still fresh")
else:
    print('  SKIP: class not loaded')


# ============================================================
# TEST 2: ClipboardPredictor — invalidate()
# ============================================================
print()
print('=== TEST 2: ClipboardPredictor — invalidate() ===')
if CP:
    cp = CP()
    with cp._lock:
        cp._bias = "some bias"
        cp._bias_ts = time.time()
        cp._last_clipboard = "some clipboard content"

    check('bias exists before invalidate', cp.get_prompt_bias() == "some bias")
    cp.invalidate()
    check('bias None after invalidate', cp.get_prompt_bias() is None)
    check('last_clipboard cleared', cp._last_clipboard == "")
    check('bias_ts reset to 0', cp._bias_ts == 0.0)
else:
    print('  SKIP: class not loaded')


# ============================================================
# TEST 3: ClipboardPredictor — situation filtering in _tick
# ============================================================
print()
print('=== TEST 3: ClipboardPredictor — situation filtering ===')
if CP:
    cp = CP()
    # Mock pyperclip
    ns['pyperclip'] = type('mock', (), {'paste': staticmethod(lambda: "computer conference structure")})()

    # Low-pressure situation -> bias cleared
    ns['current_situation'] = 'casual'
    with cp._lock:
        cp._bias = "should be cleared"
        cp._bias_ts = time.time()
    cp._tick()
    check('casual situation -> bias cleared', cp.get_prompt_bias() is None)

    # Default situation -> bias cleared
    ns['current_situation'] = 'default'
    with cp._lock:
        cp._bias = "should be cleared"
        cp._bias_ts = time.time()
    cp._tick()
    check('default situation -> bias cleared', cp.get_prompt_bias() is None)

    # High-pressure situations should proceed (may or may not generate bias
    # depending on clipboard content and risk scoring)
    for sit in ('phone', 'interview', 'presentation'):
        ns['current_situation'] = sit
        cp.invalidate()
        # Mock the LLM call in _build_bias to avoid needing real API
        cp._build_bias = lambda triggers, situation: f"bias for {situation}: {triggers}"
        cp._tick()
        # If clipboard has enough high-risk words, bias will be set
        # Just verify no crash
        check(f'{sit} situation -> no crash', True)

    ns['current_situation'] = 'default'
else:
    print('  SKIP: class not loaded')


# ============================================================
# TEST 4: compute_brown_scores integration with clipboard
# ============================================================
print()
print('=== TEST 4: compute_brown_scores integration ===')
brown = ns.get('compute_brown_scores')
if brown:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []

    # Simulate clipboard text with high-risk words
    clipboard = "I need to call the computer company about the conference structure"
    scores = brown(clipboard)
    check('scores returned', len(scores) > 0)

    # Verify deduplication logic (as clipboard predictor does)
    best = {}
    for word, risk in scores:
        w = word.lower()
        if w not in best or risk > best[w]:
            best[w] = risk
    top = sorted(best.items(), key=lambda x: x[1], reverse=True)[:ns.get('_CLIPBOARD_TOP_N', 6)]
    threshold = ns.get('_CLIPBOARD_RISK_THRESHOLD', 0.55)
    high_risk = [(w, r) for w, r in top if r >= threshold]
    check(f'high-risk words found ({len(high_risk)})', len(high_risk) > 0)
    check('all high-risk above threshold',
          all(r >= threshold for _, r in high_risk))
    check('sorted descending',
          all(top[i][1] >= top[i+1][1] for i in range(len(top)-1)))

    # Content words score higher than function words
    content_scores = {w: r for w, r in scores if w.lower() not in ns.get('FUNCTION_WORDS', set())}
    function_scores = {w: r for w, r in scores if w.lower() in ns.get('FUNCTION_WORDS', set())}
    if content_scores and function_scores:
        max_func = max(function_scores.values())
        max_content = max(content_scores.values())
        check(f'content > function ({max_content} > {max_func})', max_content > max_func)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 5: Priority chain — prep > clipboard > fallback
# ============================================================
print()
print('=== TEST 5: Priority chain — prep > clipboard > fallback ===')
build_prompt = ns.get('_build_whisper_prompt')
set_prep = ns.get('set_last_prep')
if build_prompt and set_prep and CP:
    # Tier 3: No prep, no clipboard -> generic fallback
    ns['_last_prep_text'] = None
    ns['_clipboard_predictor'] = None
    ns['current_layer'] = 2
    r = build_prompt()
    check('no prep/clipboard -> generic fallback', 'fluent' in r.lower())

    # Tier 2: Clipboard available -> clipboard bias
    cp = CP()
    with cp._lock:
        cp._bias = "clipboard bias for testing"
        cp._bias_ts = time.time()
    ns['_clipboard_predictor'] = cp
    ns['_last_prep_text'] = None
    r = build_prompt()
    check('clipboard -> clipboard bias', r == "clipboard bias for testing")

    # Tier 1: Prep available -> prep wins over clipboard
    set_prep("prep text wins")
    ns['_clipboard_predictor'] = cp
    r = build_prompt()
    check('prep -> prep text (beats clipboard)', r == "prep text wins")

    # Expired prep -> falls through to clipboard
    ns['_last_prep_text'] = "expired"
    ns['_last_prep_ts'] = time.time() - 400
    r = build_prompt()
    check('expired prep -> clipboard', r == "clipboard bias for testing")

    # Expired clipboard -> falls through to generic
    with cp._lock:
        cp._bias_ts = time.time() - ns['_CLIPBOARD_CACHE_TTL'] - 1
    r = build_prompt()
    check('expired clipboard -> generic fallback', 'fluent' in r.lower())

    # Clean up
    ns['_clipboard_predictor'] = None
    ns['_last_prep_text'] = None
else:
    print('  SKIP: functions not loaded')


# ============================================================
# TEST 6: ClipboardPredictor — _build_bias structure
# ============================================================
print()
print('=== TEST 6: _build_bias output structure ===')
if CP:
    cp = CP()

    # Mock the LLM client
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
                    return MockResponse("computer->machine, conference->meeting")
    ns['client'] = MockClient()
    ns['_personal_onset_weights'] = {'k': 0.8, 'str': 0.6, 'p': 0.5}

    result = cp._build_bias(["computer", "conference"], "phone")
    check('returns string', isinstance(result, str))
    check('contains situation', 'phone' in result)
    check('contains synonyms', 'machine' in result or 'meeting' in result)
    check('contains instruction', 'reconstruct' in result.lower() or 'context' in result.lower())

    # Empty weights -> uses "plosives" default
    ns['_personal_onset_weights'] = {}
    result2 = cp._build_bias(["test"], "interview")
    check('empty weights -> still returns string', isinstance(result2, str))

    # LLM failure -> returns None
    class FailClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise Exception("API error")
    ns['client'] = FailClient()
    result3 = cp._build_bias(["test"], "phone")
    check('LLM failure -> returns None', result3 is None)
else:
    print('  SKIP: class not loaded')


# ============================================================
# TEST 7: ClipboardPredictor — min triggers threshold
# ============================================================
print()
print('=== TEST 7: Min triggers threshold ===')
if CP and brown:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []

    # Text with only low-risk words
    low_risk_text = "the a is and or but"
    scores = brown(low_risk_text)
    threshold = ns.get('_CLIPBOARD_RISK_THRESHOLD', 0.55)
    high_risk = [(w, r) for w, r in scores if r >= threshold]
    min_triggers = ns.get('_CLIPBOARD_MIN_TRIGGERS', 2)
    check(f'low-risk text has < {min_triggers} high-risk words ({len(high_risk)})',
          len(high_risk) < min_triggers)

    # Text with many high-risk words
    high_risk_text = "computer conference structure problem presentation"
    scores2 = brown(high_risk_text)
    high_risk2 = [(w, r) for w, r in scores2 if r >= threshold]
    check(f'high-risk text has >= {min_triggers} triggers ({len(high_risk2)})',
          len(high_risk2) >= min_triggers)
else:
    print('  SKIP: class or function not loaded')


# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
