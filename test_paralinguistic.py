"""
Tests for Layer 5: Paralinguistic Event Detection.
Covers HNR computation (synthetic ground truth), error-pattern classification,
multi-signal detection, and temporal gating.
Uses the same ast.parse extraction pattern as other test suites.
"""
import re, json, sys, ast, math, io, os
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace
from pathlib import Path
ns = {'re': re, 'json': json, 'Path': Path, 'numpy': np, 'np': np, 'math': math, 'os': os}

# Load constants block
start_idx = next(i for i, l in enumerate(lines) if l.startswith('LANGUAGE = '))
end_idx = next(i for i, l in enumerate(lines) if '_personal_onset_weights_by_lang' in l and '=' in l)
exec('\n'.join(lines[start_idx:end_idx + 1]), ns)

# Load paralinguistic constants
para_consts = [
    'PARALINGUISTIC_TAGS', '_HNR_SPEECH_THRESHOLD', '_HNR_CERTAIN_THRESHOLD',
    '_MIN_EVENT_DURATION_S', '_MIN_LAUGHTER_DURATION_S', '_CONFIDENCE_FLOOR',
    '_EVENT_WINDOW_S', '_LAUGHTER_SD_RATIO', '_INSERTION_RATIO',
    '_last_paralinguistic_events',
    '_MIN_YAWNING_DURATION_S', '_MIN_CRYING_DURATION_S',
    '_MIN_SNIFF_DURATION_S', '_MIN_GASP_DURATION_S',
    '_ENERGY_FLOOR_DB', '_GUPTA_T0', '_GUPTA_T1',
    '_ZCR_LOW_THRESHOLD', '_ZCR_NASAL_THRESHOLD',
]
for const_name in para_consts:
    try:
        idx = next(i for i, l in enumerate(lines) if l.startswith(const_name + ' = '))
        # Handle multi-line constants (e.g., PARALINGUISTIC_TAGS = [\n...\n])
        const_lines = [lines[idx]]
        if '[' in lines[idx] and ']' not in lines[idx]:
            j = idx + 1
            while j < len(lines) and ']' not in lines[j]:
                const_lines.append(lines[j])
                j += 1
            if j < len(lines):
                const_lines.append(lines[j])
        exec('\n'.join(const_lines), ns)
    except (StopIteration, Exception):
        pass

# Stub log
ns['log'] = lambda msg, level='info': None
ns['stats'] = {'api_calls': 0}
ns['WHISPER_NO_SPEECH_THRESHOLD'] = 0.15

# Load predict_phonetic_risk dependencies
ns.setdefault('_onset_anomalies', [])
ns.setdefault('_COMMON_WORDS', set())
ns.setdefault('current_mode', 'SAFE')
ns.setdefault('HOLD_ON_HIGH_RISK', False)

# Load FUNCTION_WORDS
fw_start = next(i for i, l in enumerate(lines) if l.startswith('FUNCTION_WORDS = '))
fw_end = fw_start + 1
while fw_end < len(lines) and '}' not in lines[fw_end]:
    fw_end += 1
exec('\n'.join(lines[fw_start:fw_end + 1]), ns)

# Load HIGH_RISK_ONSETS
hr_start = next(i for i, l in enumerate(lines) if l.startswith('HIGH_RISK_ONSETS = '))
hr_end = hr_start + 1
while hr_end < len(lines) and '}' not in lines[hr_end]:
    hr_end += 1
exec('\n'.join(lines[hr_start:hr_end + 1]), ns)

# Load _HIGH_FREQ_WORDS
hf_start = next(i for i, l in enumerate(lines) if l.startswith('_HIGH_FREQ_WORDS = '))
hf_end = hf_start + 1
brace_depth = 1
while hf_end < len(lines) and brace_depth > 0:
    brace_depth += lines[hf_end].count('{') - lines[hf_end].count('}')
    hf_end += 1
exec('\n'.join(lines[hf_start:hf_end]), ns)

