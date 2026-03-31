"""
Tests for multi-temperature Whisper voting and low-confidence segment extraction.
Mocks _whisper_single_call, verifies agreement/disagreement detection,
word-level alignment, and disagreement map output.
No API keys, no audio, no Win32.
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

# Globals
ns['_onset_anomalies'] = []
ns['_personal_dominant_onsets'] = []
ns['_stats_lock'] = threading.Lock()
ns['_shadow_lock'] = threading.Lock()
ns['_learn_lock'] = threading.Lock()
ns['_prep_lock'] = threading.Lock()
ns['stats'] = {'api_calls': 0, 'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
ns['WHISPER_MULTI_TEMPS'] = [0.0, 0.2, 0.4]
ns['WHISPER_NO_SPEECH_THRESHOLD'] = 0.15
ns['PATIENCE_DEFAULT'] = 2.0
ns['PATIENCE_STUTTER'] = 4.5
ns['current_layer'] = 2
ns['current_situation'] = 'default'
ns['log'] = lambda msg, level='info': None

# Extract functions
target_funcs = [
    '_extract_onset', 'predict_phonetic_risk', 'stats_inc',
    '_multi_temperature_vote', '_extract_low_confidence_segments',
    'get_patience_timeout',
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
# TEST 1: Multi-temp voting — perfect agreement
# ============================================================
print('=== TEST 1: Multi-temp voting — perfect agreement ===')
vote_fn = ns.get('_multi_temperature_vote')
if vote_fn:
    call_count = [0]
    def mock_whisper_agree(filepath, temp, prompt):
        call_count[0] += 1
        return {"text": "I want to go to the store", "segments": [{"text": "I want to go to the store", "avg_logprob": -0.2, "no_speech_prob": 0.01}]}

    ns['_whisper_single_call'] = mock_whisper_agree
    ns['stats'] = {'api_calls': 0, 'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
    r = vote_fn("fake.wav", "prompt")
    check('returns dict', isinstance(r, dict))
    check('has text', 'text' in r)
    check('has segments', 'segments' in r)
    check('has disagreements', 'disagreements' in r)
    check('has all_texts', 'all_texts' in r)
    check('text matches', r['text'] == "I want to go to the store")
    check('no disagreements', len(r['disagreements']) == 0)
    check('all_texts has 3 entries', len(r['all_texts']) == 3)
    check('all texts identical', len(set(r['all_texts'])) == 1)
    check(f'3 API calls made ({call_count[0]})', call_count[0] == 3)
    check('multi_temp_votes incremented', ns['stats']['multi_temp_votes'] == 3)
    check('no disagreement stat', ns['stats']['multi_temp_disagreements'] == 0)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 2: Multi-temp voting — word-level disagreements
# ============================================================
print()
print('=== TEST 2: Multi-temp voting — disagreements ===')
if vote_fn:
    texts = [
        "I want to go to the store",      # temp=0.0
        "I want to go to the store",      # temp=0.2 (same)
        "I want to go to a store",        # temp=0.4 (different: "the" -> "a")
    ]
    call_idx = [0]
    def mock_whisper_disagree(filepath, temp, prompt):
        idx = call_idx[0]
        call_idx[0] += 1
        return {"text": texts[idx % 3], "segments": [{"text": texts[idx % 3], "avg_logprob": -0.3, "no_speech_prob": 0.02}]}

    ns['_whisper_single_call'] = mock_whisper_disagree
    ns['stats'] = {'api_calls': 0, 'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
    r = vote_fn("fake.wav", "prompt")
    check('disagreements detected', len(r['disagreements']) > 0)
    check('primary text = temp0', r['text'] == texts[0])
    # Find the disagreement at "the" vs "a"
    dis = r['disagreements']
    positions = [d['position'] for d in dis]
    check(f'disagreement at position 5 (got {positions})', 5 in positions)
    d5 = next((d for d in dis if d['position'] == 5), None)
    if d5:
        check('variants has 3 entries', len(d5['variants']) == 3)
        check('"the" and "a" in variants', 'the' in d5['variants'] and 'a' in d5['variants'])
    check('disagreement stat incremented', ns['stats']['multi_temp_disagreements'] == 1)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 3: Multi-temp voting — different lengths
# ============================================================
print()
print('=== TEST 3: Multi-temp voting — different transcription lengths ===')
if vote_fn:
    texts = [
        "I want to go to the store please",  # 8 words
        "I want to go to the store",          # 7 words
        "I want to go",                       # 4 words
    ]
    call_idx = [0]
    def mock_whisper_difflen(filepath, temp, prompt):
        idx = call_idx[0]
        call_idx[0] += 1
        return {"text": texts[idx % 3], "segments": []}

    ns['_whisper_single_call'] = mock_whisper_difflen
    ns['stats'] = {'api_calls': 0, 'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
    r = vote_fn("fake.wav", "prompt")
    check('disagreements detected for length mismatch', len(r['disagreements']) > 0)
    # Check <END> sentinel for shorter transcriptions
    has_end = any('<END>' in d['variants'] for d in r['disagreements'])
    check('<END> sentinel used for shorter texts', has_end)
    check('primary text is temp0 (longest)', r['text'] == texts[0])
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 4: Multi-temp voting — complete disagreement
# ============================================================
print()
print('=== TEST 4: Multi-temp voting — total disagreement ===')
if vote_fn:
    texts = [
        "hello world",
        "goodbye earth",
        "foo bar",
    ]
    call_idx = [0]
    def mock_whisper_total(filepath, temp, prompt):
        idx = call_idx[0]
        call_idx[0] += 1
        return {"text": texts[idx % 3], "segments": []}

    ns['_whisper_single_call'] = mock_whisper_total
    ns['stats'] = {'api_calls': 0, 'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
    r = vote_fn("fake.wav", "prompt")
    check('all positions disagree', len(r['disagreements']) == 2)
    check('primary text still temp0', r['text'] == "hello world")
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 5: Multi-temp voting — empty transcription
# ============================================================
print()
print('=== TEST 5: Multi-temp voting — empty transcription ===')
if vote_fn:
    texts = ["", "hello world", "hello world"]
    call_idx = [0]
    def mock_whisper_empty(filepath, temp, prompt):
        idx = call_idx[0]
        call_idx[0] += 1
        return {"text": texts[idx % 3], "segments": []}

    ns['_whisper_single_call'] = mock_whisper_empty
    r = vote_fn("fake.wav", "prompt")
    check('handles empty primary', isinstance(r, dict))
    check('disagreements exist (empty vs non-empty)', len(r['disagreements']) > 0)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 6: Low-confidence segment extraction
# ============================================================
print()
print('=== TEST 6: _extract_low_confidence_segments ===')
extract_lc = ns.get('_extract_low_confidence_segments')
if extract_lc:
    # No segments -> empty
    r = extract_lc({"text": "hello", "segments": []})
    check('empty segments -> empty', r == [])

    # Confident segment -> not flagged
    r = extract_lc({"text": "hello world", "segments": [
        {"text": "hello world", "avg_logprob": -0.2, "no_speech_prob": 0.01}
    ]})
    check('confident segment not flagged', len(r) == 0)

    # Low confidence segment -> flagged
    r = extract_lc({"text": "hello world", "segments": [
        {"text": "hello world", "avg_logprob": -0.9, "no_speech_prob": 0.01}
    ]})
    check('low confidence flagged', len(r) == 1)
    if r:
        check('has text key', 'text' in r[0])
        check('has avg_logprob', 'avg_logprob' in r[0])
        check('has no_speech_prob', 'no_speech_prob' in r[0])
        check('has brown_risk', 'brown_risk' in r[0])
        check('has block_suspect', 'block_suspect' in r[0])
        check('not block_suspect (low no_speech)', r[0]['block_suspect'] == False)

    # Block suspect: high no_speech_prob
    r = extract_lc({"text": "Thank you", "segments": [
        {"text": "Thank you", "avg_logprob": -0.3, "no_speech_prob": 0.5}
    ]})
    check('high no_speech_prob flagged', len(r) == 1)
    if r:
        check('marked as block_suspect', r[0]['block_suspect'] == True)

    # Multiple segments, mixed confidence
    r = extract_lc({"text": "hello world goodbye earth", "segments": [
        {"text": "hello world", "avg_logprob": -0.2, "no_speech_prob": 0.01},
        {"text": "goodbye earth", "avg_logprob": -0.8, "no_speech_prob": 0.02},
    ]})
    check('only low-conf segment flagged', len(r) == 1)
    if r:
        check('flagged segment is "goodbye earth"', 'goodbye' in r[0]['text'].lower())

    # Brown risk boost: moderate confidence + high-risk word position
    r = extract_lc({"text": "computer conference", "segments": [
        {"text": "computer conference", "avg_logprob": -0.5, "no_speech_prob": 0.01},
    ]})
    # -0.5 is above default threshold (-0.7) but if brown_risk >= 0.5 it gets flagged
    # This depends on predict_phonetic_risk for "computer"
    check('moderate conf + high risk word handling', isinstance(r, list))

    # Empty text segments skipped
    r = extract_lc({"text": "hello", "segments": [
        {"text": "", "avg_logprob": -0.9, "no_speech_prob": 0.9},
        {"text": "hello", "avg_logprob": -0.2, "no_speech_prob": 0.01},
    ]})
    check('empty text segment skipped', all(s['text'] != '' for s in r))
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 7: Low-confidence with position tracking
# ============================================================
print()
print('=== TEST 7: Low-confidence position tracking ===')
if extract_lc:
    r = extract_lc({"text": "one two three four five six", "segments": [
        {"text": "one two three", "avg_logprob": -0.2, "no_speech_prob": 0.01},
        {"text": "four five six", "avg_logprob": -0.9, "no_speech_prob": 0.01},
    ]})
    if r:
        check('position tracks word count', r[0]['position'] == 6)
        check('brown_risk is float', isinstance(r[0]['brown_risk'], float))
        check('brown_risk in [0,1]', 0.0 <= r[0]['brown_risk'] <= 1.0)
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
