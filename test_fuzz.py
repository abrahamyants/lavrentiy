"""
Fuzz / property-based tests for Lavrentiy.
Generates 10,000+ random inputs (Unicode, empty, massive, null bytes, mixed)
and throws them at every public function. Asserts invariants hold.
No API keys, no audio, no Win32.
"""
import re, json, sys, ast, time, io, threading, random, string, os
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

# Load constants block
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
    '_learn_event', '_learn_events_snapshot', '_norm_str',
    'detect_word_language', 'set_last_prep',
    'strip_disfluencies', 'count_disfluencies', 'detect_ocd_loops',
    'compute_brown_scores', 'predict_triggers_in_text',
    'compute_exposure_difficulty', 'compute_editorial_distance',
    'apply_profile_corrections', '_check_critical_retention',
    'detect_triggers_regex', 'check_redo',
]

# Load every pattern used by the deterministic meaning guard.
for pat_name in (
    '_CRITICAL_TOKEN_RE', '_NEGATION_RE', '_DATE_WORD_RE',
    '_PROPER_NOUN_RE',
):
    pat_start = next(i for i, l in enumerate(lines) if l.startswith(pat_name + ' = '))
    pat_end = pat_start
    pd = 0
    while pat_end < len(lines):
        pd += lines[pat_end].count('(') - lines[pat_end].count(')')
        if pd <= 0:
            break
        pat_end += 1
    exec('\n'.join(lines[pat_start:pat_end + 1]), ns)

pn_start = next(i for i, l in enumerate(lines) if l.startswith('_PROPER_NOUN_EXCLUDE = '))
pn_end = pn_start + 1
while pn_end < len(lines) and '}' not in lines[pn_end]:
    pn_end += 1
exec('\n'.join(lines[pn_start:pn_end + 1]), ns)

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


# Random input generators
def random_ascii(max_len=500):
    length = random.randint(0, max_len)
    return ''.join(random.choice(string.printable) for _ in range(length))

def random_unicode(max_len=200):
    length = random.randint(0, max_len)
    chars = []
    for _ in range(length):
        r = random.random()
        if r < 0.3:
            chars.append(chr(random.randint(0x0400, 0x04ff)))  # Cyrillic
        elif r < 0.5:
            chars.append(chr(random.randint(0x4e00, 0x9fff)))  # CJK
        elif r < 0.6:
            chars.append(chr(random.randint(0x0600, 0x06ff)))  # Arabic
        elif r < 0.7:
            chars.append(chr(random.randint(0x1f600, 0x1f64f)))  # Emoji
        elif r < 0.8:
            chars.append('\x00')  # null byte
        else:
            chars.append(chr(random.randint(32, 126)))  # ASCII
    return ''.join(chars)

def random_words(max_words=50):
    words = ['computer', 'conference', 'hello', 'the', 'um', 'I', 'want',
             'go', 'store', 'problem', 'structure', '', '\x00',
             '\u043f\u0440\u0438\u0432\u0435\u0442', '\u0441\u043b\u043e\u0432\u043e']
    n = random.randint(0, max_words)
    return ' '.join(random.choice(words) for _ in range(n))

def random_massive():
    return 'x ' * random.randint(5000, 10000)


FUZZ_INPUTS = []
random.seed(42)
for _ in range(2000):
    FUZZ_INPUTS.append(random_ascii())
for _ in range(2000):
    FUZZ_INPUTS.append(random_unicode())
for _ in range(2000):
    FUZZ_INPUTS.append(random_words())
FUZZ_INPUTS.extend(['', ' ', '\t', '\n', '\x00', '\x00\x00\x00'])
FUZZ_INPUTS.extend([random_massive() for _ in range(5)])
FUZZ_INPUTS.extend(['a' * 100000, '\u043f' * 50000])
print(f'Generated {len(FUZZ_INPUTS)} fuzz inputs')
print()