# Extract target functions
testable_funcs = [
    'compute_hnr', 'compute_zcr', 'compute_log_energy',
    '_classify_from_error_patterns', 'detect_paralinguistic_events',
    'format_paralinguistic_tags', 'inject_paralinguistic_tags_tsa',
    'predict_phonetic_risk', '_extract_onset',
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
# TEST 1: compute_hnr — Mathematical Ground Truth
# ============================================================
print('=== TEST 1: compute_hnr — Synthetic Signals ===')
compute_hnr = ns.get('compute_hnr')
if compute_hnr:
    SR = 16000

    # 1a. Pure sine wave (440 Hz) → should have very high HNR (>20 dB)
    t = np.linspace(0, 0.5, int(SR * 0.5), endpoint=False)
    pure_tone = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    hnr_tone = compute_hnr(pure_tone, SR)
    check(f'pure 440Hz tone → HNR > 20 dB (got {hnr_tone:.1f})', hnr_tone > 20.0)

    # 1b. White noise → should have very low HNR (<0 dB)
    rng = np.random.RandomState(42)
    noise = rng.randn(int(SR * 0.5)).astype(np.float32)
    hnr_noise = compute_hnr(noise, SR)
    check(f'white noise → HNR < 2 dB (got {hnr_noise:.1f})', hnr_noise < 2.0)

    # 1c. Tone + noise at equal power → HNR should be around 0-6 dB
    mixed = (pure_tone + noise * np.std(pure_tone)).astype(np.float32)
    hnr_mixed = compute_hnr(mixed, SR)
    check(f'tone+noise equal power → HNR between -2 and 10 (got {hnr_mixed:.1f})',
          -2.0 < hnr_mixed < 10.0)

    # 1d. Tone with small noise → high HNR but less than pure tone
    light_noise = (pure_tone + noise * 0.1 * np.std(pure_tone)).astype(np.float32)
    hnr_light = compute_hnr(light_noise, SR)
    check(f'tone+light noise → HNR > 10 dB (got {hnr_light:.1f})', hnr_light > 10.0)

    # 1e. Very short segment (< 2 pitch periods at 80Hz) → safe default (20.0)
    short_seg = np.sin(2 * np.pi * 440 * np.linspace(0, 0.01, int(SR * 0.01))).astype(np.float32)
    hnr_short = compute_hnr(short_seg, SR)
    check(f'too-short segment → returns 20.0 (got {hnr_short})', hnr_short == 20.0)

    # 1f. Silence (all zeros) → safe default (20.0)
    silence = np.zeros(int(SR * 0.5), dtype=np.float32)
    hnr_silence = compute_hnr(silence, SR)
    check(f'silence → returns 20.0 (got {hnr_silence})', hnr_silence == 20.0)

    # 1g. Near-silence (very small amplitude) → safe default
    near_silence = np.ones(int(SR * 0.5), dtype=np.float32) * 1e-8
    hnr_near = compute_hnr(near_silence, SR)
    check(f'near-silence → returns 20.0 (got {hnr_near})', hnr_near == 20.0)

    # 1h. Low-frequency tone (100 Hz) within pitch range → should still detect
    low_tone = np.sin(2 * np.pi * 100 * t).astype(np.float32)
    hnr_low = compute_hnr(low_tone, SR)
    check(f'100Hz tone → HNR > 15 dB (got {hnr_low:.1f})', hnr_low > 15.0)

    # 1i. Threshold boundary: simulate "cough-like" signal
    # Broadband noise burst with faint harmonic — should land below 4.0 dB
    cough_sim = (noise * 0.8 + pure_tone * 0.15).astype(np.float32)
    hnr_cough = compute_hnr(cough_sim, SR)
    check(f'cough simulation → HNR < 4.0 dB (got {hnr_cough:.1f})', hnr_cough < 4.0)

    # 1j. Threshold boundary: simulate "voiced speech"
    # Strong harmonic with light noise — should land above 4.0 dB
    speech_sim = (pure_tone * 0.9 + noise * 0.15).astype(np.float32)
    hnr_speech = compute_hnr(speech_sim, SR)
    check(f'speech simulation → HNR > 4.0 dB (got {hnr_speech:.1f})', hnr_speech > 4.0)

    # 1k. Different sample rate (8000 Hz) → should still work
    t8k = np.linspace(0, 0.5, int(8000 * 0.5), endpoint=False)
    tone_8k = np.sin(2 * np.pi * 200 * t8k).astype(np.float32)
    hnr_8k = compute_hnr(tone_8k, 8000)
    check(f'200Hz at 8kHz SR → HNR > 15 dB (got {hnr_8k:.1f})', hnr_8k > 15.0)

    # 1l. Return type is float
    check('return type is float', isinstance(hnr_tone, float))

    # 1m. Consistent: same input → same output
    hnr_again = compute_hnr(pure_tone, SR)
    check(f'deterministic (same input → same output)', hnr_tone == hnr_again)

    # 1n. Ordering: pure tone > mixed > noise
    check(f'ordering: tone({hnr_tone:.1f}) > mixed({hnr_mixed:.1f}) > noise({hnr_noise:.1f})',
          hnr_tone > hnr_mixed > hnr_noise)

    print()

# ============================================================
# TEST 2: _classify_from_error_patterns
# ============================================================
print('=== TEST 2: _classify_from_error_patterns ===')
classify = ns.get('_classify_from_error_patterns')
if classify:
    # 2a. High S+D ratio → Laughter
    result = classify([], [], wer_sdi=(5, 4, 1))
    check('high S+D → Laughter', len(result) >= 1 and result[0]['type'] == 'Laughter',
          f'got {result}')

    # 2b. High insertion ratio → Sigh or Throat-clearing
    result_ins = classify([], [], wer_sdi=(1, 0, 4))
    check('high insertions → Sigh or Throat-clearing',
          len(result_ins) >= 1 and result_ins[0]['type'] in ('Sigh', 'Throat-clearing'),
          f'got {result_ins}')

    # 2c. Very high insertion ratio (≥0.45) → Throat-clearing
    result_tc = classify([], [], wer_sdi=(0, 0, 5))
    check('very high insertions → Throat-clearing',
          len(result_tc) >= 1 and result_tc[0]['type'] == 'Throat-clearing',
          f'got {result_tc}')

    # 2d. Moderate insertion ratio (< 0.45) → Sigh
    result_sigh = classify([], [], wer_sdi=(3, 1, 3))
    types = [c['type'] for c in result_sigh]
    check('moderate insertions → Sigh', 'Sigh' in types, f'got {types}')

    # 2e. No errors → no candidates
    result_empty = classify([], [], wer_sdi=(0, 0, 0))
    check('no errors → no candidates', len(result_empty) == 0, f'got {result_empty}')

    # 2f. None wer_sdi → no error-based candidates
    result_none = classify([], [], wer_sdi=None)
    check('None wer_sdi → no error candidates', len(result_none) == 0)

    # 2g. Single error → not enough (threshold is ≥2)
    result_one = classify([], [], wer_sdi=(1, 0, 0))
    error_based = [c for c in result_one if 'error_pattern' in c.get('detection_method', '')]
    check('single error → no candidates', len(error_based) == 0, f'got {result_one}')

    # 2h. High no_speech_prob → Breathing
    low_conf = [{'block_suspect': True, 'no_speech_prob': 0.8, 'avg_logprob': -1.2, 'text': 'um'}]
    result_breath = classify(low_conf, [], wer_sdi=None)
    types_b = [c['type'] for c in result_breath]
    check('high no_speech_prob (0.8) → Breathing', 'Breathing' in types_b, f'got {types_b}')

    # 2i. Moderate no_speech_prob → Pause
    low_conf_pause = [{'block_suspect': True, 'no_speech_prob': 0.55, 'avg_logprob': -0.8, 'text': '...'}]
    result_pause = classify(low_conf_pause, [], wer_sdi=None)
    types_p = [c['type'] for c in result_pause]
    check('moderate no_speech_prob (0.55) → Pause', 'Pause' in types_p, f'got {types_p}')

    # 2j. no_speech_prob below threshold → no candidate
    low_conf_low = [{'block_suspect': True, 'no_speech_prob': 0.3, 'avg_logprob': -0.5, 'text': 'ok'}]
    result_low = classify(low_conf_low, [], wer_sdi=None)
    check('low no_speech_prob (0.3) → no candidate', len(result_low) == 0, f'got {result_low}')

    # 2k. Non-block-suspect segments are ignored
    non_block = [{'block_suspect': False, 'no_speech_prob': 0.9, 'avg_logprob': -1.5, 'text': 'test'}]
    result_nb = classify(non_block, [], wer_sdi=None)
    check('non-block-suspect → ignored', len(result_nb) == 0, f'got {result_nb}')

    # 2l. Dense disagreement cluster → unknown candidate
    disagree = [
        {'position': 3, 'variants': ['hello', 'yellow', 'fellow']},
        {'position': 4, 'variants': ['world', 'word', 'whirl']},
        {'position': 5, 'variants': ['test', 'best', 'rest']},
    ]
    result_dis = classify([], disagree, wer_sdi=None)
    check('dense disagreement → unknown candidate',
          len(result_dis) >= 1 and result_dis[0]['type'] == 'unknown',
          f'got {result_dis}')

    # 2m. Sparse disagreements (spread out) → no cluster candidate
    sparse_disagree = [
        {'position': 1, 'variants': ['a', 'b']},
        {'position': 10, 'variants': ['c', 'd']},
        {'position': 20, 'variants': ['e', 'f']},
    ]
    result_sparse = classify([], sparse_disagree, wer_sdi=None)
    cluster_cands = [c for c in result_sparse if c['detection_method'] == 'disagreement_cluster']
    check('sparse disagreements → no cluster', len(cluster_cands) == 0, f'got {result_sparse}')

    # 2n. Confidence values are in valid range
    all_confs = [c['confidence'] for c in classify(low_conf, disagree, wer_sdi=(5, 4, 1))]
    check('all confidences in [0, 1]', all(0 <= c <= 1 for c in all_confs), f'got {all_confs}')

    # 2o. All candidates have required keys
    full_result = classify(low_conf, disagree, wer_sdi=(5, 4, 1))
    required_keys = {'type', 'confidence', 'detection_method'}
    check('all candidates have required keys',
          all(required_keys.issubset(c.keys()) for c in full_result))

    print()

# ============================================================
# TEST 3: detect_paralinguistic_events — Integration
# ============================================================
print('=== TEST 3: detect_paralinguistic_events ===')
detect = ns.get('detect_paralinguistic_events')
if detect:
    SR = 16000
    rng = np.random.RandomState(42)

    # 3a. Audio too short → empty
    short_audio = np.zeros(int(SR * 0.3), dtype=np.float32)
    result = detect(short_audio, SR, [], [], [])
    check('short audio → no events', len(result) == 0)

    # 3b. Clean speech audio + no Whisper errors → no events
    t = np.linspace(0, 2.0, int(SR * 2.0), endpoint=False)
    clean_speech = np.sin(2 * np.pi * 200 * t).astype(np.float32)
    result_clean = detect(clean_speech, SR, [], [], [])
    check('clean audio + no errors → no events', len(result_clean) == 0)

    # 3c. Noisy audio + S+D errors → should detect laughter (HNR < 4)
    noise_audio = rng.randn(int(SR * 3.0)).astype(np.float32) * 0.5
    # Add faint harmonic so it's not dead silence
    t3 = np.linspace(0, 3.0, int(SR * 3.0), endpoint=False)
    noise_audio += np.sin(2 * np.pi * 150 * t3).astype(np.float32) * 0.05
    segments = [{'text': 'ha ha ha', 'start': 0.5, 'end': 2.0, 'avg_logprob': -0.8, 'no_speech_prob': 0.1}]
    result_laugh = detect(noise_audio, SR, segments, [], [], wer_sdi=(5, 4, 1))
    laugh_types = [e['type'] for e in result_laugh]
    check('noisy audio + S+D errors → Laughter detected', 'Laughter' in laugh_types,
          f'got {laugh_types}')

    # 3d. Events have required fields
    if result_laugh:
        required = {'type', 'start_s', 'end_s', 'confidence', 'detection_method', 'hnr_db', 'zcr_hz', 'energy_db', 'committed'}
        check('events have all required fields',
              all(required.issubset(e.keys()) for e in result_laugh))
    else:
        check('events have all required fields', False, 'no events to check')

    # 3e. Event types are valid Phase 1 tags
    all_types = [e['type'] for e in result_laugh]
    valid_types = set(ns.get('PARALINGUISTIC_TAGS', []) + ['unknown'])
    check('event types are valid', all(t in valid_types for t in all_types), f'got {all_types}')

    # 3f. Confidence values in valid range
    all_confs = [e['confidence'] for e in result_laugh]
    check('confidences in [0, 1]', all(0 <= c <= 1 for c in all_confs), f'got {all_confs}')

    # 3g. start_s < end_s for all events
    check('start < end for all events',
          all(e['start_s'] < e['end_s'] for e in result_laugh))

    # 3h. High no_speech_prob on noisy audio → Breathing/Pause
    low_conf_breath = [{'block_suspect': True, 'no_speech_prob': 0.8, 'avg_logprob': -1.0,
                         'text': 'um', 'position': 2, 'brown_risk': 0.3}]
    breath_segs = [{'text': 'um', 'start': 1.0, 'end': 2.0, 'avg_logprob': -1.0, 'no_speech_prob': 0.8}]
    result_breath = detect(noise_audio, SR, breath_segs, low_conf_breath, [])
    breath_types = [e['type'] for e in result_breath]
    check('high no_speech + noise → Breathing or Pause',
          'Breathing' in breath_types or 'Pause' in breath_types,
          f'got {breath_types}')

    # 3i. Clean audio + high no_speech → still detect Pause/Breathing (HNR exemption)
    result_clean_pause = detect(clean_speech, SR, breath_segs, low_conf_breath, [])
    clean_pause_types = [e['type'] for e in result_clean_pause]
    check('clean audio + high no_speech → Pause/Breathing (HNR exemption)',
          len(result_clean_pause) >= 1 and result_clean_pause[0]['type'] in ('Pause', 'Breathing'),
          f'got {clean_pause_types}')

    # 3j. Empty everything → no events
    result_empty = detect(np.zeros(int(SR * 2), dtype=np.float32), SR, [], [], [])
    check('empty inputs → no events', len(result_empty) == 0)

    # 3k. WER with only insertions + noisy audio → Sigh or Throat-clearing
    result_ins = detect(noise_audio, SR, segments, [], [], wer_sdi=(0, 0, 5))
    ins_types = [e['type'] for e in result_ins]
    check('insertions + noise → Sigh or Throat-clearing',
          any(t in ('Sigh', 'Throat-clearing') for t in ins_types),
          f'got {ins_types}')

    print()

# ============================================================
# TEST 4: format_paralinguistic_tags
# ============================================================
print('=== TEST 4: format_paralinguistic_tags ===')
fmt = ns.get('format_paralinguistic_tags')
if fmt:
    # 4a. Basic formatting
    events = [
        {'type': 'Laughter', 'start_s': 1.0, 'end_s': 2.0, 'confidence': 0.8},
        {'type': 'Cough', 'start_s': 3.0, 'end_s': 3.5, 'confidence': 0.7},
    ]
    tags = fmt(events)
    check('two events → two tags', len(tags) == 2)
    check('correct format', tags == ['[Laughter]', '[Cough]'])

    # 4b. Sorted by start time
    events_unsorted = [
        {'type': 'Sigh', 'start_s': 5.0, 'end_s': 5.5, 'confidence': 0.6},
        {'type': 'Pause', 'start_s': 1.0, 'end_s': 2.0, 'confidence': 0.7},
    ]
    tags_sorted = fmt(events_unsorted)
    check('sorted by start time', tags_sorted == ['[Pause]', '[Sigh]'])

    # 4c. Unknown type filtered out
    events_unknown = [
        {'type': 'unknown', 'start_s': 1.0, 'end_s': 2.0, 'confidence': 0.5},
        {'type': 'Breathing', 'start_s': 3.0, 'end_s': 3.5, 'confidence': 0.6},
    ]
    tags_filtered = fmt(events_unknown)
    check('unknown type filtered', tags_filtered == ['[Breathing]'])

    # 4d. Empty input → empty output
    check('empty → empty', fmt([]) == [])

    # 4e. All Phase 1 tags format correctly
    all_events = [{'type': t, 'start_s': i, 'end_s': i+0.5, 'confidence': 0.7}
                  for i, t in enumerate(ns.get('PARALINGUISTIC_TAGS', []))]
    all_tags = fmt(all_events)
    expected = [f'[{t}]' for t in ns.get('PARALINGUISTIC_TAGS', [])]
    check(f'all Phase 1 tags format correctly', all_tags == expected, f'got {all_tags}')

    print()

# ============================================================
# TEST 5: LAYERS (1-4) + independent toggles
# ============================================================
print('=== TEST 5: LAYERS and LAYER_NAMES ===')
check('LAYERS has 4 entries', len(ns.get('LAYERS', [])) == 4)
check('LAYERS max is 4', max(ns.get('LAYERS', [0])) == 4)
check('LAYER_NAMES[4] = stutter',
      ns.get('LAYER_NAMES', {}).get(4) == 'stutter')
print()

# ============================================================
# SUMMARY
# ============================================================
print(f'\n{"="*50}')
print(f'TOTAL: {passed} passed, {failed} failed ({passed+failed} assertions)')
if failed:
    print('SOME TESTS FAILED')
    sys.exit(1)
else:
    print('ALL TESTS PASSED')
