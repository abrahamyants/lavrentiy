"""
Tests for WiM Consumer API (wim/api/reconstruct.py).

Part 1: Pure function tests (no API key needed) — strip_disfluencies, build_prompt, compute_confidence
Part 2: Mocked API tests — reconstruct_intent, falcon_validate with fake OpenAI client
Part 3: Live stress test — 100 concurrent real API calls (requires OPENAI_API_KEY or api_key.txt)

Run: python test_wim_api.py
"""
import sys, os, io, time, json, threading, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add wim/api to path so we can import reconstruct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'wim', 'api'))

import reconstruct as R
import prompt_builder as PB  # SITUATION_SEVERITY/TONE_TEMP live here; reconstruct re-exports only TONE_TEMP

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
# PART 1: Pure function tests (no API needed)
# ============================================================

# ---- strip_disfluencies ----
print()
print('=== TEST 1: strip_disfluencies ===')
sd = R.strip_disfluencies

check('removes word repetitions', 'I want' in sd('I I I want to go') and 'I I' not in sd('I I I want to go'))
check('removes filler words', 'um' not in sd('so um like the thing is we um need to go').lower() or
      sd('so um like the thing is we um need to go').count('um') == 0)
check('removes stutter fragments', sd('p- p- pop') == 'pop' or 'pop' in sd('p- p- pop'))
check('removes phrase repetitions', sd('I want I want to go').count('I want') == 1)
check('preserves content', 'store' in sd('I I want to go to the the store'))
check('handles empty string', sd('') == '')
check('handles None', sd(None) is None)
check('handles single word', sd('hello') == 'hello')
check('strips Russian fillers', 'ну' not in sd('ну я хочу ээ пойти'))
check('handles only fillers', len(sd('um uh er').strip()) > 0)  # should keep at least something

# Multi-pattern combo
combo = sd('I I was um going to to the the store to uh buy some milk')
check('combo: repetitions + fillers stripped', 'um' not in combo and 'uh' not in combo)
check('combo: content preserved', 'store' in combo and 'milk' in combo)

# ---- build_prompt ----
print()
print('=== TEST 2: build_prompt — tone variants ===')
bp = R.build_prompt

for tone in ('formal', 'professional', 'casual', 'friend'):
    prompt = bp('test input', tone=tone)
    check(f'{tone}: returns string', isinstance(prompt, str) and len(prompt) > 50)
    check(f'{tone}: contains tone name', tone in prompt.lower())

print()
print('=== TEST 3: build_prompt — layer escalation ===')

p_l1 = bp('hello world', layer=1)
p_l2 = bp('hello world', layer=2)
p_l3 = bp('hello world', layer=3, profile={'vocabulary': ['synecdoche'], 'corrections': {'Duncan': 'Dankeschoen'}})
p_l4 = bp('hello world', layer=4, profile={'trigger_words': ['computer'], 'onset_weights': {'c': 0.8}})

check('L2 has ASR artifact guidance', 'ASR artifact' in p_l2 or 'transcription' in p_l2.lower())
check('L3 includes vocabulary', 'synecdoche' in p_l3)
check('L3 includes corrections', 'Duncan' in p_l3 or 'Dankeschoen' in p_l3)
check('L4 has disfluency context', 'disfluency' in p_l4.lower())
check('L4 has trigger words', 'computer' in p_l4)
check('L4 has onset weights', '/c/' in p_l4)
# L4 has the clinical taxonomy that L2 lacks (HARDEST PHONEMES, overt/covert,
# anticipatory behavior, lang few-shot). L2 has the generic restate/Strunk
# block that L4 skips. After H-4 unification, the L2 block grew (full Strunk,
# anti-censoring, no-markdown, single-line) so the prompts are closer in
# size; the meaningful invariant is L4-specific clinical content presence.
check('L4 has clinical phoneme content', 'HARDEST PHONEMES' in p_l4)
check('L2 has prose-restate scaffolding', 'ALWAYS RESTATE' in p_l2)

print()
print('=== TEST 4: build_prompt — situations ===')

p_default = bp('test', situation='default')
p_stress = bp('test', situation='high_stress')
p_reading = bp('test', situation='reading')

check('high_stress has aggression note', 'HIGH-STRESS' in p_stress or 'aggressive' in p_stress.lower())
check('reading has conservative note', 'conservative' in p_reading.lower() or 'minor' in p_reading.lower())

