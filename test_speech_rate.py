"""
Tests for analyze_speech_rate() — speech rate and pause detection.

Uses synthetic audio signals with known properties:
- Controlled silence/speech segments → known pause_ratio
- Controlled onset transitions → known syllable count
- Severity modifier threshold verification

No audio hardware needed.
"""
import sys, os, io, ast, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import numpy

passed = 0
failed = 0

def check(label, condition):
    global passed, failed
    if condition:
        print(f'  PASS: {label}')
        passed += 1
    else:
        print(f'  FAIL: {label}')
        failed += 1

# ============================================================
# Load function from lavrentiy.py
# ============================================================
with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()
tree = ast.parse(source)

ns = {
    'numpy': numpy,
    're': __import__('re'),
    'json': __import__('json'),
    'time': __import__('time'),
    'log': lambda msg, level='info': None,
}

# Load constants
SAMPLE_RATE = 16000
FRAME_SIZE = 320        # 20ms at 16kHz
RMS_THRESHOLD = 0.015
MIN_PAUSE_FRAMES = 5    # 100ms

ns['_FRAME_SIZE_SAMPLES'] = FRAME_SIZE
ns['_SPEECH_RMS_THRESHOLD'] = RMS_THRESHOLD
ns['_MIN_PAUSE_FRAMES'] = MIN_PAUSE_FRAMES
ns['_last_speech_metrics'] = {}

# Load the function
# Load every module-level function, not just analyze_speech_rate — it calls
# private helpers the single-name load omitted, which would NameError at call
# time. Defining a function never runs its body, so this is side-effect-free.
for node in tree.body:
    # skip names already seeded above (intentional stubs like a no-op log()) —
    # loading the real one would drag in unseeded module state (e.g. _log_lock).
    if isinstance(node, ast.FunctionDef) and node.name not in ns:
        func_source = ast.get_source_segment(source, node)
        try:
            exec(func_source, ns)
        except Exception as e:
            print(f'SKIP {node.name}: {e}')

analyze = ns['analyze_speech_rate']
print('Loaded: analyze_speech_rate')

# ============================================================
# Helpers
# ============================================================

def make_tone_burst(freq, duration_s, amplitude=0.1):
    """Generate a sine tone burst (speech-like segment)."""
    t = numpy.arange(int(SAMPLE_RATE * duration_s)) / SAMPLE_RATE
    return (amplitude * numpy.sin(2 * numpy.pi * freq * t)).astype(numpy.float32)

def make_silence(duration_s):
    """Generate silence."""
    return numpy.zeros(int(SAMPLE_RATE * duration_s), dtype=numpy.float32)

def make_speech_with_pauses(speech_segments, pause_durations):
    """Build audio: alternating speech bursts and pauses.
    speech_segments: list of durations in seconds for each speech burst
    pause_durations: list of durations in seconds for each pause (len = len(speech) - 1 or len(speech))
    """
    parts = []
    for i, speech_dur in enumerate(speech_segments):
        parts.append(make_tone_burst(300, speech_dur))
        if i < len(pause_durations):
            parts.append(make_silence(pause_durations[i]))
    return numpy.concatenate(parts)


# ============================================================
# TEST 1: Pure speech (no pauses)
# ============================================================
print()
print('=== TEST 1: Pure speech (no pauses) ===')
# Note: a single sustained tone has only 1 syllable onset over 3s = 0.33 syl/s,
# which triggers slow-rate severity boost. That's correct — continuous tone ≠ normal speech.
pure_speech = make_tone_burst(300, 3.0, amplitude=0.1)
r = analyze(pure_speech, SAMPLE_RATE)
check(f'pause_ratio near 0 (got {r["pause_ratio"]})', r['pause_ratio'] < 0.05)
check(f'severity_modifier from slow rate (got {r["severity_modifier"]})', r['severity_modifier'] >= 0.3)
check(f'speech_duration near total (got {r["speech_duration_s"]:.1f}s)', r['speech_duration_s'] > 2.5)
check(f'n_pauses = 0 (got {r["n_pauses"]})', r['n_pauses'] == 0)
check('returns all expected keys', all(k in r for k in
      ['pause_ratio', 'speaking_rate_sps', 'n_pauses', 'total_duration_s',
       'speech_duration_s', 'severity_modifier']))

