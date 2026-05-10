"""
Isolated unit tests for Lavrentiy core logic functions.
Tests pure functions without needing audio hardware, API keys, or Win32.
"""
import os, re, json, sys, difflib, time, ast

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace with needed constants. `os` is needed because the
# constants block in lavrentiy.py (LANGUAGE..._personal_onset_weights_by_lang)
# uses os.environ.get(...) for env-var-driven config (LOCAL_FW_*, LAV_LOCAL_LLM
# etc.). Without it, exec(const_block, ns) raises NameError at the first
# os.environ.get call. Past CI failures all came from this gap.
from pathlib import Path
ns = {'os': os, 're': re, 'json': json, 'difflib': difflib, 'time': time, 'Path': Path}

# Dynamically find constants block: from LANGUAGE= through _personal_onset_weights_by_lang
# This avoids hardcoded line numbers breaking when code is added above.
start_idx = next(i for i, l in enumerate(lines) if l.startswith('LANGUAGE = '))
end_idx = next(i for i, l in enumerate(lines) if '_personal_onset_weights_by_lang' in l and '=' in l)
const_block = '\n'.join(lines[start_idx:end_idx + 1])
exec(const_block, ns)

# Set defaults for globals that may not be in the constant block
ns.setdefault('_onset_anomalies', [])
ns.setdefault('_COMMON_WORDS', set())

# Stub out log and stats
ns['log'] = lambda msg, level='info': None
ns['stats'] = {'api_calls': 0}
ns['current_mode'] = 'SAFE'
ns['HOLD_ON_HIGH_RISK'] = False
ns['_DANGLING'] = re.compile(r'(?:,|\band\s*$|\bor\s*$|\bbut\s*$|\.{2}(?!\.)|\bthe\s*$)', re.IGNORECASE)

# Extract and exec pure functions
testable_funcs = [
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
    'compute_wer', 'compute_risk_flags', 'make_decision',
]

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in testable_funcs:
        func_source = ast.get_source_segment(source, node)
        if func_source:
            try:
                exec(func_source, ns)
            except Exception as e:
                print(f'SKIP {node.name}: {e}')

loaded = [k for k in testable_funcs if k in ns]
print(f'Loaded {len(loaded)}/{len(testable_funcs)} functions: {loaded}')
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
# TEST 1: _extract_onset
# ============================================================
print('=== TEST 1: _extract_onset ===')
extract = ns.get('_extract_onset')
if extract:
    check('vowel-initial returns None', extract('apple') is None)
    check('empty returns None', extract('') is None)
    # FIXED: 'c' added to HIGH_RISK_ONSETS — maps to /k/ (cat, come) or /s/ (city).
    # _extract_onset("computer") now returns 'c'.
    r = extract('computer')
    check(f'"computer" -> "c" (got {r})', r == 'c')
    r4 = extract('call')
    check(f'"call" -> "c" (got {r4})', r4 == 'c')
    r5 = extract('city')
    check(f'"city" -> "c" (got {r5})', r5 == 'c')
    r2 = extract('break')
    check(f'"break" -> onset (got {r2})', r2 is not None)
    r3 = extract('strong')
    check(f'"strong" -> onset (got {r3})', r3 is not None)

# ============================================================
# TEST 2: learn_onset_weights
# ============================================================
print()
print('=== TEST 2: learn_onset_weights ===')
learn = ns.get('learn_onset_weights')
if learn:
    learn(['computer', 'conference', 'class', 'critical', 'create', 'break', 'problem'])
    w = ns['_personal_onset_weights']
    d = ns['_personal_dominant_onsets']
    check(f'weights non-empty ({len(w)} onsets)', len(w) > 0)
    check(f'dominants non-empty ({len(d)} entries)', len(d) > 0)
    check('all weights in [0,1]', all(0 <= v <= 1 for v in w.values()))

    # Empty input clears
    learn([])
    check('empty triggers -> empty weights', ns['_personal_onset_weights'] == {})
    check('empty triggers -> empty dominants', ns['_personal_dominant_onsets'] == [])

    # Single trigger
    learn(['problem'])
    check('single trigger -> non-empty', len(ns['_personal_onset_weights']) > 0)
    learn([])

