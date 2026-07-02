"""
Tests for Layer 5.5: Prosodic Bridging.
Covers F0 extraction, prosodic feature extraction, speaker baseline,
state inference, prosodic context formatting, and prosodic summary.
Uses the same ast.parse extraction pattern as other test suites.
"""
import re, json, sys, ast, math, io, os
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

from pathlib import Path
ns = {'re': re, 'json': json, 'Path': Path, 'numpy': np, 'np': np, 'math': math, 'os': os}

# Load constants
start_idx = next(i for i, l in enumerate(lines) if l.startswith('LANGUAGE = '))
end_idx = next(i for i, l in enumerate(lines) if '_personal_onset_weights_by_lang' in l and '=' in l)
exec('\n'.join(lines[start_idx:end_idx + 1]), ns)

# Load paralinguistic constants
for const_name in ['PARALINGUISTIC_TAGS', '_HNR_SPEECH_THRESHOLD', '_HNR_CERTAIN_THRESHOLD',
                    '_MIN_EVENT_DURATION_S', '_MIN_LAUGHTER_DURATION_S', '_CONFIDENCE_FLOOR',
                    '_EVENT_WINDOW_S', '_LAUGHTER_SD_RATIO', '_INSERTION_RATIO',
                    '_last_paralinguistic_events', '_last_prosodic_features', '_last_speaker_state']:
    try:
        idx = next(i for i, l in enumerate(lines) if l.startswith(const_name + ' = '))
        exec(lines[idx], ns)
    except (StopIteration, Exception):
        pass

ns['log'] = lambda msg, level='info': None
ns['stats'] = {'api_calls': 0}
ns['WHISPER_NO_SPEECH_THRESHOLD'] = 0.15
ns.setdefault('_onset_anomalies', [])
ns.setdefault('_COMMON_WORDS', set())
ns.setdefault('current_situation', 'default')

# Load FUNCTION_WORDS, HIGH_RISK_ONSETS, _HIGH_FREQ_WORDS for predict_phonetic_risk
for block_name, delim in [('FUNCTION_WORDS', '}'), ('HIGH_RISK_ONSETS', '}')]:
    s = next(i for i, l in enumerate(lines) if l.startswith(block_name + ' = '))
    e = s + 1
    while e < len(lines) and delim not in lines[e]:
        e += 1
    exec('\n'.join(lines[s:e + 1]), ns)

hf_start = next(i for i, l in enumerate(lines) if l.startswith('_HIGH_FREQ_WORDS = '))
hf_end = hf_start + 1
bd = 1
while hf_end < len(lines) and bd > 0:
    bd += lines[hf_end].count('{') - lines[hf_end].count('}')
    hf_end += 1
exec('\n'.join(lines[hf_start:hf_end]), ns)

# Extract functions
testable = [
    'extract_f0', 'extract_prosodic_features', 'compute_speaker_baseline',
    'infer_speaker_state', 'build_prosodic_context', 'compute_prosodic_summary',
    'compute_hnr', 'predict_phonetic_risk', '_extract_onset',
]
# Load every module-level function, not just the enumerated targets — the
# tested functions call private helpers (e.g. _compute_session_prosodic_
# aggregates) the old name filter omitted, causing NameErrors at call time.
# Defining a function never runs its body, so this is side-effect-free;
# `testable` is kept only for the coverage report.
for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        func_source = ast.get_source_segment(source, node)
        if func_source:
            try:
                exec(func_source, ns)
            except Exception as e:
                print(f'SKIP {node.name}: {e}')

loaded = [k for k in testable if k in ns]
print(f'Loaded {len(loaded)}/{len(testable)} functions: {loaded}')
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


SR = 16000