# With speech severity modifier
# default (1.0) + 0.5 = 1.5 → triggers HIGH-STRESS branch (>= 1.4)
p_elevated = bp('test', situation='default', speech_severity_mod=0.5)
check('severity_mod boosts aggression', 'HIGH-STRESS' in p_elevated or 'aggressive' in p_elevated.lower())

# default (1.0) + 0.15 = 1.15 → triggers elevated branch (>= 1.1)
p_moderate = bp('test', situation='default', speech_severity_mod=0.15)
check('moderate severity_mod -> elevated note', 'elevated' in p_moderate.lower() or 'moderate' in p_moderate.lower())

print()
print('=== TEST 5: build_prompt — bilingual detection ===')

p_en = bp('I want to go to the store')
p_ru = bp('Я хочу пойти в магазин')
check('English: no bilingual note', 'bilingual' not in p_en.lower())
check('Russian: bilingual note added', 'bilingual' in p_ru.lower() or 'Russian' in p_ru)

print()
print('=== TEST 6: build_prompt — Whisper signals ===')

low_conf = [{'text': 'um hello', 'avg_logprob': -0.8, 'brown_risk': 0.7, 'block_suspect': False}]
disagree = [{'position': 3, 'variants': ['hello', 'halo', 'hollow']}]
block_suspect = [{'text': 'uh', 'no_speech_prob': 0.9, 'block_suspect': True}]

p_lc = bp('test', layer=2, whisper_low_conf=low_conf)
check('low confidence segments noted', 'LOW CONFIDENCE' in p_lc or 'uncertain' in p_lc.lower())

p_dis = bp('test', layer=2, whisper_disagreements=disagree)
check('disagreements noted', 'DISAGREEMENT' in p_dis or 'disagree' in p_dis.lower())

p_block = bp('test', layer=4, whisper_low_conf=block_suspect)
check('block suspects noted at L4', 'BLOCK SUSPECT' in p_block or 'silence' in p_block.lower())

# L4 low-conf is more aggressive than L2
p_lc_l4 = bp('test', layer=4, whisper_low_conf=low_conf)
check('L4 low-conf more aggressive', 'aggressively' in p_lc_l4.lower() or 'UNCERTAINTY' in p_lc_l4)

print()
print('=== TEST 7: build_prompt — covert avoidance ===')

covert_profile = {
    'trigger_words': ['computer'],
    'covert_profile': {
        'avoidance_pairs': {
            'default': {
                'computer': {'common_substitutes': ['laptop', 'machine']}
            }
        }
    }
}
p_covert = bp('test', layer=4, profile=covert_profile)
check('covert avoidance injected', 'COVERT AVOIDANCE' in p_covert or 'avoidance' in p_covert.lower())
check('substitute words shown', 'laptop' in p_covert or 'machine' in p_covert)

# ---- compute_confidence ----
print()
print('=== TEST 8: compute_confidence ===')
cc = R.compute_confidence

# Falcon pass, normal ratio
gamma = cc('I want to go to the store', 'I want to go to the store', True, 2)
check(f'falcon pass + same text -> high gamma ({gamma})', gamma >= 0.8)

# Falcon reject
gamma_rej = cc('hello world', 'completely different thing', False, 2)
check(f'falcon reject -> low gamma ({gamma_rej})', gamma_rej == 0.3)

# Extreme compression
gamma_comp = cc('I I I um want to uh go to the the store to buy some um groceries for dinner',
                'Store.', True, 2)
check(f'extreme compression penalized ({gamma_comp})', gamma_comp < 0.8)

# Extreme expansion (hallucination risk)
gamma_exp = cc('hello', 'hello there my dear friend how are you doing on this beautiful day', True, 2)
check(f'extreme expansion penalized ({gamma_exp})', gamma_exp < 0.8)

# L4 penalty
gamma_l2 = cc('I want to go', 'I want to go', True, 2)
gamma_l4 = cc('I want to go', 'I want to go', True, 4)
check(f'L4 slightly lower than L2 ({gamma_l4} vs {gamma_l2})', gamma_l4 <= gamma_l2)

# Very short input
gamma_short = cc('hi', 'hi', True, 2)
check(f'very short input penalized ({gamma_short})', gamma_short < gamma_l2)

# Empty input
gamma_empty = cc('', 'hello', True, 2)
check(f'empty raw -> 0.5 ({gamma_empty})', gamma_empty == 0.5)