# ============================================================
# TEST 3: predict_phonetic_risk (Brown 4-factor)
# ============================================================
print()
print('=== TEST 3: predict_phonetic_risk (Brown 4-factor) ===')
predict = ns.get('predict_phonetic_risk')
if predict:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []

    # Function words = low risk
    check('"the" low risk', predict('the') <= 0.15, f'got {predict("the")}')
    check('"a" low risk', predict('a') <= 0.15, f'got {predict("a")}')
    check('"is" low risk', predict('is') <= 0.15, f'got {predict("is")}')

    # Content words with risky onsets = higher
    c_risk = predict('computer')
    h_risk = predict('hello')
    check(f'"computer" > "hello" ({c_risk:.2f} > {h_risk:.2f})', c_risk > h_risk)

    # Brown feature 3: sentence position
    early = predict('computer', sentence_position=0, sentence_length=10)
    late = predict('computer', sentence_position=9, sentence_length=10)
    check(f'early >= late ({early:.2f} >= {late:.2f})', early >= late)

    # Brown feature 4: word length (compare same onset class for fair test)
    # 'go' has 'g' onset (high risk) making it score higher than length alone
    # Use vowel-initial words to isolate the length factor
    short_risk = predict('ask')
    long_risk = predict('understand')
    check(f'longer >= shorter ({long_risk:.2f} >= {short_risk:.2f})', long_risk >= short_risk)

    # Risk is bounded [0, 1]
    extreme = predict('structure', sentence_position=0, sentence_length=1)
    check(f'risk bounded <= 1.0 (got {extreme:.2f})', extreme <= 1.0)
    check(f'risk bounded >= 0.0 (got {extreme:.2f})', extreme >= 0.0)

    # Personal weights change output
    if learn:
        learn(['computer', 'conference', 'class', 'critical'])
        personal = predict('computer')
        learn([])
        ns['_onset_anomalies'] = []
        generic = predict('computer')
        check(f'personal weights change score ({personal:.2f} vs {generic:.2f})',
              abs(personal - generic) > 0.001)  # personal onset weights must measurably shift the score

# ============================================================
# TEST 4: SITUATION_SEVERITY values match README
# ============================================================
print()
print('=== TEST 4: SITUATION_SEVERITY ===')
sev = ns.get('SITUATION_SEVERITY', {})
for sit, expected in [('default', 1.0), ('high_stress', 1.5), ('reading', 0.3)]:
    check(f'{sit} = {expected}', sev.get(sit) == expected, f'got {sev.get(sit)}')

# ============================================================
# TEST 5: compute_wer
# ============================================================
print()
print('=== TEST 5: compute_wer ===')
wer_fn = ns.get('compute_wer')
if wer_fn:
    w, s, d, i = wer_fn('hello world', 'hello world')
    check(f'perfect match WER=0 (got {w:.2f})', w == 0.0)

    w, s, d, i = wer_fn('hello world', 'hello earth')
    check(f'one substitution S=1 (got S={s})', s == 1)

    w, s, d, i = wer_fn('hello beautiful world', 'hello world')
    check(f'deletion D>=1 (got D={d})', d >= 1)

    w, s, d, i = wer_fn('hello world', '')
    check(f'empty hyp WER>=1.0 (got {w:.2f})', w >= 1.0)

    w, s, d, i = wer_fn('', '')
    check(f'both empty WER=0 (got {w:.2f})', w == 0.0)

# ============================================================
# TEST 6: compute_risk_flags
# ============================================================
print()
print('=== TEST 6: compute_risk_flags ===')
flags_fn = ns.get('compute_risk_flags')
if flags_fn:
    f = flags_fn('hello world', 'hello world', True, False, 2)
    check('clean run = no flags', len(f) == 0, str(f))

    f = flags_fn('hello world', 'hello world', False, False, 2)
    check('falcon reject flagged', 'validator_reject' in f)

    f = flags_fn('hello world', 'hello world', True, True, 2)
    check('fallback flagged', 'reconstruct_fallback' in f)

    f = flags_fn('hello this is a long sentence with many words', 'hi', True, False, 2)
    check('very short output flagged', 'very_short_output' in f)

# ============================================================
# TEST 7: make_decision
# ============================================================
print()
print('=== TEST 7: make_decision ===')
decide = ns.get('make_decision')
if decide:
    ns['current_mode'] = 'SAFE'
    d = decide(True, 2, False, [])
    check('SAFE + falcon_ok -> paste_clean', d['decision'] == 'paste_clean')

    d = decide(False, 2, False, [])
    check('SAFE + falcon_reject -> paste_raw', d['decision'] == 'paste_raw')

    ns['current_mode'] = 'RAW'
    d = decide(True, 2, False, [])
    check('RAW mode -> paste_raw', d['decision'] == 'paste_raw')

    ns['current_mode'] = 'FAST'
    d = decide(True, 2, False, [])
    check('FAST mode -> paste_clean', d['decision'] == 'paste_clean')

    # L1 always raw regardless of mode
    ns['current_mode'] = 'SAFE'
    d = decide(True, 1, False, [])
    check('L1 -> paste_raw', d['decision'] == 'paste_raw')

# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