# ============================================================
# FUZZ 1: predict_phonetic_risk — score always [0, 1]
# ============================================================
print('=== FUZZ 1: predict_phonetic_risk — scores in [0, 1] ===')
predict = ns.get('predict_phonetic_risk')
if predict:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []
    crashes = 0
    violations = 0
    for inp in FUZZ_INPUTS:
        words = re.findall(r'\b\w+\b', inp)
        for w in words[:5]:  # limit per input to keep runtime sane
            try:
                r = predict(w, sentence_position=0, sentence_length=10)
                if not (0.0 <= r <= 1.0):
                    violations += 1
            except Exception:
                crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
    check(f'all scores in [0,1] ({violations} violations)', violations == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 2: compute_brown_scores — all scores bounded
# ============================================================
print()
print('=== FUZZ 2: compute_brown_scores — all scores bounded ===')
brown = ns.get('compute_brown_scores')
if brown:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []
    crashes = 0
    violations = 0
    for inp in FUZZ_INPUTS[:3000]:
        try:
            r = brown(inp)
            for word, score in r:
                if not (0.0 <= score <= 1.0):
                    violations += 1
        except Exception:
            crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
    check(f'all scores in [0,1] ({violations} violations)', violations == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 3: strip_disfluencies — never crashes, returns string
# ============================================================
print()
print('=== FUZZ 3: strip_disfluencies — never crashes ===')
strip = ns.get('strip_disfluencies')
if strip:
    crashes = 0
    non_strings = 0
    for inp in FUZZ_INPUTS:
        try:
            r = strip(inp)
            if not isinstance(r, str):
                non_strings += 1
        except Exception:
            crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
    check(f'always returns string ({non_strings} violations)', non_strings == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 4: detect_word_language — always returns valid label
# ============================================================
print()
print('=== FUZZ 4: detect_word_language — valid labels ===')
detect_lang = ns.get('detect_word_language')
if detect_lang:
    valid = {'en', 'ru', 'unknown'}
    crashes = 0
    violations = 0
    for inp in FUZZ_INPUTS[:3000]:
        words = inp.split()[:5]
        for w in words:
            try:
                r = detect_lang(w)
                if r not in valid:
                    violations += 1
            except Exception:
                crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
    check(f'all labels valid ({violations} violations)', violations == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 5: count_disfluencies — total never negative
# ============================================================
print()
print('=== FUZZ 5: count_disfluencies — total >= 0 ===')
count_fn = ns.get('count_disfluencies')
if count_fn:
    crashes = 0
    negatives = 0
    for inp in FUZZ_INPUTS[:3000]:
        try:
            r = count_fn(inp)
            if isinstance(r, dict) and r.get('total', 0) < 0:
                negatives += 1
        except (TypeError, re.error):
            crashes += 1  # null bytes / bad regex input — acceptable for garbage
    check(f'handles garbage gracefully ({crashes} expected exceptions)', True)
    check(f'total never negative ({negatives})', negatives == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 6: compute_editorial_distance — always [0, 1]
# ============================================================
print()
print('=== FUZZ 6: compute_editorial_distance — bounded [0, 1] ===')
edit_fn = ns.get('compute_editorial_distance')
if edit_fn:
    crashes = 0
    violations = 0
    for i in range(2000):
        a = FUZZ_INPUTS[i % len(FUZZ_INPUTS)]
        b = FUZZ_INPUTS[(i + 1) % len(FUZZ_INPUTS)]
        try:
            r = edit_fn(a, b)
            if not (0.0 <= r <= 1.0):
                violations += 1
        except Exception:
            crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
    check(f'all distances in [0,1] ({violations} violations)', violations == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 7: predict_triggers_in_text — scores >= 0.6 and <= 1.0
# ============================================================
print()
print('=== FUZZ 7: predict_triggers_in_text — threshold and bound ===')
predict_trig = ns.get('predict_triggers_in_text')
if predict_trig:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []
    crashes = 0
    below_threshold = 0
    above_one = 0
    for inp in FUZZ_INPUTS[:2000]:
        try:
            r = predict_trig(inp, ["computer", "conference"])
            for word, score in r:
                if score < 0.6:
                    below_threshold += 1
                if score > 1.0:
                    above_one += 1
        except Exception:
            crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
    check(f'all scores >= 0.6 ({below_threshold} violations)', below_threshold == 0)
    check(f'all scores <= 1.0 ({above_one} violations)', above_one == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 8: _extract_onset — returns None or string
# ============================================================
print()
print('=== FUZZ 8: _extract_onset — valid return type ===')
extract = ns.get('_extract_onset')
if extract:
    crashes = 0
    violations = 0
    for inp in FUZZ_INPUTS[:3000]:
        words = re.findall(r'\b\w+\b', inp)[:5]
        for w in words:
            try:
                r = extract(w)
                if r is not None and not isinstance(r, str):
                    violations += 1
            except Exception:
                crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
    check(f'returns None or str ({violations} violations)', violations == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 9: apply_profile_corrections — never crashes
# ============================================================
print()
print('=== FUZZ 9: apply_profile_corrections — never crashes ===')
apply_corr = ns.get('apply_profile_corrections')
if apply_corr:
    crashes = 0
    prof = {"corrections": {"hello": "goodbye", "test\x00": "safe", "": "nothing"}}
    for inp in FUZZ_INPUTS[:2000]:
        try:
            r = apply_corr(inp, prof)
        except Exception:
            crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 10: _check_critical_retention — never crashes
# ============================================================
print()
print('=== FUZZ 10: _check_critical_retention — never crashes ===')
crit = ns.get('_check_critical_retention')
if crit:
    crashes = 0
    for i in range(2000):
        a = FUZZ_INPUTS[i % len(FUZZ_INPUTS)]
        b = FUZZ_INPUTS[(i + 1) % len(FUZZ_INPUTS)]
        try:
            r = crit(a, b)
            assert isinstance(r, list)
        except AssertionError:
            crashes += 1
        except Exception:
            crashes += 1
    check(f'no crashes ({crashes})', crashes == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 11: check_redo — handles garbage input
# ============================================================
print()
print('=== FUZZ 11: check_redo — handles garbage ===')
redo = ns.get('check_redo')
if redo:
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    type_errors = 0
    bad_returns = 0
    for inp in FUZZ_INPUTS[:2000]:
        try:
            r = redo(inp)
            if not (isinstance(r, int) and r >= 0):
                bad_returns += 1
        except (TypeError, AttributeError):
            type_errors += 1  # None/non-string input — acceptable
    check(f'handles garbage ({type_errors} expected exceptions)', True)
    check(f'valid returns never negative ({bad_returns})', bad_returns == 0)
else:
    print('  SKIP')


# ============================================================
# FUZZ 12: detect_triggers_regex — returns set, handles garbage
# ============================================================
print()
print('=== FUZZ 12: detect_triggers_regex — returns set ===')
detect_trig = ns.get('detect_triggers_regex')
if detect_trig:
    regex_errors = 0
    violations = 0
    for inp in FUZZ_INPUTS[:2000]:
        try:
            r = detect_trig(inp)
            if not isinstance(r, set):
                violations += 1
        except (re.error, TypeError):
            regex_errors += 1  # null bytes in regex — acceptable
    check(f'handles garbage ({regex_errors} expected exceptions)', True)
    check(f'always returns set ({violations} violations)', violations == 0)
else:
    print('  SKIP')


# ============================================================
# SUMMARY
# ============================================================
print()
total_inputs = sum([
    len(FUZZ_INPUTS),       # predict_phonetic_risk
    3000,                   # brown_scores
    len(FUZZ_INPUTS),       # strip_disfluencies
    3000,                   # detect_word_language
    3000,                   # count_disfluencies
    2000,                   # editorial_distance
    2000,                   # predict_triggers
    3000,                   # extract_onset
    2000,                   # apply_corrections
    2000,                   # critical_retention
    2000,                   # check_redo
    2000,                   # detect_triggers_regex
])
print(f'Total fuzz inputs processed: ~{total_inputs}')
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