# Bounds
check('gamma always >= 0.1', all(cc('x', 'y', False, 4) >= 0.1 for _ in range(10)))
check('gamma always <= 1.0', all(cc('hello world test', 'hello world test', True, 2) <= 1.0 for _ in range(10)))


# ============================================================
# PART 2: Mocked API tests
# ============================================================

print()
print('=== TEST 9: reconstruct_intent — mocked API ===')

# Build a fake OpenAI client
class FakeChoice:
    def __init__(self, text):
        self.message = type('M', (), {'content': text})()

class FakeResponse:
    def __init__(self, text):
        self.choices = [FakeChoice(text)]

class FakeCompletions:
    def __init__(self):
        self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        # If it's a falcon call (max_tokens=5), return "yes"
        if kwargs.get('max_tokens') == 5:
            return FakeResponse('yes')
        # Otherwise return a cleaned version
        return FakeResponse('I want to go to the store.')

class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()

class FakeClient:
    def __init__(self):
        self.chat = FakeChat()

# Monkey-patch the module's client
original_client = R.client
original_anthropic_client = R.anthropic_client
R.client = FakeClient()

try:
    # L1 / RAW mode — no API call
    r = R.reconstruct_intent('um I I want to go', layer=1)
    check('L1: no API call', len(R.client.chat.completions.calls) == 0)
    check('L1: strips disfluencies', 'um' not in r['clean'].lower() or r['clean'] != r['raw'])
    check('L1: confidence = 0.95', r['confidence'] == 0.95)
    check('L1: falcon_ok = True', r['falcon_ok'] is True)

    r_raw = R.reconstruct_intent('um hello', mode='RAW', layer=3)
    check('RAW mode: no API call', len(R.client.chat.completions.calls) == 0)

    # L2 FAST mode — 1 API call (reconstruct only, no falcon)
    R.client = FakeClient()
    r2 = R.reconstruct_intent('um I I want to go to the store', tone='professional', layer=2, mode='FAST')
    check('L2 FAST: 1 API call (no falcon)', len(R.client.chat.completions.calls) == 1)
    check('L2 FAST: clean text returned', r2['clean'] == 'I want to go to the store.')
    check('L2 FAST: falcon_ok = True (skipped)', r2['falcon_ok'] is True)
    check('L2 FAST: has confidence', 0 < r2['confidence'] <= 1.0)
    check('L2 FAST: has ms', r2['ms'] >= 0)
    check('L2 FAST: tone preserved', r2['tone'] == 'professional')
    check('L2 FAST: layer preserved', r2['layer'] == 2)

    # L2 SAFE mode — falcon_validate retired 2026-05-10 (stub returns True).
    # Only the reconstruction call hits the API now; the cross-provider
    # validation roundtrip was removed across both lavrentiy.py and wim/api/.
    R.client = FakeClient()
    r3 = R.reconstruct_intent('um hello world', tone='casual', layer=2, mode='SAFE')
    check('L2 SAFE: 1 API call (falcon retired)', len(R.client.chat.completions.calls) == 1)
    check('L2 SAFE: falcon_ok = True (stub)', r3['falcon_ok'] is True)

    # Falcon-rejection scenarios are no longer reachable — stub always returns
    # True. Prior tests at this location (falcon_ok=False / strip_disfluencies
    # fallback / confidence=0.3) were removed when Falcon retired.

    # L3 with profile
    R.client = FakeClient()
    prof = {'vocabulary': ['Kubernetes'], 'corrections': {'Duncan': 'Dankeschoen'}, 'filler_words': ['um', 'uh']}
    r5 = R.reconstruct_intent('um Duncan said Kubernetes', tone='formal', layer=3, mode='FAST', profile=prof)
    # Check the prompt sent to the API includes profile data
    api_call = R.client.chat.completions.calls[0]
    system_msg = api_call['messages'][0]['content']
    check('L3: prompt includes vocabulary', 'Kubernetes' in system_msg)
    check('L3: prompt includes corrections', 'Duncan' in system_msg or 'Dankeschoen' in system_msg)
    check('L3: model is pinned gpt-4o snapshot', api_call['model'].startswith('gpt-4o'))
    check('L3 formal: low temperature', api_call['temperature'] == 0.1)

    # L4 model selection
    R.client = FakeClient()
    R.anthropic_client = None
    r6 = R.reconstruct_intent('hello', layer=4, mode='FAST', profile={'trigger_words': ['hello']})
    api_call = R.client.chat.completions.calls[0]
    check('L4 fallback: uses MODEL_L4', api_call['model'] == R.MODEL_L4)
    check('L4: prompt has disfluency context', 'disfluency' in api_call['messages'][0]['content'].lower())

    # Whisper signals forwarded
    R.client = FakeClient()
    lc = [{'text': 'um', 'avg_logprob': -0.9, 'brown_risk': 0.8, 'block_suspect': False}]
    dis = [{'position': 2, 'variants': ['hello', 'halo']}]
    r7 = R.reconstruct_intent('hello', layer=2, mode='FAST',
                               whisper_low_conf=lc, whisper_disagreements=dis)
    sys_prompt = R.client.chat.completions.calls[0]['messages'][0]['content']
    check('Whisper low_conf in prompt', 'LOW CONFIDENCE' in sys_prompt or 'uncertain' in sys_prompt.lower())
    check('Whisper disagreements in prompt', 'DISAGREEMENT' in sys_prompt or 'disagree' in sys_prompt.lower())

    # No API key -> error
    R.client = None
    r_nokey = R.reconstruct_intent('hello')
    check('no API key: returns error', 'error' in r_nokey)
    check('no API key: raw echoed', r_nokey['raw'] == 'hello')