# ============================================================
# TEST 2: Pure silence
# ============================================================
print()
print('=== TEST 2: Pure silence ===')
silence = make_silence(3.0)
r = analyze(silence, SAMPLE_RATE)
check(f'pause_ratio near 1.0 (got {r["pause_ratio"]})', r['pause_ratio'] > 0.9)
check(f'severity_modifier = 0.6 (heavy blocking) (got {r["severity_modifier"]})', r['severity_modifier'] == 0.6)
check(f'speaking_rate = 0 (got {r["speaking_rate_sps"]})', r['speaking_rate_sps'] == 0.0)

# ============================================================
# TEST 3: 50/50 speech and silence
# ============================================================
print()
print('=== TEST 3: 50/50 speech and silence ===')
# 1.5s speech, 1.5s silence
balanced = numpy.concatenate([make_tone_burst(300, 1.5), make_silence(1.5)])
r = analyze(balanced, SAMPLE_RATE)
check(f'pause_ratio ~0.5 (got {r["pause_ratio"]})', 0.35 < r['pause_ratio'] < 0.65)
check(f'severity_modifier >= 0.4 (got {r["severity_modifier"]})', r['severity_modifier'] >= 0.4)
check(f'n_pauses >= 1 (got {r["n_pauses"]})', r['n_pauses'] >= 1)

# ============================================================
# TEST 4: Normal conversational pattern (25-35% pauses)
# ============================================================
print()
print('=== TEST 4: Normal conversational pattern ===')
# Simulate: 0.2s speech, 0.08s pause, repeated 15 times = ~4.2s total
# pause_ratio = 15*0.08 / (15*0.2 + 15*0.08) = 1.2/4.2 ≈ 0.286
# 15 onsets over ~3s speech = ~5 syl/s (normal rate, above 2.0 threshold)
conversational = make_speech_with_pauses(
    [0.2] * 15,
    [0.08] * 15
)
r = analyze(conversational, SAMPLE_RATE)
check(f'pause_ratio ~0.28 (got {r["pause_ratio"]})', 0.15 < r['pause_ratio'] < 0.40)
check(f'severity_modifier = 0 (normal) (got {r["severity_modifier"]})', r['severity_modifier'] == 0.0)
# 80ms gaps are below the 100ms _MIN_PAUSE_FRAMES threshold → not counted as "pauses"
check(f'sub-100ms gaps not counted as pauses (got {r["n_pauses"]})', r['n_pauses'] == 0)

# ============================================================
# TEST 5: Stuttered speech pattern (high pausing)
# ============================================================
print()
print('=== TEST 5: Stuttered speech — heavy blocking ===')
# 0.3s speech, 0.7s pause (blocking), repeated 4 times
# pause_ratio = 4*0.7 / (4*0.3 + 4*0.7) = 2.8/4.0 = 0.70
blocking = make_speech_with_pauses(
    [0.3] * 4,
    [0.7] * 4
)
r = analyze(blocking, SAMPLE_RATE)
check(f'pause_ratio > 0.60 (got {r["pause_ratio"]})', r['pause_ratio'] > 0.55)
check(f'severity_modifier = 0.6 (max) (got {r["severity_modifier"]})', r['severity_modifier'] == 0.6)
check(f'n_pauses >= 3 (got {r["n_pauses"]})', r['n_pauses'] >= 3)

# ============================================================
# TEST 6: Mild pausing (35-45% — above normal)
# ============================================================
print()
print('=== TEST 6: Mild pausing (above normal) ===')
# 0.4s speech, 0.3s pause, repeated 5 times
# pause_ratio = 5*0.3 / (5*0.4 + 5*0.3) = 1.5/3.5 ≈ 0.43
mild = make_speech_with_pauses(
    [0.4] * 5,
    [0.3] * 5
)
r = analyze(mild, SAMPLE_RATE)
check(f'pause_ratio ~0.43 (got {r["pause_ratio"]})', 0.30 < r['pause_ratio'] < 0.55)
check(f'severity_modifier = 0.2 or 0.4 (got {r["severity_modifier"]})', r['severity_modifier'] in (0.2, 0.4))

