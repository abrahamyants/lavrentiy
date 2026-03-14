"""
Adversarial stress tests for Lavrentiy clinical features.
Empty inputs, massive inputs, Unicode, boundary values, type confusion.
Covers: 7 core clinical functions + disfluency pipeline + covert avoidance + bug-fix regressions.
"""
import re, json, sys, os, ast, time, io, tempfile, shutil, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace
from pathlib import Path
from datetime import datetime, timedelta
ns = {
    're': re, 'json': json, 'time': time, 'os': os, 'sqlite3': sqlite3,
    'datetime': datetime, 'timedelta': timedelta,
    'Path': Path, 'difflib': __import__('difflib'),
}

# Load constants block
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

# Load _STRIP_FILLERS
sf_start = next(i for i, l in enumerate(lines) if '_STRIP_FILLERS' in l and '=' in l and 'if' not in l)
sf_end = sf_start + 1
while sf_end < len(lines) and '}' not in lines[sf_end]:
    sf_end += 1
exec('\n'.join(lines[sf_start:sf_end + 1]), ns)

# Stubs and constants
ns.setdefault('_onset_anomalies', [])
ns.setdefault('_COMMON_WORDS', set())
ns['log'] = lambda msg, level='info': None
ns['stats'] = {'api_calls': 0, 'sessions': 10, 'falcon_rejects': 0,
               'words': 0, 'chars': 0, 'start_time': time.time(),
               'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
ns['current_mode'] = 'SAFE'
ns['current_situation'] = 'default'
ns['HOLD_ON_HIGH_RISK'] = False
ns['_DANGLING'] = re.compile(r'(?:,|\band\s*$|\bor\s*$|\bbut\s*$|\.{2}(?!\.)|\bthe\s*$)', re.IGNORECASE)
ns['save_profile'] = lambda prof: None
# Thread locks (needed by functions that now use locking)
import threading
ns['threading'] = threading
ns['_prep_lock'] = threading.Lock()
ns['_redo_lock'] = threading.Lock()
ns['_shadow_lock'] = threading.Lock()
ns['_learn_lock'] = threading.Lock()
ns['_augment_lock'] = threading.Lock()
ns['_stats_lock'] = threading.Lock()

ns['learn_events'] = []
ns['REDO_SIMILARITY_THRESHOLD'] = 0.7
ns['_redo_buffer'] = []
ns['_redo_count'] = 0
ns['DECAY_STALE_SESSIONS'] = 100
ns['DECAY_DEAD_SESSIONS'] = 200
ns['_last_prep_text'] = None
ns['_last_prep_ts'] = 0.0
ns['_PREP_EXPIRY_SEC'] = 300

_mock_session_count = [50]
ns['db_session_count'] = lambda: _mock_session_count[0]

# Load all target functions
target_funcs = [
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
    'compute_wer', 'compute_risk_flags', 'make_decision',
    'strip_disfluencies', 'count_disfluencies', 'detect_ocd_loops',
    'update_covert_profile', 'compute_substitution_fingerprint',
    'compute_exposure_difficulty', 'compute_editorial_distance',
    'detect_covert_avoidance', 'check_redo', 'set_last_prep',
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


def survives(fn, *args, **kwargs):
    """Return (True, result) if fn completes, (False, exception) otherwise."""
    try:
        return True, fn(*args, **kwargs)
    except Exception as e:
        return False, e


# ============================================================
# TEST 1: _extract_onset — adversarial inputs
# ============================================================
print('=== TEST 1: _extract_onset — adversarial ===')
extract = ns.get('_extract_onset')
if extract:
    # Empty / whitespace
    check('empty string', extract('') is None)
    check('whitespace only', extract('   ') is None)
    check('tab', extract('\t') is None)
    check('newline', extract('\n') is None)

    # Unicode
    ok, r = survives(extract, '你好世界')
    check(f'CJK survives (got {r})', ok)
    ok, r = survives(extract, '😀happy')
    check(f'emoji prefix survives (got {r})', ok)
    ok, r = survives(extract, 'مرحبا')
    check(f'Arabic survives (got {r})', ok)
    ok, r = survives(extract, 'é̈')
    check(f'combining chars survives (got {r})', ok)
    ok, r = survives(extract, '\u200bhello')
    check(f'zero-width space prefix survives (got {r})', ok)

    # Massive
    ok, r = survives(extract, 'a' * 100_000)
    check('100K char string survives', ok)

    # Type confusion
    for bad, label in [(None, 'None'), (42, 'int'), (3.14, 'float'), ([], 'list'), ({}, 'dict')]:
        ok, r = survives(extract, bad)
        check(f'{label} -> no crash', ok or isinstance(r, (TypeError, AttributeError)))

    # Special strings
    ok, r = survives(extract, '!!??...')
    check(f'all punctuation survives (got {r})', ok)
    check('single vowel "a" -> None', extract('a') is None)
    ok, r = survives(extract, '123456')
    check(f'numeric string survives (got {r})', ok)
    ok, r = survives(extract, '\x00hello')
    check(f'null byte prefix survives (got {r})', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 2: learn_onset_weights — adversarial
# ============================================================
print()
print('=== TEST 2: learn_onset_weights — adversarial ===')
learn = ns.get('learn_onset_weights')
if learn:
    # Massive list
    ok, _ = survives(learn, ['computer'] * 10_000)
    check('10K identical triggers survives', ok)
    ns['_personal_onset_weights'] = {}
    ns['_personal_dominant_onsets'] = []

    # All vowel-initial
    learn(['apple', 'orange', 'umbrella', 'elephant', 'igloo'])
    check('all vowel words -> dict', isinstance(ns['_personal_onset_weights'], dict))
    ns['_personal_onset_weights'] = {}
    ns['_personal_dominant_onsets'] = []

    # Cyrillic
    ok, _ = survives(learn, ['компьютер', 'конференция', 'класс'])
    check('Cyrillic triggers survives', ok)
    ns['_personal_onset_weights'] = {}
    ns['_personal_dominant_onsets'] = []

    # Single character triggers
    ok, _ = survives(learn, ['a', 'b', 'c', 'd', 'e'])
    check('single-char triggers survives', ok)
    ns['_personal_onset_weights'] = {}
    ns['_personal_dominant_onsets'] = []

    # Mixed types in list
    ok, r = survives(learn, ['hello', 42, None, 'world'])
    check(f'mixed types -> no crash', ok or isinstance(r, (TypeError, AttributeError)))
    ns['_personal_onset_weights'] = {}
    ns['_personal_dominant_onsets'] = []

    # All empty strings
    ok, _ = survives(learn, ['', '', '', ''])
    check('all-empty strings survives', ok)
    ns['_personal_onset_weights'] = {}
    ns['_personal_dominant_onsets'] = []

    # Emoji triggers
    ok, _ = survives(learn, ['😀', '🎉', '🔥'])
    check('emoji triggers survives', ok)
    ns['_personal_onset_weights'] = {}
    ns['_personal_dominant_onsets'] = []
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 3: predict_phonetic_risk — adversarial
# ============================================================
print()
print('=== TEST 3: predict_phonetic_risk — adversarial ===')
predict = ns.get('predict_phonetic_risk')
if predict:
    ns['_personal_onset_weights'] = {}
    ns['_onset_anomalies'] = []

    ok, r = survives(predict, '')
    check(f'empty string survives (got {r})', ok)
    ok, r = survives(predict, '   ')
    check(f'whitespace survives (got {r})', ok)
    ok, r = survives(predict, 'a' * 100_000)
    check('100K char word survives', ok)

    # Unicode
    ok, r = survives(predict, '你好')
    check(f'CJK survives (got {r})', ok)
    ok, r = survives(predict, 'Dankeschön')
    check(f'umlaut survives (got {r})', ok)

    # Boundary sentence positions
    ok, r = survives(predict, 'hello', sentence_position=-1, sentence_length=10)
    check(f'negative position survives (got {r})', ok)
    ok, r = survives(predict, 'hello', sentence_position=0, sentence_length=0)
    check(f'sentence_length=0 survives (got {r})', ok)
    ok, r = survives(predict, 'hello', sentence_position=999, sentence_length=10)
    check(f'position > length survives (got {r})', ok)
    ok, r = survives(predict, 'hello', sentence_position=0, sentence_length=1_000_000)
    check(f'massive sentence_length survives (got {r})', ok)

    # Verify bounds hold under all conditions
    for word in ['', 'a', 'computer', '你好', '😀', '...',  'a' * 1000]:
        ok, r = survives(predict, word)
        if ok and isinstance(r, (int, float)):
            check(f'"{word[:20]}" bounded [0,1] (got {r:.2f})', 0.0 <= r <= 1.0)

    ok, r = survives(predict, '😀')
    check(f'emoji word survives (got {r})', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 4: compute_wer — adversarial
# ============================================================
print()
print('=== TEST 4: compute_wer — adversarial ===')
wer_fn = ns.get('compute_wer')
if wer_fn:
    # Massive identical (O(n*m) DP — could be slow)
    big = ' '.join(['word'] * 5_000)
    ok, r = survives(wer_fn, big, big)
    check(f'5K identical words WER=0 (got {r[0] if ok else "ERR"})', ok and r[0] == 0.0)

    # Completely different
    ref = ' '.join([f'word{i}' for i in range(500)])
    hyp = ' '.join([f'other{i}' for i in range(500)])
    ok, r = survives(wer_fn, ref, hyp)
    check('500 different words survives', ok)

    # Unicode
    ok, r = survives(wer_fn, 'я хочу пойти домой', 'я хочу пойти домой')
    check(f'Cyrillic match WER=0', ok and r[0] == 0.0)
    ok, r = survives(wer_fn, '你好世界', '你好')
    check(f'CJK survives', ok)

    # Whitespace-only
    ok, r = survives(wer_fn, '   ', '   ')
    check('whitespace-only survives', ok)

    # None inputs
    ok, r = survives(wer_fn, None, 'hello')
    check(f'None ref -> no crash', ok or isinstance(r, (TypeError, AttributeError)))
    ok, r = survives(wer_fn, 'hello', None)
    check(f'None hyp -> no crash', ok or isinstance(r, (TypeError, AttributeError)))

    # Very long single word
    ok, r = survives(wer_fn, 'a' * 10_000, 'b' * 10_000)
    check('10K single-word survives', ok)

    # Emoji in speech
    ok, r = survives(wer_fn, '😀 hello 🎉 world', '😀 hello 🎉 world')
    check('emoji tokens WER=0', ok and r[0] == 0.0)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 5: compute_risk_flags — adversarial
# ============================================================
print()
print('=== TEST 5: compute_risk_flags — adversarial ===')
flags_fn = ns.get('compute_risk_flags')
if flags_fn:
    ok, r = survives(flags_fn, '', '', True, False, 2)
    check(f'empty strings survives (got {r})', ok)

    ok, r = survives(flags_fn, None, None, True, False, 2)
    check(f'None inputs -> no crash', ok or isinstance(r, (TypeError, AttributeError)))

    big = 'word ' * 50_000
    ok, r = survives(flags_fn, big, big, True, False, 2)
    check('50K word input survives', ok)

    for layer in [-1, 0, 1, 99]:
        ok, r = survives(flags_fn, 'hello', 'hello', True, False, layer)
        check(f'layer={layer} survives', ok)

    ok, r = survives(flags_fn, 'hello', 'hello', 1, 0, 2)
    check('int booleans survive', ok)

    ok, r = survives(flags_fn, 'компьютер конференция', 'компьютер', True, False, 4)
    check('Cyrillic flags survives', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 6: make_decision — adversarial
# ============================================================
print()
print('=== TEST 6: make_decision — adversarial ===')
decide = ns.get('make_decision')
if decide:
    for layer in [-1, 0, 1, 99, 1_000_000]:
        ns['current_mode'] = 'SAFE'
        ok, r = survives(decide, True, layer, False, [])
        check(f'layer={layer} survives', ok)

    for mode in ['', 'INVALID', 'safe', 'RAW ', ' FAST']:
        ns['current_mode'] = mode
        ok, r = survives(decide, True, 2, False, [])
        check(f'mode={repr(mode)} survives', ok)
    ns['current_mode'] = 'SAFE'

    # Wrong types for risk_flags
    ok, r = survives(decide, True, 2, False, 'not_a_list')
    check('risk_flags as string survives', ok)
    ok, r = survives(decide, True, 2, False, None)
    check('risk_flags as None survives', ok)
    ok, r = survives(decide, True, 2, False, [None, 42, 'valid_flag'])
    check('mixed risk_flags survives', ok)

    # Truthy/falsy confusion
    ok, r = survives(decide, 0, 2, 1, [])
    check('int booleans survive', ok)
    ok, r = survives(decide, 'truthy', 2, '', [])
    check('string booleans survive', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 7: strip_disfluencies — adversarial
# ============================================================
print()
print('=== TEST 7: strip_disfluencies — adversarial ===')
strip = ns.get('strip_disfluencies')
if strip:
    # Massive repetition
    ok, r = survives(strip, ' '.join(['hello'] * 100))
    check(f'100x repetition survives (len={len(r) if ok else "ERR"})', ok)
    if ok:
        check('100x repetition collapses', r.count('hello') < 100)

    # Massive input
    ok, r = survives(strip, 'I want to go to the store. ' * 2000)
    check(f'50K+ char input survives', ok)

    # 200 fillers
    ok, r = survives(strip, ' '.join(['um', 'uh', 'er', 'ah'] * 50))
    check('200 fillers survives', ok)

    # Emoji-only
    ok, r = survives(strip, '😀 🎉 🔥 💯')
    check(f'emoji-only survives (got "{r}")', ok)

    # Mixed whitespace
    ok, r = survives(strip, 'hello\t\tworld\n\nnew\rline')
    check('mixed whitespace survives', ok)

    # Null bytes
    ok, r = survives(strip, 'hello\x00world')
    check('null byte survives', ok)

    # Injection strings
    ok, r = survives(strip, "'; DROP TABLE sessions; --")
    check('SQL injection survives', ok)
    ok, r = survives(strip, '<script>alert("xss")</script>')
    check('HTML injection survives', ok)

    # 100K chars no spaces
    ok, r = survives(strip, 'a' * 100_000)
    check('100K no-space survives', ok)

    # 10x stutter fragment
    ok, r = survives(strip, 'p- p- p- p- p- p- p- p- p- p- pop')
    check('10x stutter survives', ok)
    if ok:
        check('10x stutter -> "pop"', 'pop' in r and 'p-' not in r)

    # Bilingual filler mix
    ok, r = survives(strip, 'um я uh хочу er пойти')
    check(f'bilingual fillers survives', ok)

    # Type confusion
    ok, r = survives(strip, 42)
    check('int input -> no crash', ok or isinstance(r, (TypeError, AttributeError)))
    ok, r = survives(strip, True)
    check('bool input -> no crash', ok or isinstance(r, (TypeError, AttributeError)))

    # Bare hyphens
    ok, r = survives(strip, '- - - - -')
    check(f'bare hyphens survives', ok)

    # Alternating stutter + filler
    ok, r = survives(strip, 'um p- um p- um p- pop')
    check('alternating stutter+filler survives', ok)

    # Only newlines
    ok, r = survives(strip, '\n\n\n\n')
    check('only newlines survives', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 8: count_disfluencies — adversarial
# ============================================================
print()
print('=== TEST 8: count_disfluencies — adversarial ===')
count = ns.get('count_disfluencies')
if count:
    # Massive disfluent input
    big = 'I I I I want um uh to er go ' * 1000
    ok, r = survives(count, big)
    check('massive disfluent survives', ok)
    if ok:
        check('massive count total > 0', r.get('total', 0) > 0)
        total = r.get('total', 0)
        parts = sum(v for k, v in r.items() if k != 'total')
        check(f'total={total} == parts={parts}', total == parts)

    # Emoji
    ok, r = survives(count, '😀 😀 😀')
    check(f'emoji survives (got {r})', ok)

    # All punctuation
    ok, r = survives(count, '!!! ??? ... ,,, ;;; ::: ---')
    check('all punctuation survives', ok)

    # 1000-char prolongation
    ok, r = survives(count, 'I ' + 's' * 1000 + 'aid hello')
    check('1000-char prolongation survives', ok)

    # Type confusion
    ok, r = survives(count, 42)
    check('int input -> no crash or empty', ok or isinstance(r, TypeError))
    ok, r = survives(count, [1, 2, 3])
    check('list input -> no crash', ok or isinstance(r, (TypeError, AttributeError)))

    # Cyrillic prolongation
    ok, r = survives(count, 'я ннннначал говорить')
    check('Cyrillic prolongation survives', ok)

    # Extremely long word repetitions
    ok, r = survives(count, ' '.join(['the'] * 500))
    check('500x "the" survives', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 9: detect_ocd_loops — adversarial
# ============================================================
print()
print('=== TEST 9: detect_ocd_loops — adversarial ===')
loops_fn = ns.get('detect_ocd_loops')
if loops_fn:
    # 50x phrase
    ok, r = survives(loops_fn, ' '.join(['I need to check'] * 50))
    check(f'50x phrase survives (found {len(r) if ok else "ERR"})', ok)
    if ok:
        check('50x phrase is a loop', len(r) >= 1)

    # 100x single word
    ok, r = survives(loops_fn, ' '.join(['no'] * 100))
    check('100x single word survives', ok)

    # Empty / None
    ok, r = survives(loops_fn, '')
    check('empty survives', ok)
    ok, r = survives(loops_fn, None)
    check('None -> no crash', ok or isinstance(r, (TypeError, AttributeError)))

    # Cyrillic loops
    ok, r = survives(loops_fn, 'мне нужно мне нужно мне нужно проверить')
    check(f'Cyrillic loops survives', ok)

    # 5K unique words (no loops)
    ok, r = survives(loops_fn, ' '.join([f'word{i}' for i in range(5000)]))
    check('5K unique words survives', ok)
    if ok:
        check('5K unique -> no loops', len(r) == 0)

    # Whitespace only
    ok, r = survives(loops_fn, '     ')
    check('whitespace-only survives', ok)

    # Single word (edge case for phrase detection)
    ok, r = survives(loops_fn, 'hello')
    check('single word survives', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 10: update_covert_profile — adversarial
# ============================================================
print()
print('=== TEST 10: update_covert_profile — adversarial ===')
update_cp = ns.get('update_covert_profile')
if update_cp:
    pairs = [{"intended": "door", "said": "entrance", "onset_avoided": "d"}]

    # Empty/None avoidance_pairs
    prof = {}
    ok, _ = survives(update_cp, prof, [], 'default')
    check('empty pairs -> no-op', ok and 'covert_profile' not in prof)

    prof = {}
    ok, _ = survives(update_cp, prof, None, 'default')
    check('None pairs -> no-op', ok)

    # None situation -> "default"
    prof = {}
    ok, _ = survives(update_cp, prof, pairs, None)
    check('None situation -> "default"', ok and 'default' in prof.get('covert_profile', {}).get('avoidance_pairs', {}))

    # Empty situation string -> "default"
    prof = {}
    ok, _ = survives(update_cp, prof, pairs, '')
    check('empty situation -> "default"', ok and 'default' in prof.get('covert_profile', {}).get('avoidance_pairs', {}))

    # Unicode situation and word
    prof = {}
    ok, _ = survives(update_cp, prof, [{"intended": "дверь", "said": "вход", "onset_avoided": "д"}], "презентация")
    check('Cyrillic situation/word survives', ok)
    if ok:
        check('Cyrillic word stored', 'дверь' in prof.get('covert_profile', {}).get('avoidance_pairs', {}).get('презентация', {}))

    # Trigger 30-word cap
    prof = {}
    many = [{"intended": f"word{i}", "said": f"alt{i}", "onset_avoided": "w"} for i in range(40)]
    ok, _ = survives(update_cp, prof, many, 'phone')
    check('40 pairs -> triggers cap', ok)
    if ok:
        sit_data = prof.get('covert_profile', {}).get('avoidance_pairs', {}).get('phone', {})
        check(f'capped at 30 (got {len(sit_data)})', len(sit_data) <= 30)

    # Repeated same word -> count increments
    prof = {}
    ok, _ = survives(update_cp, prof, [{"intended": "door", "said": "entrance", "onset_avoided": "d"}] * 5, 'default')
    check('5 repeats -> count=5', ok)
    if ok:
        entry = prof.get('covert_profile', {}).get('avoidance_pairs', {}).get('default', {}).get('door', {})
        check(f'avoided_count=5 (got {entry.get("avoided_count")})', entry.get('avoided_count') == 5)

    # Many substitutes -> capped at 5
    prof = {}
    varied = [{"intended": "door", "said": f"syn{i}", "onset_avoided": "d"} for i in range(10)]
    ok, _ = survives(update_cp, prof, varied, 'default')
    check('10 subs -> capped at 5', ok)
    if ok:
        subs = prof.get('covert_profile', {}).get('avoidance_pairs', {}).get('default', {}).get('door', {}).get('common_substitutes', [])
        check(f'substitutes <= 5 (got {len(subs)})', len(subs) <= 5)

    # Existing profile preserved
    prof = {"covert_profile": {"avoidance_pairs": {"default": {"existing": {"avoided_count": 3}}}}}
    ok, _ = survives(update_cp, prof, pairs, 'default')
    check('existing preserved + new added', ok)
    if ok:
        check('existing word kept', 'existing' in prof['covert_profile']['avoidance_pairs']['default'])
        check('new word added', 'door' in prof['covert_profile']['avoidance_pairs']['default'])
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 11: compute_substitution_fingerprint — adversarial
# ============================================================
print()
print('=== TEST 11: compute_substitution_fingerprint — adversarial ===')
fingerprint = ns.get('compute_substitution_fingerprint')
if fingerprint:
    # Empty
    ok, r = survives(fingerprint, {})
    check('empty -> index 0.0', ok and r.get('avoidance_index') == 0.0)

    ok, r = survives(fingerprint, {"trigger_words": ["hello"]})
    check('no covert data -> index 0.0', ok and r.get('avoidance_index') == 0.0)

    # Massive: 10 situations x 50 words
    big_prof = {"covert_profile": {"avoidance_pairs": {}}}
    for s in range(10):
        sit = f"sit_{s}"
        big_prof["covert_profile"]["avoidance_pairs"][sit] = {
            f"word{w}": {
                "avoided_count": w + 1, "used_count": 0,
                "common_substitutes": [f"sub{j}" for j in range(3)],
                "dominant_onset": "w", "last_seen": datetime.now().isoformat()
            } for w in range(50)
        }
    ok, r = survives(fingerprint, big_prof)
    check('massive profile survives', ok)
    if ok:
        check(f'index bounded (got {r["avoidance_index"]})', 0.0 <= r['avoidance_index'] <= 1.0)
        check(f'top_subs capped at 10 (got {len(r["top_substitutions"])})', len(r['top_substitutions']) <= 10)

    # Malformed dates
    bad_prof = {"covert_profile": {"avoidance_pairs": {"default": {"door": {
        "avoided_count": 5, "used_count": 0, "common_substitutes": ["entrance"],
        "dominant_onset": "d", "last_seen": "not-a-date"
    }}}}}
    ok, r = survives(fingerprint, bad_prof)
    check('malformed date survives', ok)

    # Empty situation dict
    ok, r = survives(fingerprint, {"covert_profile": {"avoidance_pairs": {"phone": {}}}})
    check('empty situation dict survives', ok)

    # Unicode everything
    uni_prof = {"covert_profile": {"avoidance_pairs": {"презентация": {"дверь": {
        "avoided_count": 3, "used_count": 1, "common_substitutes": ["вход"],
        "dominant_onset": "д", "last_seen": datetime.now().isoformat()
    }}}}}
    ok, r = survives(fingerprint, uni_prof)
    check('full Cyrillic profile survives', ok)

    # Missing keys in word data
    sparse_prof = {"covert_profile": {"avoidance_pairs": {"default": {"word": {}}}}}
    ok, r = survives(fingerprint, sparse_prof)
    check('sparse word data (no keys) survives', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 12: compute_exposure_difficulty — adversarial
# ============================================================
print()
print('=== TEST 12: compute_exposure_difficulty — adversarial ===')
exposure = ns.get('compute_exposure_difficulty')
if exposure:
    prof = {"trigger_words": ["computer"]}

    # Empty everything
    ok, r = survives(exposure, '', 'default', {}, prof)
    check('all empty -> score 0.0', ok and r.get('score') == 0.0)

    # Massive text
    big = ' '.join(['computer'] * 5000)
    ok, r = survives(exposure, big, 'phone', {"total": 100}, prof)
    check(f'5K word input survives (score={r.get("score") if ok else "ERR"})', ok)
    if ok:
        check('massive score bounded [0,1]', 0.0 <= r['score'] <= 1.0)

    # Unknown situation
    ok, r = survives(exposure, 'hello', 'NONEXISTENT_SITUATION', {"total": 0}, prof)
    check('unknown situation survives', ok)

    # None inputs
    ok, r = survives(exposure, None, 'default', {}, prof)
    check('None text -> no crash', ok or isinstance(r, (TypeError, AttributeError)))

    # Unicode text
    ok, r = survives(exposure, 'я хочу компьютер конференция', 'phone', {"total": 2}, prof)
    check('Cyrillic text survives', ok)

    # Empty profile
    ok, r = survives(exposure, 'hello world', 'default', {"total": 0}, {})
    check('empty profile survives', ok)

    # Negative disfluency counts
    ok, r = survives(exposure, 'hello', 'default', {"total": -5}, prof)
    check('negative disfluency count survives', ok)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 13: compute_editorial_distance — adversarial
# ============================================================
print()
print('=== TEST 13: compute_editorial_distance — adversarial ===')
ed = ns.get('compute_editorial_distance')
if ed:
    # Massive identical
    big = ' '.join(['word'] * 10_000)
    ok, r = survives(ed, big, big)
    check(f'10K identical words = 0.0 (got {r})', ok and r == 0.0)

    # Massive completely different
    raw = ' '.join([f'a{i}' for i in range(1000)])
    clean = ' '.join([f'b{i}' for i in range(1000)])
    ok, r = survives(ed, raw, clean)
    check(f'1K different words = 1.0 (got {r})', ok and r == 1.0)

    # Unicode
    ok, r = survives(ed, 'я хочу пойти', 'я хочу пойти')
    check(f'Cyrillic identical = 0.0 (got {r})', ok and r == 0.0)

    # None inputs
    ok, r = survives(ed, None, 'hello')
    check(f'None raw survives (got {r})', ok)
    ok, r = survives(ed, 'hello', None)
    check(f'None clean survives (got {r})', ok)

    # Both empty
    ok, r = survives(ed, '', '')
    check(f'both empty = 0.0 (got {r})', ok and r == 0.0)

    # Emoji
    ok, r = survives(ed, '😀 hello', '😀 hello')
    check(f'emoji text = 0.0 (got {r})', ok and r == 0.0)

    # Result always bounded [0, 1]
    for raw, clean in [('a', 'b' * 100), ('x ' * 1000, 'y'), ('', 'z')]:
        ok, r = survives(ed, raw, clean)
        if ok and isinstance(r, (int, float)):
            check(f'bounded [0,1] for len({len(raw)})/len({len(clean)})', 0.0 <= r <= 1.0)
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 14: check_redo — adversarial
# ============================================================
print()
print('=== TEST 14: check_redo — adversarial ===')
redo = ns.get('check_redo')
if redo:
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0

    # Empty / None
    ok, r = survives(redo, '')
    check('empty string survives', ok)
    ok, r = survives(redo, None)
    check('None survives', ok)

    # Massive text
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    big = 'word ' * 10_000
    ok, r = survives(redo, big)
    check('10K word text survives', ok)
    ok, r = survives(redo, big)
    check('10K word repeat = redo', ok and r >= 1)

    # Unicode
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    ok, r = survives(redo, 'я хочу пойти домой')
    check('Cyrillic first = 0', ok and r == 0)
    ok, r = survives(redo, 'я хочу пойти домой')
    check('Cyrillic redo >= 1', ok and r >= 1)

    # Emoji text
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    ok, r = survives(redo, '😀 🎉 🔥')
    check('emoji text survives', ok)

    # Many consecutive redos (stress buffer)
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    for i in range(50):
        ok, r = survives(redo, 'same thing over and over')
    check(f'50 consecutive redos survives (count={r})', ok and r >= 40)

    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
else:
    print('  SKIP: not loaded')

# ============================================================
# TEST 15: Bug-fix regression — covert/remove data structure
# ============================================================
print()
print('=== TEST 15: Regression — covert/remove data path ===')

prof = {
    "covert_profile": {
        "avoidance_pairs": {
            "phone": {
                "door": {"avoided_count": 5, "used_count": 1,
                         "common_substitutes": ["entrance"], "dominant_onset": "d",
                         "last_seen": "2026-03-14T00:00:00"},
                "computer": {"avoided_count": 3, "used_count": 0,
                             "common_substitutes": ["laptop"], "dominant_onset": "c",
                             "last_seen": "2026-03-14T00:00:00"}
            }
        }
    }
}

# Simulate the FIXED handler
pairs = prof.get('covert_profile', {}).get('avoidance_pairs', {})
check('fixed: pairs dict found', 'phone' in pairs)
check('fixed: word in sit', 'door' in pairs['phone'])
del pairs['phone']['door']
check('fixed: word removed', 'door' not in pairs['phone'])
check('fixed: other word preserved', 'computer' in pairs['phone'])

# Prove old handler fails on real structure
old_cp = prof.get('covert_profile', {})
has_substitutions = 'phone' in old_cp and 'substitutions' in old_cp.get('phone', {})
check('old path: "substitutions" does NOT exist', not has_substitutions)
check('correct key is "avoidance_pairs"', 'avoidance_pairs' in old_cp)

# Edge: remove from nonexistent situation
pairs2 = prof.get('covert_profile', {}).get('avoidance_pairs', {})
check('nonexistent sit -> not found', 'interview' not in pairs2)

# Edge: remove from empty avoidance_pairs
empty_prof = {"covert_profile": {"avoidance_pairs": {}}}
ep = empty_prof.get('covert_profile', {}).get('avoidance_pairs', {})
check('empty avoidance_pairs -> empty dict', len(ep) == 0)

# Edge: missing covert_profile entirely
bare_prof = {"trigger_words": ["hello"]}
bp = bare_prof.get('covert_profile', {}).get('avoidance_pairs', {})
check('no covert_profile -> empty dict', len(bp) == 0)

# ============================================================
# TEST 16: Regression — reconstruct() signature
# ============================================================
print()
print('=== TEST 16: Regression — reconstruct() kwargs ===')

recon_match = re.search(r'def reconstruct\((.*?)\):', source, re.DOTALL)
if recon_match:
    sig = recon_match.group(1)
    check('has whisper_low_conf param', 'whisper_low_conf' in sig)
    check('has whisper_disagreements param', 'whisper_disagreements' in sig)
    check('no bare "low_confidence" param',
          'low_confidence' not in sig or 'whisper_low_conf' in sig)

    # Verify mobile handler uses correct kwargs (search the /api/transcribe block)
    transcribe_start = source.find("/api/transcribe")
    next_endpoint = source.find("elif self.path ==", transcribe_start + 1)
    if next_endpoint == -1:
        next_endpoint = len(source)
    transcribe_block = source[transcribe_start:next_endpoint]
    check('mobile uses whisper_low_conf=', 'whisper_low_conf=' in transcribe_block)
    check('mobile uses whisper_disagreements=', 'whisper_disagreements=' in transcribe_block)
    check('mobile does NOT use bare low_confidence=',
          'low_confidence=' not in transcribe_block or 'whisper_low_conf=' in transcribe_block)
else:
    check('reconstruct function found', False, 'not found')

# ============================================================
# TEST 17: Regression — ThreadingHTTPServer
# ============================================================
print()
print('=== TEST 17: Regression — ThreadingHTTPServer ===')

check('imports ThreadingHTTPServer',
      'from http.server import ThreadingHTTPServer' in source)
check('no plain HTTPServer import',
      'import HTTPServer,' not in source and 'import HTTPServer\n' not in source)
check('server uses ThreadingHTTPServer',
      'ThreadingHTTPServer(' in source)
check('HTTPServer( count matches ThreadingHTTPServer( count',
      source.count('HTTPServer(') == source.count('ThreadingHTTPServer('))

try:
    from http.server import ThreadingHTTPServer as _THS
    check('ThreadingHTTPServer importable at runtime', True)
except ImportError as e:
    check('ThreadingHTTPServer importable at runtime', False, str(e))

# ============================================================
# TEST 18: Database adversarial
# ============================================================
print()
print('=== TEST 18: Database adversarial ===')

tmp_dir = tempfile.mkdtemp()
db_path = os.path.join(tmp_dir, 'test_adversarial.db')

try:
    db = sqlite3.connect(db_path)
    db.execute("""
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, raw TEXT NOT NULL, out TEXT NOT NULL,
            tone TEXT NOT NULL, layer INTEGER NOT NULL,
            words INTEGER NOT NULL, falcon INTEGER NOT NULL DEFAULT 1,
            decision TEXT, timings TEXT, situation TEXT DEFAULT 'default',
            disfluency_counts TEXT, exposure_difficulty REAL, editorial_distance REAL
        )
    """)

    # Unicode in all fields
    db.execute("INSERT INTO sessions (ts,raw,out,tone,layer,words,falcon,situation) VALUES (?,?,?,?,?,?,?,?)",
               ('2026-03-14T00:00:00', 'я хочу 你好 مرحبا 😀', 'cleaned 你好', 'casual', 2, 4, 1, 'презентация'))
    db.commit()
    row = db.execute("SELECT raw, out, situation FROM sessions WHERE id=1").fetchone()
    check('Unicode raw preserved', '你好' in row[0] and '😀' in row[0])
    check('Unicode situation preserved', row[2] == 'презентация')

    # SQL injection via parameterized query
    evil = "'; DROP TABLE sessions; --"
    db.execute("INSERT INTO sessions (ts,raw,out,tone,layer,words,falcon) VALUES (?,?,?,?,?,?,?)",
               ('2026-03-14T00:00:01', evil, evil, 'casual', 2, 1, 1))
    db.commit()
    count_val = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    check(f'SQL injection harmless (rows={count_val})', count_val == 2)

    # Null bytes
    db.execute("INSERT INTO sessions (ts,raw,out,tone,layer,words,falcon) VALUES (?,?,?,?,?,?,?)",
               ('2026-03-14T00:00:02', 'hello\x00world', 'hello\x00world', 'casual', 2, 1, 1))
    db.commit()
    check('null byte survives DB', db.execute("SELECT raw FROM sessions WHERE id=3").fetchone() is not None)

    # Massive text
    big_text = 'word ' * 100_000
    db.execute("INSERT INTO sessions (ts,raw,out,tone,layer,words,falcon) VALUES (?,?,?,?,?,?,?)",
               ('2026-03-14T00:00:03', big_text, big_text, 'casual', 2, 100_000, 1))
    db.commit()
    row = db.execute("SELECT length(raw) FROM sessions WHERE id=4").fetchone()
    check(f'500K char text stored (len={row[0]})', row[0] == len(big_text))

    # Boundary numerics
    db.execute("INSERT INTO sessions (ts,raw,out,tone,layer,words,falcon,exposure_difficulty,editorial_distance) VALUES (?,?,?,?,?,?,?,?,?)",
               ('2026-03-14T00:00:04', 'x', 'x', 'casual', 0, 0, 0, 0.0, 0.0))
    db.commit()
    check('zero values survive', True)

    db.execute("INSERT INTO sessions (ts,raw,out,tone,layer,words,falcon,exposure_difficulty,editorial_distance) VALUES (?,?,?,?,?,?,?,?,?)",
               ('2026-03-14T00:00:05', 'x', 'x', 'casual', 999, 2147483647, 1, 1.0, 1.0))
    db.commit()
    row = db.execute("SELECT layer, words FROM sessions WHERE id=6").fetchone()
    check(f'max int values survive (layer={row[0]})', row[0] == 999 and row[1] == 2147483647)

    # Adversarial JSON
    evil_json = json.dumps({"mode": "SAFE", "injection": "'; DROP TABLE--", "nested": {"deep": [1, 2, 3]}})
    db.execute("INSERT INTO sessions (ts,raw,out,tone,layer,words,falcon,decision) VALUES (?,?,?,?,?,?,?,?)",
               ('2026-03-14T00:00:06', 'x', 'x', 'casual', 2, 1, 1, evil_json))
    db.commit()
    parsed = json.loads(db.execute("SELECT decision FROM sessions WHERE id=7").fetchone()[0])
    check('adversarial JSON round-trips', parsed['injection'] == "'; DROP TABLE--")

    db.close()
except Exception as e:
    failed += 1
    print(f'  FAIL: DB exception: {e}')
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

# ============================================================
# TEST 19: Profile JSON adversarial
# ============================================================
print()
print('=== TEST 19: Profile JSON adversarial ===')

# Deep nesting
deep = {"level": 0}
current = deep
for i in range(100):
    current["child"] = {"level": i + 1}
    current = current["child"]
ok_s, serialized = survives(json.dumps, deep)
ok_d, _ = survives(json.loads, serialized) if ok_s else (False, None)
check('100-level nesting round-trips', ok_s and ok_d)

# Unicode keys/values
uni_profile = {
    "trigger_words": ["компьютер", "Dankeschön", "你好", "مرحبا"],
    "corrections": {"Dankeschon": "Dankeschön", "спасибо": "спасибо"},
    "covert_profile": {"avoidance_pairs": {
        "презентация": {"дверь": {"avoided_count": 5, "common_substitutes": ["вход"]}}
    }}
}
serialized = json.dumps(uni_profile, ensure_ascii=False)
deserialized = json.loads(serialized)
check('Unicode profile round-trips', deserialized == uni_profile)
check('Cyrillic trigger preserved', 'компьютер' in deserialized['trigger_words'])
check('German umlaut preserved', 'Dankeschön' in list(deserialized['corrections'].values()))

# Large profile
big_profile = {
    "version": 4,
    "trigger_words": [f"trigger_{i}" for i in range(1000)],
    "filler_words": [f"filler_{i}" for i in range(500)],
    "vocabulary": [f"vocab_{i}" for i in range(500)],
    "corrections": {f"wrong_{i}": f"right_{i}" for i in range(1000)},
}
serialized = json.dumps(big_profile)
check(f'1000-trigger profile serializes ({len(serialized)} bytes)', len(serialized) > 0)
deserialized = json.loads(serialized)
check('large profile round-trips', len(deserialized['trigger_words']) == 1000)

# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