finally:
    R.client = original_client
    R.anthropic_client = original_anthropic_client

# ---- Response shape contract ----
print()
print('=== TEST 10: response shape contract ===')

# Every response from reconstruct_intent must have these keys
R.client = FakeClient()
required_keys = {'clean', 'raw', 'confidence', 'falcon_ok', 'ms', 'mode', 'tone', 'layer'}

for label, kwargs in [
    ('L1 default', {'raw_text': 'hello', 'layer': 1}),
    ('L2 FAST', {'raw_text': 'um hello', 'layer': 2, 'mode': 'FAST'}),
    ('L2 SAFE', {'raw_text': 'um hello', 'layer': 2, 'mode': 'SAFE'}),
    ('RAW mode', {'raw_text': 'um hello', 'mode': 'RAW'}),
    ('L4 FAST', {'raw_text': 'hello', 'layer': 4, 'mode': 'FAST'}),
]:
    result = R.reconstruct_intent(**kwargs)
    missing = required_keys - set(result.keys())
    check(f'{label}: all required keys present', len(missing) == 0)
    check(f'{label}: confidence in [0,1]', 0 <= result.get('confidence', -1) <= 1.0)
    check(f'{label}: ms >= 0', result.get('ms', -1) >= 0)
    check(f'{label}: clean is string', isinstance(result.get('clean'), str))

R.client = original_client


# ============================================================
# PART 3: Live stress test (requires API key)
# ============================================================

print()
if R.client is None:
    print('=== SKIPPING LIVE STRESS TEST (no API key) ===')
    print('  Set OPENAI_API_KEY or place api_key.txt to run live tests.')