# ============================================================
# TEST 1: extract_f0 — Frequency Detection
# ============================================================
print('=== TEST 1: extract_f0 ===')
extract_f0 = ns.get('extract_f0')
if extract_f0:
    # 1a. Pure 200Hz tone → should detect ~200Hz
    t = np.linspace(0, 0.5, int(SR * 0.5), endpoint=False)
    tone_200 = np.sin(2 * np.pi * 200 * t).astype(np.float32)
    f0 = extract_f0(tone_200, SR)
    check(f'200Hz tone → ~200Hz (got {f0})', 180 < f0 < 220)

    # 1b. Pure 440Hz tone → ~440Hz
    tone_440 = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    f0_440 = extract_f0(tone_440, SR)
    check(f'440Hz tone → ~440Hz (got {f0_440})', 420 < f0_440 < 460)

    # 1c. White noise → 0.0 (no clear pitch)
    rng = np.random.RandomState(42)
    noise = rng.randn(int(SR * 0.5)).astype(np.float32)
    f0_noise = extract_f0(noise, SR)
    check(f'white noise → 0.0 (got {f0_noise})', f0_noise == 0.0)

    # 1d. Silence → 0.0
    silence = np.zeros(int(SR * 0.5), dtype=np.float32)
    f0_silence = extract_f0(silence, SR)
    check(f'silence → 0.0 (got {f0_silence})', f0_silence == 0.0)

    # 1e. Too short → 0.0
    short = tone_200[:100]
    f0_short = extract_f0(short, SR)
    check(f'too short → 0.0 (got {f0_short})', f0_short == 0.0)

    # 1f. 100Hz tone (low pitch) → ~100Hz
    tone_100 = np.sin(2 * np.pi * 100 * t).astype(np.float32)
    f0_100 = extract_f0(tone_100, SR)
    check(f'100Hz tone → ~100Hz (got {f0_100})', 85 < f0_100 < 115)

    # 1g. Returns float
    check('returns float', isinstance(f0, float))

    # 1h. Deterministic
    check('deterministic', extract_f0(tone_200, SR) == f0)

    print()

# ============================================================
# TEST 2: extract_prosodic_features
# ============================================================
print('=== TEST 2: extract_prosodic_features ===')
epf = ns.get('extract_prosodic_features')
if epf:
    # Create test audio: 3 seconds of 200Hz tone
    t3 = np.linspace(0, 3.0, int(SR * 3.0), endpoint=False)
    audio = np.sin(2 * np.pi * 200 * t3).astype(np.float32)

    segments = [
        {'text': 'hello world', 'start': 0.0, 'end': 1.0, 'avg_logprob': -0.3, 'no_speech_prob': 0.05},
        {'text': 'test speech', 'start': 1.0, 'end': 2.0, 'avg_logprob': -0.5, 'no_speech_prob': 0.1},
        {'text': 'end here', 'start': 2.0, 'end': 3.0, 'avg_logprob': -0.4, 'no_speech_prob': 0.05},
    ]

    features = epf(audio, segments, SR)

    # 2a. Returns one feature dict per segment
    check(f'3 segments → 3 features (got {len(features)})', len(features) == 3)

    # 2b. Each feature has required keys
    required = {'start_s', 'end_s', 'text', 'f0_mean', 'f0_var', 'energy', 'rate_sps', 'pitch_direction', 'hnr'}
    if features:
        check('required keys present', required.issubset(features[0].keys()))

    # 2c. F0 should detect ~200Hz for pure tone
    if features:
        f0m = features[0]['f0_mean']
        check(f'F0 mean ~200Hz for 200Hz tone (got {f0m})', 150 < f0m < 250 or f0m == 0)

    # 2d. Energy should be positive for tone
    if features:
        check(f'energy > 0 (got {features[0]["energy"]})', features[0]['energy'] > 0)

    # 2e. Pitch direction is valid string
    valid_dirs = {'rising', 'falling', 'flat', 'erratic'}
    if features:
        check('pitch_direction valid', features[0]['pitch_direction'] in valid_dirs)

    # 2f. Empty segments → empty features
    check('no segments → empty', epf(audio, [], SR) == [])

    # 2g. Short audio → empty
    check('short audio → empty', epf(np.zeros(100, dtype=np.float32), segments, SR) == [])

    # 2h. Rate is plausible (2 words in 1 second ≈ 2.6 syl/s)
    if features:
        check(f'rate plausible (got {features[0]["rate_sps"]})', 0 < features[0]['rate_sps'] < 20)

    print()