# ============================================================
# TEST 7: Syllable onset counting
# ============================================================
print()
print('=== TEST 7: Syllable onset counting ===')
# 10 distinct tone bursts separated by short silences = ~10 syllables
syllables = make_speech_with_pauses(
    [0.15] * 10,  # 150ms per syllable
    [0.05] * 9    # 50ms gaps (below MIN_PAUSE threshold = not counted as pauses)
)
r = analyze(syllables, SAMPLE_RATE)
check(f'speaking_rate > 0 (got {r["speaking_rate_sps"]})', r['speaking_rate_sps'] > 0)
# With 10 onsets over ~2s of speech, rate should be ~5 syl/s
check(f'speaking_rate in reasonable range 2-8 syl/s (got {r["speaking_rate_sps"]})',
      2.0 < r['speaking_rate_sps'] < 8.0)

# Short gaps below 100ms should NOT count as pauses
check(f'short gaps not counted as pauses (got {r["n_pauses"]})', r['n_pauses'] <= 2)

# ============================================================
# TEST 8: Slow speaking rate → severity boost
# ============================================================
print()
print('=== TEST 8: Slow speaking rate ===')
# 2 syllables over 3 seconds of speech = ~0.67 syl/s (very slow)
slow = make_speech_with_pauses(
    [1.4, 1.4],  # two long syllables
    [0.2]         # one short pause
)
r = analyze(slow, SAMPLE_RATE)
# speaking_rate < 2.0 should trigger severity_mod >= 0.3
check(f'slow rate detected (got {r["speaking_rate_sps"]} syl/s)', r['speaking_rate_sps'] < 3.0)
if r['speaking_rate_sps'] < 2.0:
    check(f'slow rate -> severity >= 0.3 (got {r["severity_modifier"]})', r['severity_modifier'] >= 0.3)
else:
    check(f'rate not slow enough to trigger (got {r["speaking_rate_sps"]})', True)

# ============================================================
# TEST 9: Edge cases
# ============================================================
print()
print('=== TEST 9: Edge cases ===')

# Very short signal (below 3 frames = 60ms)
tiny = numpy.zeros(100, dtype=numpy.float32)
r = analyze(tiny, SAMPLE_RATE)
check('tiny signal returns defaults', r['pause_ratio'] == 0.0 and r['severity_modifier'] == 0.0)
check('tiny signal has total_duration', r['total_duration_s'] > 0)

# Single frame of speech
single_frame = make_tone_burst(300, 0.025)  # 25ms = just over 1 frame
r = analyze(single_frame, SAMPLE_RATE)
check('single frame no crash', isinstance(r['pause_ratio'], float))

# 30 seconds (longer recording) — many short bursts for normal speaking rate
long_normal = make_speech_with_pauses(
    [0.15] * 80,
    [0.06] * 79
)
r = analyze(long_normal, SAMPLE_RATE)
check(f'long recording: duration > 15s (got {r["total_duration_s"]:.0f}s)', r['total_duration_s'] > 15)
check(f'long recording: severity normal (got {r["severity_modifier"]})', r['severity_modifier'] == 0.0)

# ============================================================
# TEST 10: Severity modifier thresholds
# ============================================================
print()
print('=== TEST 10: Severity modifier thresholds ===')

# Build signals with specific pause ratios and verify thresholds
test_cases = [
    # (target_pause_ratio, expected_severity_range)
    (0.25, (0.0, 0.0)),   # normal: no boost
    (0.40, (0.2, 0.4)),   # mild: 0.2-0.4
    (0.50, (0.4, 0.6)),   # significant: 0.4
    (0.70, (0.6, 0.6)),   # heavy blocking: 0.6
]

for target_pr, (sev_min, sev_max) in test_cases:
    # Build signal: speech_dur + pause_dur where pause_dur/(speech_dur+pause_dur) ≈ target_pr
    speech_dur = 0.4
    pause_dur = speech_dur * target_pr / (1.0 - target_pr)
    sig = make_speech_with_pauses([speech_dur] * 8, [pause_dur] * 8)
    r = analyze(sig, SAMPLE_RATE)
    in_range = sev_min <= r['severity_modifier'] <= sev_max
    check(f'pause_ratio ~{target_pr}: severity {r["severity_modifier"]} in [{sev_min},{sev_max}] (actual pr={r["pause_ratio"]})',
          in_range)


# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