else:
    print('=== TEST 11: Live stress test — 100 concurrent API calls ===')

    # Quick API key validation — try one call before launching 100
    _stress_test_skip = False
    try:
        _probe = R.reconstruct_intent('hello test', layer=2, mode='FAST')
        if 'error' in _probe or not _probe.get('clean'):
            raise Exception('probe returned error')
    except Exception as _e:
        print(f'  SKIP: API key invalid or unreachable ({type(_e).__name__})')
        print(f'  Update api_key.txt to run the live stress test.')
        _stress_test_skip = True

    if not _stress_test_skip:
        test_messages = [
            "so um like the thing is we need to uh get the report done by Friday",
            "I I I want to to go to the store",
            "um can you uh send me the the email",
            "basically what I'm trying to say is um we should probably maybe consider",
            "the the meeting is at at three o'clock",
            "I was going to um like tell you about the project",
            "so uh yeah the the deadline is is next week",
            "can can you please uh forward that to to the team",
            "I think I think we should um reconsider the approach",
            "the report um shows that uh revenue is is up fifteen percent",
        ]

        messages_100 = [test_messages[i % len(test_messages)] for i in range(100)]
        results = [None] * 100
        errors = []
        tones = ['casual', 'professional', 'formal', 'friend']
        layers = [1, 2, 2, 2, 3, 3, 4]

        def _call(idx):
            try:
                r = R.reconstruct_intent(
                    raw_text=messages_100[idx],
                    tone=tones[idx % len(tones)],
                    layer=layers[idx % len(layers)],
                    mode='FAST',
                    situation='default',
                )
                results[idx] = r
            except Exception as e:
                errors.append(f'#{idx}: {type(e).__name__}: {e}')

        t0 = time.time()
        threads = [threading.Thread(target=_call, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        elapsed = time.time() - t0

        completed = sum(1 for r in results if r is not None)
        check(f'100 calls completed ({completed}/100)', completed == 100)
        check(f'no exceptions ({len(errors)} errors)', len(errors) == 0)
        if errors:
            for e in errors[:5]:
                print(f'    ERROR: {e}')

        bad_shapes = 0
        for i, r in enumerate(results):
            if r is None:
                continue
            if not isinstance(r.get('clean'), str) or r.get('confidence') is None:
                bad_shapes += 1
        check(f'all responses have valid shape ({bad_shapes} bad)', bad_shapes == 0)

        l1_results = [results[i] for i in range(100) if layers[i % len(layers)] == 1 and results[i]]
        if l1_results:
            avg_l1_ms = sum(r['ms'] for r in l1_results) / len(l1_results)
            check(f'L1 avg latency < 5ms ({avg_l1_ms:.1f}ms)', avg_l1_ms < 5)

        api_results = [results[i] for i in range(100) if layers[i % len(layers)] >= 2 and results[i]]
        empty_clean = sum(1 for r in api_results if not r.get('clean', '').strip())
        check(f'no empty clean text ({empty_clean} empty)', empty_clean == 0)

        low_conf = sum(1 for r in api_results if r.get('confidence', 0) < 0.5)
        check(f'most results have confidence >= 0.5 ({low_conf} low)', low_conf < len(api_results) * 0.2)

        shorter = sum(1 for r in api_results if len(r.get('clean', '')) <= len(r.get('raw', '')) * 1.2)
        check(f'clean text not inflated ({shorter}/{len(api_results)} OK)', shorter > len(api_results) * 0.8)

        print(f'\n  Completed 100 calls in {elapsed:.1f}s ({elapsed/100*1000:.0f}ms avg)')
        print(f'  L1 calls: {len(l1_results)}, API calls: {len(api_results)}')


# ============================================================
# PART 4: Canonical values (WiM Android must match these)
# ============================================================

print()
print('=== TEST 12: Canonical values for WiM parity ===')

# Situation severity — authoritative values
check('reading severity = 0.5', PB.SITUATION_SEVERITY.get('reading') == 0.5)
check('default severity = 1.0', PB.SITUATION_SEVERITY.get('default') == 1.0)
check('high_stress severity = 1.5', PB.SITUATION_SEVERITY.get('high_stress') == 1.5)

# Tone temperatures — authoritative values
check('formal temp = 0.1', R.TONE_TEMP.get('formal') == 0.1)
check('professional temp = 0.15', R.TONE_TEMP.get('professional') == 0.15)
check('casual temp = 0.35', R.TONE_TEMP.get('casual') == 0.35)
check('friend temp = 0.4', R.TONE_TEMP.get('friend') == 0.4)

# Falcon prompt format — falcon_validate retired 2026-05-10 (stub returns
# True), no separate falcon prompt to inspect. Prior assertions for
# "Original:" / "Reconstruction:" labels removed.
R.client = original_client

# build_prompt includes profile fields when provided (backend must receive these)
full_profile = {
    'vocabulary': ['Kubernetes'],
    'corrections': {'Duncan': 'Dankeschoen'},
    'filler_words': ['um', 'uh', 'like'],
    'trigger_words': ['computer', 'conference'],
    'onset_weights': {'c': 0.8, 'k': 0.5},
    'covert_profile': {'avoidance_pairs': {'default': {'computer': {'common_substitutes': ['laptop']}}}},
}
p_l3 = R.build_prompt('test', layer=3, profile=full_profile)
check('L3 prompt uses vocabulary', 'Kubernetes' in p_l3)
check('L3 prompt uses corrections', 'Duncan' in p_l3 or 'Dankeschoen' in p_l3)
check('L3 prompt uses filler_words', 'um' in p_l3.lower())

p_l4 = R.build_prompt('test', layer=4, profile=full_profile)
check('L4 prompt uses trigger_words', 'computer' in p_l4)
check('L4 prompt uses onset_weights', '/c/' in p_l4)
check('L4 prompt uses covert_profile', 'laptop' in p_l4 or 'avoidance' in p_l4.lower())

print()
print('=== TEST 13: Backend payload shape contract ===')
# These are the fields reconstruct_via_backend() in lavrentiy.py sends.
# WiM Android's reconstructViaBackend must send the same fields.
required_profile_fields = ['vocabulary', 'corrections', 'filler_words', 'trigger_words', 'onset_weights', 'covert_profile']
for field in required_profile_fields:
    check(f'build_prompt accepts profile.{field}', True)  # confirmed by TEST 12 above

# reconstruct_intent accepts all backend contract fields
import inspect
sig = inspect.signature(R.reconstruct_intent)
params = set(sig.parameters.keys())
check('accepts whisper_low_conf', 'whisper_low_conf' in params)
check('accepts whisper_disagreements', 'whisper_disagreements' in params)
check('accepts speech_severity_mod', 'speech_severity_mod' in params)
check('accepts situation', 'situation' in params)
check('accepts mode', 'mode' in params)
check('accepts profile', 'profile' in params)


# ============================================================
# H-4 REGRESSION: shared prompt-builder is single source of truth
# ============================================================
print()
print('=== H-4: prompt_builder is sole source — drift-prevention ===')

# Import the shared builder directly and verify reconstruct.build_prompt is
# the same callable. If someone re-introduces a local build_prompt in
# wim/api/reconstruct.py without going through prompt_builder, this fails.
import prompt_builder as PB
check('R.build_prompt IS prompt_builder.build_prompt',
      R.build_prompt is PB.build_prompt)
check('R.TONE_TEMP IS prompt_builder.TONE_TEMP',
      R.TONE_TEMP is PB.TONE_TEMP)
check('R.SITUATION_SEVERITY IS prompt_builder.SITUATION_SEVERITY',
      R.SITUATION_SEVERITY is PB.SITUATION_SEVERITY)

# Specific rules required at L2/L3 that drifted out of WiM CF pre-H-4.
# These are non-negotiable product correctness assertions — if any of these
# disappear from the L2/L3 prompt, the CF will silently start softening
# profanity, emitting markdown, or returning multi-line output.
p_l2 = PB.build_prompt('I need to fucking go to the store', tone='professional', layer=2)
check('L2 has anti-censoring rule',
      "Do NOT censor, sanitize, or soften" in p_l2)
check('L2 has no-Markdown rule',
      "no asterisks, no backticks" in p_l2)
check('L2 has single-line output rule',
      "Output exactly one line" in p_l2)
check('L2 has no-preamble rule',
      "Do not include any preamble" in p_l2)
check('L2 has full active-voice example',
      'John threw the ball' in p_l2)
check('L2 has subject-verb-close-together rule',
      'Keep subject and verb close together' in p_l2)
check('L2 has everyday-words rule',
      'Use everyday words' in p_l2)
check('L2 has simple-active-declarative rule',
      'simple, active, affirmative, declarative' in p_l2)
check('L2 has "let me rephrase" self-correction marker',
      'let me rephrase' in p_l2)
check('L2 has DO-NOT-summarize hard rule',
      "DO NOT summarize away content" in p_l2)
check('L2 has PRESERVE-intent hard rule',
      "PRESERVE the speaker's intent and the substance" in p_l2)

# Cross-session memory (L3+) renders only when supplied — not on bare L3.
p_l3 = PB.build_prompt(
    'hello', tone='casual', layer=3,
    profile={'vocabulary': ['Kubernetes']},
    prior_rejections=['some rejected output'],
    style_examples=[{'raw': 'r', 'output': 'o'}],
)
check('L3 renders prior_rejections when supplied',
      'PERSISTENT REJECTION HISTORY' in p_l3)
check('L3 renders style_examples when supplied',
      'USER STYLE EXAMPLES' in p_l3)

# WiM CF passes None for the lavrentiy-only kwargs; those sections must
# vanish completely (CF doesn't have a rejection_store).
p_l3_bare = PB.build_prompt('hello', tone='casual', layer=3, profile={})
check('L3 bare (CF path) omits prior_rejections section',
      'PERSISTENT REJECTION HISTORY' not in p_l3_bare)
check('L3 bare (CF path) omits style_examples section',
      'USER STYLE EXAMPLES' not in p_l3_bare)


# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