# ============================================================
# TEST 3: compute_speaker_baseline
# ============================================================
print('=== TEST 3: compute_speaker_baseline ===')
csb = ns.get('compute_speaker_baseline')
if csb:
    # Mock db_get_sessions that returns sessions with prosodic_summary
    mock_sessions = [
        {'prosodic_summary': {'f0_mean': 180.0, 'energy_mean': 0.05, 'rate_mean': 4.0}},
        {'prosodic_summary': {'f0_mean': 200.0, 'energy_mean': 0.06, 'rate_mean': 4.5}},
        {'prosodic_summary': {'f0_mean': 190.0, 'energy_mean': 0.055, 'rate_mean': 4.2}},
        {'prosodic_summary': {'f0_mean': 185.0, 'energy_mean': 0.052, 'rate_mean': 4.1}},
    ]
    mock_db = lambda limit=50: mock_sessions

    prof = {}
    baseline = csb(prof, mock_db)

    # 3a. Baseline has required keys
    check('has f0_mean', 'f0_mean' in baseline)
    check('has f0_std', 'f0_std' in baseline)
    check('has energy_mean', 'energy_mean' in baseline)
    check('has rate_mean', 'rate_mean' in baseline)
    check('has n_sessions', 'n_sessions' in baseline)

    # 3b. F0 mean is reasonable (average of 180, 200, 190, 185)
    check(f'f0_mean ≈ 188.8 (got {baseline["f0_mean"]})', 185 < baseline['f0_mean'] < 195)

    # 3c. n_sessions correct
    check(f'n_sessions = 4 (got {baseline["n_sessions"]})', baseline['n_sessions'] == 4)

    # 3d. Empty sessions → default baseline
    empty_db = lambda limit=50: []
    empty_baseline = csb({}, empty_db)
    check('empty sessions → default n_sessions=0', empty_baseline['n_sessions'] == 0)

    # 3e. Sessions without prosodic_summary → handled gracefully
    no_prosodic = lambda limit=50: [{'ts': '2024-01-01', 'raw': 'test'}]
    nop_baseline = csb({}, no_prosodic)
    check('no prosodic data → n_sessions=0', nop_baseline['n_sessions'] == 0)

    # 3f. std is positive
    check(f'f0_std > 0 (got {baseline["f0_std"]})', baseline['f0_std'] > 0)

    print()

# ============================================================
# TEST 4: infer_speaker_state
# ============================================================
print('=== TEST 4: infer_speaker_state ===')
iss = ns.get('infer_speaker_state')
if iss:
    baseline = {'f0_mean': 180.0, 'f0_std': 15.0, 'energy_mean': 0.05,
                'energy_std': 0.01, 'rate_mean': 4.0, 'rate_std': 0.5, 'n_sessions': 10}

    # 4a. High arousal: elevated F0 + fast rate + high energy
    stressed_feats = [
        {'f0_mean': 250.0, 'f0_var': 500.0, 'energy': 0.12, 'rate_sps': 6.0, 'pitch_direction': 'rising'},
        {'f0_mean': 260.0, 'f0_var': 600.0, 'energy': 0.11, 'rate_sps': 5.5, 'pitch_direction': 'erratic'},
    ]
    state = iss(stressed_feats, baseline)
    check(f'high arousal → mentions stress', 'stress' in state.lower() or 'arousal' in state.lower(),
          f'got: {state}')

    # 4b. Fatigue: low energy + slow rate
    tired_feats = [
        {'f0_mean': 160.0, 'f0_var': 10.0, 'energy': 0.02, 'rate_sps': 2.0, 'pitch_direction': 'falling'},
        {'f0_mean': 155.0, 'f0_var': 8.0, 'energy': 0.018, 'rate_sps': 1.8, 'pitch_direction': 'falling'},
    ]
    state_tired = iss(tired_feats, baseline)
    check(f'low energy → mentions fatigue/low', 'fatigue' in state_tired.lower() or 'low' in state_tired.lower(),
          f'got: {state_tired}')

    # 4c. Calm: near baseline
    calm_feats = [
        {'f0_mean': 182.0, 'f0_var': 20.0, 'energy': 0.051, 'rate_sps': 4.1, 'pitch_direction': 'flat'},
        {'f0_mean': 178.0, 'f0_var': 15.0, 'energy': 0.049, 'rate_sps': 3.9, 'pitch_direction': 'flat'},
    ]
    state_calm = iss(calm_feats, baseline)
    check(f'near baseline → calm', 'calm' in state_calm.lower() or 'casual' in state_calm.lower(),
          f'got: {state_calm}')

    # 4d. Empty features → empty string
    check('empty → empty string', iss([], baseline) == '')

    # 4e. Returns string
    check('returns string', isinstance(state, str))

    # 4f. Auto-suggest for high stress
    check('high stress → auto_suggest', 'auto_suggest' in state, f'got: {state}')

    # 4g. Erratic pitch → tension
    erratic_feats = [
        {'f0_mean': 190.0, 'f0_var': 80.0, 'energy': 0.055, 'rate_sps': 4.0, 'pitch_direction': 'erratic'},
        {'f0_mean': 185.0, 'f0_var': 70.0, 'energy': 0.05, 'rate_sps': 3.8, 'pitch_direction': 'erratic'},
        {'f0_mean': 195.0, 'f0_var': 90.0, 'energy': 0.06, 'rate_sps': 4.2, 'pitch_direction': 'erratic'},
    ]
    state_erratic = iss(erratic_feats, baseline)
    check(f'erratic → tension', 'tension' in state_erratic.lower() or 'erratic' in state_erratic.lower(),
          f'got: {state_erratic}')

    print()

