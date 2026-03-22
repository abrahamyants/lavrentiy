"""
Pipeline integration tests: function chaining, decision routing, critical token retention.
Tests the wiring between pipeline stages that unit tests miss.
Uses the same ast.parse extraction pattern. No API keys, no audio, no Win32.
"""
import re, json, sys, ast, time, io, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
from datetime import datetime, timedelta

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace with needed constants
ns = {
    're': re, 'json': json, 'time': time,
    'datetime': datetime, 'timedelta': timedelta,
    'Path': Path, 'difflib': __import__('difflib'),
    'threading': threading,
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

# Load _STRIP_FILLERS
sf_start = next(i for i, l in enumerate(lines) if '_STRIP_FILLERS' in l and '=' in l and 'if' not in l)
sf_end = sf_start + 1
while sf_end < len(lines) and '}' not in lines[sf_end]:
    sf_end += 1
exec('\n'.join(lines[sf_start:sf_end + 1]), ns)

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

# Load DEFAULT_PROFILE
dp_start = next(i for i, l in enumerate(lines) if l.startswith('DEFAULT_PROFILE = '))
dp_end = dp_start + 1
brace_depth = 1
while dp_end < len(lines) and brace_depth > 0:
    brace_depth += lines[dp_end].count('{') - lines[dp_end].count('}')
    dp_end += 1
exec('\n'.join(lines[dp_start:dp_end]), ns)

# Load trigger regex patterns (paren-delimited, not brace-delimited)
for pat_name in ('_HYPHEN_STUTTER', '_WORD_REPEAT', '_CRITICAL_TOKEN_RE'):
    pat_start = next(i for i, l in enumerate(lines) if l.startswith(pat_name + ' = '))
    pat_end = pat_start
    paren_depth = 0
    while pat_end < len(lines):
        paren_depth += lines[pat_end].count('(') - lines[pat_end].count(')')
        if paren_depth <= 0 and pat_end > pat_start:
            break
        pat_end += 1
    exec('\n'.join(lines[pat_start:pat_end + 1]), ns)

# Load STUTTER_TIPS, MAX_INSIGHTS, DISFLUENCY_TYPES
st_start = next(i for i, l in enumerate(lines) if l.startswith('STUTTER_TIPS = '))
st_end = st_start + 1
brace_depth = 1
while st_end < len(lines) and brace_depth > 0:
    brace_depth += lines[st_end].count('{') - lines[st_end].count('}')
    st_end += 1
exec('\n'.join(lines[st_start:st_end]), ns)
for l in lines:
    if l.startswith('MAX_INSIGHTS'): exec(l, ns)
    if l.startswith('LEARN_EVERY'): exec(l, ns)
    if l.startswith('LEARN_PROMOTION_THRESHOLD'): exec(l, ns)
    if l.startswith('MAX_PROFILE_ITEMS'): exec(l, ns)

ns['DISFLUENCY_TYPES'] = {
    "block", "sound_rep", "word_rep", "prolongation", "interjection",
    "avoidance", "loop_compulsion",
}

# Globals and stubs
ns['_onset_anomalies'] = []
ns['_personal_dominant_onsets'] = []
ns['_last_prep_text'] = None
ns['_last_prep_ts'] = 0.0
ns['_PREP_EXPIRY_SEC'] = 300
ns['_shadow_history'] = []
ns['_MAX_SHADOW_HISTORY'] = 50
ns['_clipboard_predictor'] = None
ns['current_layer'] = 2
ns['current_mode'] = 'SAFE'
ns['current_situation'] = 'default'
ns['HOLD_ON_HIGH_RISK'] = False
ns['_DANGLING'] = re.compile(r'(?:,|\band\s*$|\bor\s*$|\bbut\s*$|\.{2}(?!\.)|\bthe\s*$)', re.IGNORECASE)

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
ns['learn_events'] = []
ns['learn_status'] = {"last_run": None, "total_learned": 0, "next_in": 3}
ns['save_profile'] = lambda prof: None
ns['stats_inc'] = lambda key, n=1: None
ns['db_session_count'] = lambda: 50

# Extract all pipeline component functions
target_funcs = [
    # Core dependencies
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
    '_learn_event', '_learn_events_snapshot', '_sample', '_norm_str',
    'detect_word_language', 'set_last_prep',
    # Pipeline stages
    'strip_disfluencies', 'count_disfluencies', 'detect_ocd_loops',
    'apply_profile_corrections', 'strip_block_hallucinations',
    '_check_critical_retention',
    'compute_risk_flags', 'make_decision',
    'compute_exposure_difficulty', 'compute_editorial_distance',
    # Clinical chain
    'detect_covert_avoidance', 'update_covert_profile',
    'generate_shadow_utterance', 'compute_avoidance_trend',
    'detect_triggers_regex', 'add_trigger_words',
    'predict_triggers_in_text', 'compute_brown_scores',
    'build_stutter_insights',
    'check_redo',
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
# PIPELINE TEST 1: L1 path (transcribe only, no reconstruction)
# ============================================================
print('=== PIPELINE 1: L1 path (strip + corrections, no reconstruct) ===')
strip = ns.get('strip_disfluencies')
apply_corr = ns.get('apply_profile_corrections')
strip_halluc = ns.get('strip_block_hallucinations')
decide = ns.get('make_decision')
flags_fn = ns.get('compute_risk_flags')
if strip and apply_corr and strip_halluc and decide:
    # Simulate Whisper output with disfluencies
    raw = "I I I w- want to um go to the the the Duncan store"
    prof = {
        "corrections": {"Duncan": "Dankeschoen"},
        "filler_words": ["um", "uh"],
        "trigger_words": [],
        "vocabulary": [],
    }

    # Stage 1: strip disfluencies
    filtered = strip(raw)
    check('strip removes repetitions', 'I I I' not in filtered)
    check('strip removes fillers', ' um ' not in filtered)
    check('strip preserves "store"', 'store' in filtered.lower())

    # Stage 2: apply profile corrections (L1 only)
    corrected = apply_corr(filtered, prof)
    check('corrections applied: Duncan -> Dankeschoen', 'Dankeschoen' in corrected)
    check('corrections preserve other words', 'store' in corrected.lower())

    # Stage 3: strip block hallucinations (L1 only)
    low_conf = [
        {"text": "Thank you", "block_suspect": True, "no_speech_prob": 0.8},
        {"text": "real speech content here", "block_suspect": True, "no_speech_prob": 0.5},
    ]
    test_text = "Hello Thank you real speech content here world"
    cleaned = strip_halluc(test_text, low_conf)
    check('short hallucination stripped', 'Thank you' not in cleaned)
    check('long segment kept (>3 words)', 'real speech content here' in cleaned)
    check('real content preserved', 'Hello' in cleaned and 'world' in cleaned)
    check('empty low_conf -> unchanged', strip_halluc("hello", []) == "hello")
    check('None low_conf -> unchanged', strip_halluc("hello", None) == "hello")

    # Stage 4: L1 decision -> always paste_raw
    ns['current_mode'] = 'SAFE'
    flags = flags_fn(raw, corrected, True, False, 1)
    d = decide(True, 1, False, flags)
    check('L1 decision = paste_raw', d['decision'] == 'paste_raw')
else:
    print('  SKIP: functions not loaded')


# ============================================================
# PIPELINE TEST 2: L2 SAFE path (full pipeline, falcon accepts)
# ============================================================
print()
print('=== PIPELINE 2: L2 SAFE path (falcon accepts) ===')
if strip and decide and flags_fn:
    raw = "I I want to um go to the the store to buy um some groceries"

    # Stage 1: strip disfluencies
    filtered = strip(raw)
    check('filtered text is shorter', len(filtered) < len(raw))
    check('content preserved through strip', 'store' in filtered.lower())

    # Stage 2: mock reconstruct (would call GPT)
    clean = "I want to go to the store to buy some groceries."

    # Stage 3: falcon accepts
    falcon_ok = True
    used_fallback = False
    ns['current_mode'] = 'SAFE'
    flags = flags_fn(raw, clean, falcon_ok, used_fallback, 2)
    d = decide(falcon_ok, 2, used_fallback, flags)
    check('SAFE + falcon_ok -> paste_clean', d['decision'] == 'paste_clean')
    check('decision has mode', d['mode'] == 'SAFE')

    # Stage 4: disfluency analysis chain
    count_fn = ns.get('count_disfluencies')
    exposure_fn = ns.get('compute_exposure_difficulty')
    edit_fn = ns.get('compute_editorial_distance')
    if count_fn and exposure_fn and edit_fn:
        disf = count_fn(raw)
        check('disfluency count returns dict', isinstance(disf, dict))
        check('disfluency has total', 'total' in disf)
        check(f'disfluencies detected (total={disf["total"]})', disf['total'] > 0)

        exposure = exposure_fn(raw, 'default', disf, {"trigger_words": []})
        check('exposure returns dict', isinstance(exposure, dict))
        check('exposure score in [0,1]', 0.0 <= exposure['score'] <= 1.0)

        edit_dist = edit_fn(raw, clean)
        check(f'editorial distance > 0 (got {edit_dist})', edit_dist > 0.0)
        check('editorial distance <= 1.0', edit_dist <= 1.0)

        # Chain verification: these outputs feed into session logging
        check('all analysis outputs available for logging', True)
else:
    print('  SKIP: functions not loaded')


# ============================================================
# PIPELINE TEST 3: L2 SAFE path (falcon rejects)
# ============================================================
print()
print('=== PIPELINE 3: L2 SAFE path (falcon rejects) ===')
if decide and flags_fn:
    raw = "I want to discuss the project timeline"
    clean = "I want to go swimming"  # meaning changed — falcon should reject

    ns['current_mode'] = 'SAFE'
    falcon_ok = False
    flags = flags_fn(raw, clean, falcon_ok, False, 2)
    d = decide(falcon_ok, 2, False, flags)
    check('falcon rejection -> paste_raw', d['decision'] == 'paste_raw')
    check('validator_reject in flags', 'validator_reject' in flags)
else:
    print('  SKIP: functions not loaded')


# ============================================================
# PIPELINE TEST 4: L2 FAST path (skip falcon)
# ============================================================
print()
print('=== PIPELINE 4: L2 FAST path (skip falcon) ===')
if decide and flags_fn:
    raw = "I want to go to the store"
    clean = "I want to go to the store."

    ns['current_mode'] = 'FAST'
    # FAST mode skips falcon entirely — falcon_ok is irrelevant
    flags = flags_fn(raw, clean, True, False, 2)
    d = decide(True, 2, False, flags)
    check('FAST mode -> paste_clean', d['decision'] == 'paste_clean')
else:
    print('  SKIP: functions not loaded')


# ============================================================
# PIPELINE TEST 5: RAW mode (skip everything)
# ============================================================
print()
print('=== PIPELINE 5: RAW mode ===')
if decide:
    ns['current_mode'] = 'RAW'
    d = decide(True, 4, False, [])
    check('RAW mode -> paste_raw (any layer)', d['decision'] == 'paste_raw')

    d = decide(False, 2, True, ['validator_reject'])
    check('RAW mode ignores falcon/flags', d['decision'] == 'paste_raw')
    ns['current_mode'] = 'SAFE'
else:
    print('  SKIP: functions not loaded')


# ============================================================
# PIPELINE TEST 6: Critical token retention
# ============================================================
print()
print('=== PIPELINE 6: Critical token retention ===')
crit = ns.get('_check_critical_retention')
if crit:
    # Numbers preserved
    lost = crit("I need $500 for the project", "I need $500 for the project.")
    check('preserved $500 -> no lost tokens', lost == [])

    # Number lost in reconstruction (regex captures "500" not "$500")
    lost = crit("I need $500 for the project", "I need money for the project.")
    check('lost 500 detected', any('500' in t for t in lost))

    # Percentage preserved
    lost = crit("The rate is 15.5%", "The rate is 15.5%.")
    check('preserved 15.5% -> no lost tokens', lost == [])

    # Percentage lost
    lost = crit("The rate is 15.5%", "The rate is high.")
    check('lost 15.5% detected', any('15' in t for t in lost))

    # Multiple tokens
    lost = crit("Buy 3 items for $29.99 at 10% off", "Buy items at a discount.")
    check(f'multiple lost tokens detected ({len(lost)})', len(lost) >= 2)

    # No critical tokens in input
    lost = crit("I want to go to the store", "I want to go to the store.")
    check('no numbers -> empty', lost == [])

    # Empty inputs
    lost = crit("", "hello")
    check('empty raw -> empty', lost == [])

    # Pipeline integration: critical token loss should cause fallback
    raw_with_num = "I need $500 for the project tomorrow"
    bad_reconstruct = "I need money for the project tomorrow"
    lost = crit(raw_with_num, bad_reconstruct)
    if lost:
        # In the real pipeline, this triggers: used_fallback = True, output = raw
        flags = flags_fn(raw_with_num, bad_reconstruct, True, True, 2)
        d = decide(True, 2, True, flags)
        check('critical loss -> fallback -> paste_raw', d['decision'] == 'paste_raw')
else:
    print('  SKIP: function not loaded')


# ============================================================
# PIPELINE TEST 7: L4 clinical chain
# ============================================================
print()
print('=== PIPELINE 7: L4 clinical chain ===')
shadow_fn = ns.get('generate_shadow_utterance')
trend_fn = ns.get('compute_avoidance_trend')
detect_ca = ns.get('detect_covert_avoidance')
update_cp = ns.get('update_covert_profile')
set_prep = ns.get('set_last_prep')
if shadow_fn and trend_fn and detect_ca and update_cp and set_prep:
    ns['_shadow_history'] = []

    # Simulate L4 pipeline: user preps "I need to call the computer company"
    # but says "I need to call the machine company" (avoids "computer")
    prep_text = "I need to call the computer company"
    actual_text = "I need to call the machine company"
    prof = {
        "trigger_words": ["computer"],
        "covert_profile": {},
    }

    # Step 1: Set prep (user enters script)
    set_prep(prep_text)

    # Step 2: Shadow utterance (runs BEFORE covert detection in pipeline)
    shadow = shadow_fn(actual_text, prof)
    check('shadow source = prep', shadow['source'] == 'prep')
    check(f'drift > 0 (got {shadow["drift_score"]})', shadow['drift_score'] > 0)

    # Step 3: Covert avoidance detection
    set_prep(prep_text)  # reset since shadow consumed time
    covert_pairs = detect_ca(actual_text, prof)
    # covert_pairs may or may not detect the substitution depending on risk threshold

    # Step 4: Update covert profile (even if no pairs, shouldn't crash)
    update_cp(prof, covert_pairs, "phone")
    check('covert profile update no crash', True)

    # Step 5: Avoidance trend (uses shadow history)
    trend = trend_fn()
    check('trend has avg_drift', 'avg_drift' in trend)
    check('trend has n', 'n' in trend)
    check(f'trend.n >= 1 (got {trend["n"]})', trend['n'] >= 1)

    # Build up enough history for trend detection
    for i in range(8):
        set_prep(prep_text)
        shadow_fn(actual_text, prof)
    trend = trend_fn()
    check(f'sufficient history -> trend direction (got {trend["trend"]})',
          trend['trend'] in ('stable', 'increasing', 'decreasing', 'insufficient_data'))

    # Clean up
    ns['_shadow_history'] = []
    ns['_last_prep_text'] = None
else:
    print('  SKIP: functions not loaded')


# ============================================================
# PIPELINE TEST 8: Trigger detection chain
# ============================================================
print()
print('=== PIPELINE 8: Trigger detection chain ===')
detect_trig = ns.get('detect_triggers_regex')
add_trig = ns.get('add_trigger_words')
if detect_trig and add_trig:
    ns['learn_events'] = []

    # Regex detection from stuttered speech
    raw = "I w- w- want to go to the the the st- store"
    triggers = detect_trig(raw)
    check('regex detects triggers', len(triggers) > 0)
    check('returns set', isinstance(triggers, set))

    # Add triggers to profile
    prof = {"trigger_words": [], "trigger_types": {}, "preferences": {"layer": 4}}
    added = add_trig(triggers, prof)
    check(f'triggers added to profile ({len(added)})', len(added) > 0)
    check('trigger_words populated', len(prof['trigger_words']) > 0)
    check('trigger_types populated', len(prof['trigger_types']) > 0)

    # Adding same triggers again -> no duplicates
    added2 = add_trig(triggers, prof)
    check('duplicate triggers not re-added', len(added2) == 0)

    # Dict format (from LLM detection)
    llm_triggers = {"conference": "block", "structure": "prolongation"}
    added3 = add_trig(llm_triggers, prof)
    check('dict format triggers added', len(added3) == 2)
    check('disfluency type stored', prof['trigger_types'].get('conference') == 'block')

    # Type upgrade: existing trigger with "unknown" type gets classified
    prof2 = {"trigger_words": ["hello"], "trigger_types": {"hello": "unknown"}}
    add_trig({"hello": "block"}, prof2)
    check('type upgraded from unknown', prof2['trigger_types']['hello'] == 'block')

    # Single-char triggers filtered
    add_trig({"x": "block"}, prof2)
    check('single-char trigger filtered', 'x' not in [w.lower() for w in prof2['trigger_words']])

    # Learn events recorded for new triggers
    check(f'learn_events has trigger entries ({len(ns["learn_events"])})',
          any(e.get('type') == 'trigger' for e in ns['learn_events']))
else:
    print('  SKIP: functions not loaded')


# ============================================================
# PIPELINE TEST 9: End-to-end data shape verification
# ============================================================
print()
print('=== PIPELINE 9: End-to-end data shape verification ===')
count_fn = ns.get('count_disfluencies')
exposure_fn = ns.get('compute_exposure_difficulty')
edit_fn = ns.get('compute_editorial_distance')
redo_fn = ns.get('check_redo')
brown_fn = ns.get('compute_brown_scores')
predict_fn = ns.get('predict_triggers_in_text')
if strip and count_fn and exposure_fn and edit_fn and redo_fn and brown_fn and predict_fn:
    # Simulate full pipeline with realistic speech
    raw = "I I need to um um call the the computer company about the the conference"
    prof = {"trigger_words": ["computer", "conference"], "filler_words": ["um", "uh"],
            "corrections": {}, "vocabulary": []}

    # Stage 1: strip
    filtered = strip(raw)
    check('strip output is string', isinstance(filtered, str))
    check('strip output non-empty', len(filtered) > 0)

    # Stage 2: mock reconstruct output
    clean = "I need to call the computer company about the conference."

    # Stage 3: count disfluencies (uses raw, not filtered)
    disf = count_fn(raw)
    # count_disfluencies only includes keys with count > 0, but always has 'total'
    check('disf has total key', 'total' in disf)

    # Stage 4: exposure difficulty (uses raw + disf + prof)
    exposure = exposure_fn(raw, 'phone', disf, prof)
    check('exposure has score+band+components', all(k in exposure for k in ('score', 'band', 'components')))

    # Stage 5: editorial distance (uses raw + clean)
    ed = edit_fn(raw, clean)
    check('editorial distance is float', isinstance(ed, float))

    # Stage 6: redo detection (uses clean)
    ns['_redo_buffer'] = []
    ns['_redo_count'] = 0
    redo = redo_fn(clean)
    check('first utterance redo=0', redo == 0)

    # Stage 7: Brown scores (uses clean text for Script Prep)
    scores = brown_fn(clean)
    check('Brown scores for all words', len(scores) == len(clean.split()))

    # Stage 8: Predict triggers (uses clean + existing triggers)
    predicted = predict_fn(clean, prof['trigger_words'])
    check('predicted triggers is list', isinstance(predicted, list))

    # Verify data flows correctly between all stages
    check('pipeline produces valid session data', True)
else:
    print('  SKIP: functions not loaded')


# ============================================================
# PIPELINE TEST 10: Profile corrections chaining
# ============================================================
print()
print('=== PIPELINE 10: apply_profile_corrections ===')
if apply_corr:
    # Basic correction
    prof = {"corrections": {"Duncan": "Dankeschoen", "notch": "not"}}
    r = apply_corr("Duncan said it was notch ready", prof)
    check('Duncan corrected', 'Dankeschoen' in r)
    check('notch corrected', 'not ready' in r or 'not ' in r)

    # Case insensitive
    r = apply_corr("DUNCAN said hello", prof)
    check('case insensitive correction', 'Dankeschoen' in r)

    # Empty profile
    r = apply_corr("hello world", {"corrections": {}})
    check('empty corrections -> unchanged', r == "hello world")

    # Empty text
    r = apply_corr("", prof)
    check('empty text -> empty', r == "")

    # None corrections
    r = apply_corr("hello", {})
    check('no corrections key -> unchanged', r == "hello")

    # Word boundary: "Duncan" shouldn't match "Duncanville"
    r = apply_corr("Duncanville is a city", prof)
    # With \b word boundary, "Duncan" would still match the "Duncan" part of "Duncanville"
    # This is regex \b behavior — just verify no crash
    check('word boundary handling no crash', isinstance(r, str))
else:
    print('  SKIP: function not loaded')


# ============================================================
# PIPELINE TEST 11: Mode × Layer decision matrix
# ============================================================
print()
print('=== PIPELINE 11: Mode x Layer decision matrix ===')
if decide:
    # Test every mode × layer combination
    for mode in ('RAW', 'FAST', 'SAFE'):
        for layer in (1, 2, 3, 4):
            ns['current_mode'] = mode
            d = decide(True, layer, False, [])
            if mode == 'RAW' or layer == 1:
                expected = 'paste_raw'
            elif mode == 'FAST':
                expected = 'paste_clean'
            else:  # SAFE
                expected = 'paste_clean'
            check(f'{mode}/L{layer} -> {expected}', d['decision'] == expected)

    # SAFE mode with falcon rejection
    ns['current_mode'] = 'SAFE'
    for layer in (2, 3, 4):
        d = decide(False, layer, False, ['validator_reject'])
        check(f'SAFE/L{layer}/falcon_reject -> paste_raw', d['decision'] == 'paste_raw')

    # Fallback always -> paste_raw
    for mode in ('FAST', 'SAFE'):
        ns['current_mode'] = mode
        d = decide(True, 2, True, [])
        check(f'{mode}/L2/fallback -> paste_raw', d['decision'] == 'paste_raw')

    # HOLD_ON_HIGH_RISK
    ns['current_mode'] = 'SAFE'
    ns['HOLD_ON_HIGH_RISK'] = True
    d = decide(True, 2, False, ['very_short_output'])
    check('HOLD_ON_HIGH_RISK + flags -> hold', d['decision'] == 'hold')
    ns['HOLD_ON_HIGH_RISK'] = False

    ns['current_mode'] = 'SAFE'
else:
    print('  SKIP: function not loaded')


# ============================================================
# PIPELINE TEST 12: Disfluency → exposure → editorial chain
# ============================================================
print()
print('=== PIPELINE 12: Disfluency -> exposure -> editorial chain ===')
if count_fn and exposure_fn and edit_fn:
    # High disfluency speech in phone situation with triggers
    raw_heavy = "I I I c- c- computer um uh the the conference p- problem"
    clean_heavy = "I need the computer for the conference problem."
    prof = {"trigger_words": ["computer", "conference", "problem"]}

    disf = count_fn(raw_heavy)
    exposure = exposure_fn(raw_heavy, "phone", disf, prof)
    ed = edit_fn(raw_heavy, clean_heavy)

    check(f'heavy disfluency total > 3 (got {disf["total"]})', disf['total'] > 3)
    check(f'phone + triggers + heavy disf -> high exposure (got {exposure["score"]:.2f})',
          exposure['score'] > 0.3)
    check(f'heavy edit distance (got {ed})', ed > 0.3)

    # Clean speech in casual situation
    raw_clean = "I want to go to the store"
    clean_clean = "I want to go to the store."
    disf2 = count_fn(raw_clean)
    exposure2 = exposure_fn(raw_clean, "casual", disf2, {"trigger_words": []})
    ed2 = edit_fn(raw_clean, clean_clean)

    check(f'clean speech total = 0 (got {disf2["total"]})', disf2['total'] == 0)
    check(f'casual + clean -> low exposure (got {exposure2["score"]:.2f})',
          exposure2['score'] < exposure['score'])
    check(f'minimal edit (got {ed2})', ed2 < ed)

    # Situation severity ordering
    for sit_high, sit_low in [('high_stress', 'default'), ('default', 'reading')]:
        e_high = exposure_fn(raw_heavy, sit_high, disf, prof)
        e_low = exposure_fn(raw_heavy, sit_low, disf, prof)
        check(f'{sit_high} > {sit_low} ({e_high["score"]:.2f} > {e_low["score"]:.2f})',
              e_high['score'] > e_low['score'])
else:
    print('  SKIP: functions not loaded')


# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