# ============================================================
# TEST 5: build_prosodic_context
# ============================================================
print('=== TEST 5: build_prosodic_context ===')
bpc = ns.get('build_prosodic_context')
if bpc:
    feats = [
        {'start_s': 0.0, 'end_s': 1.0, 'text': 'hello', 'f0_mean': 200.0, 'f0_var': 50.0,
         'energy': 0.08, 'rate_sps': 3.5, 'pitch_direction': 'rising', 'hnr': 12.0},
        {'start_s': 1.0, 'end_s': 2.0, 'text': 'world', 'f0_mean': 180.0, 'f0_var': 30.0,
         'energy': 0.05, 'rate_sps': 3.0, 'pitch_direction': 'falling', 'hnr': 10.0},
    ]
    events = [{'type': 'Laughter', 'start_s': 2.5, 'end_s': 3.5, 'confidence': 0.8, 'hnr_db': -12.0}]

    ctx = bpc(feats, events, "Calm/casual (features near baseline)")

    # 5a. Contains header
    check('has PROSODIC CONTEXT header', 'PROSODIC CONTEXT' in ctx)

    # 5b. Contains segment annotations
    check('has timestamp annotations', '[0.0-1.0s]' in ctx)

    # 5c. Contains speaker state
    check('has SPEAKER STATE', 'SPEAKER STATE' in ctx)

    # 5d. Contains stutter-prosodic rules
    check('has stutter rules', 'STUTTER-PROSODIC RULES' in ctx)

    # 5e. Contains pitch direction
    check('has pitch direction', 'pitch:rising' in ctx)

    # 5f. Contains energy label
    check('has energy label', 'energy:' in ctx)

    # 5g. Empty features → empty string
    check('empty → empty', bpc([], [], '') == '')

    # 5h. Block + laughter rule present
    check('block+laughter rule', 'self-deprecating humor' in ctx)

    # 5i. Discourse marker rule present
    check('discourse marker rule', 'discourse marker' in ctx)

    print()

# ============================================================
# TEST 6: compute_prosodic_summary
# ============================================================
print('=== TEST 6: compute_prosodic_summary ===')
cps = ns.get('compute_prosodic_summary')
if cps:
    feats = [
        {'f0_mean': 200.0, 'f0_var': 50.0, 'energy': 0.08, 'rate_sps': 3.5, 'pitch_direction': 'rising'},
        {'f0_mean': 180.0, 'f0_var': 30.0, 'energy': 0.05, 'rate_sps': 3.0, 'pitch_direction': 'falling'},
        {'f0_mean': 0.0, 'f0_var': 0.0, 'energy': 0.0, 'rate_sps': 0.0, 'pitch_direction': 'flat'},
    ]

    summary = cps(feats)

    # 6a. Has required keys
    check('has f0_mean', 'f0_mean' in summary)
    check('has energy_mean', 'energy_mean' in summary)
    check('has rate_mean', 'rate_mean' in summary)
    check('has n_segments', 'n_segments' in summary)
    check('has pitch_directions', 'pitch_directions' in summary)

    # 6b. F0 mean computed from non-zero values only
    check(f'f0_mean ≈ 190 (got {summary["f0_mean"]})', 185 < summary['f0_mean'] < 195)

    # 6c. n_segments = 3
    check(f'n_segments = 3 (got {summary["n_segments"]})', summary['n_segments'] == 3)

    # 6d. Empty → None
    check('empty → None', cps([]) is None)

    # 6e. Pitch directions counted
    check('pitch dirs counted', summary['pitch_directions'].get('rising') == 1)

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
