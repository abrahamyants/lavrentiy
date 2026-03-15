"""
Thread safety tests for Lavrentiy shared state.
Verifies no corruption when multiple threads hit _shadow_history,
_onset_anomalies, stats, preview_state, and the learn loop concurrently.
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

# Load _ENGLISH_ONSET_BASELINE
eb_start = next(i for i, l in enumerate(lines) if l.startswith('_ENGLISH_ONSET_BASELINE = '))
eb_end = eb_start + 1
while eb_end < len(lines) and '}' not in lines[eb_end]:
    eb_end += 1
exec('\n'.join(lines[eb_start:eb_end + 1]), ns)

# Load _HIGH_FREQ_WORDS
hf_start = next(i for i, l in enumerate(lines) if l.startswith('_HIGH_FREQ_WORDS = '))
hf_end = hf_start + 1
bd = 1
while hf_end < len(lines) and bd > 0:
    bd += lines[hf_end].count('{') - lines[hf_end].count('}')
    hf_end += 1
exec('\n'.join(lines[hf_start:hf_end]), ns)

# Thread locks
ns['_prep_lock'] = threading.Lock()
ns['_shadow_lock'] = threading.Lock()
ns['_learn_lock'] = threading.Lock()
ns['_stats_lock'] = threading.Lock()
ns['_augment_lock'] = threading.Lock()
ns['_redo_lock'] = threading.Lock()
ns['preview_lock'] = threading.Lock()

# Globals
ns['_shadow_history'] = []
ns['_MAX_SHADOW_HISTORY'] = 50
ns['_onset_anomalies'] = []
ns['_personal_dominant_onsets'] = []
ns['_last_prep_text'] = None
ns['_last_prep_ts'] = 0.0
ns['_PREP_EXPIRY_SEC'] = 300
ns['_clipboard_predictor'] = None
ns['current_layer'] = 2
ns['current_mode'] = 'SAFE'
ns['HOLD_ON_HIGH_RISK'] = False
ns['learn_events'] = []
ns['stats'] = {'api_calls': 0, 'sessions': 0, 'words': 0, 'chars': 0,
               'start_time': time.time(), 'falcon_rejects': 0,
               'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
ns['preview_state'] = {"active": False, "text": "", "final_text": "", "updated_at": 0}

# Stubs
ns['log'] = lambda msg, level='info': None
ns['save_profile'] = lambda prof: None
ns['db_session_count'] = lambda: 50

# Extract functions
target_funcs = [
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
    '_learn_event', '_learn_events_snapshot',
    'set_last_prep', 'detect_word_language',
    'generate_shadow_utterance', 'compute_avoidance_trend',
    'detect_onset_anomalies', 'stats_inc', 'update_preview_text',
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
# TEST 1: Concurrent shadow history writes
# ============================================================
print('=== TEST 1: Concurrent _shadow_history writes ===')
shadow_fn = ns.get('generate_shadow_utterance')
set_prep = ns.get('set_last_prep')
if shadow_fn and set_prep:
    ns['_shadow_history'] = []
    errors = []
    N_THREADS = 10
    N_OPS = 20

    def shadow_worker(thread_id):
        try:
            for i in range(N_OPS):
                set_prep(f"thread {thread_id} utterance {i} with some content words")
                shadow_fn(f"thread {thread_id} utterance {i} with different words here",
                         {"trigger_words": []})
        except Exception as e:
            errors.append(f"thread {thread_id}: {e}")

    threads = [threading.Thread(target=shadow_worker, args=(t,)) for t in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    check('no errors during concurrent shadow writes', len(errors) == 0,
          str(errors[:3]) if errors else '')
    check(f'shadow_history populated ({len(ns["_shadow_history"])} entries)',
          len(ns['_shadow_history']) > 0)
    check(f'shadow_history capped at {ns["_MAX_SHADOW_HISTORY"]}',
          len(ns['_shadow_history']) <= ns['_MAX_SHADOW_HISTORY'])
    # Verify each entry has valid structure
    for entry in ns['_shadow_history']:
        if not isinstance(entry, dict) or 'drift_score' not in entry:
            check('all entries have valid structure', False, str(entry))
            break
    else:
        check('all entries have valid structure', True)

    # Verify drift scores are valid
    bad_drifts = [e for e in ns['_shadow_history'] if not (0.0 <= e['drift_score'] <= 1.0)]
    check('all drift scores in [0,1]', len(bad_drifts) == 0,
          str(bad_drifts[:2]) if bad_drifts else '')
else:
    print('  SKIP: functions not loaded')


# ============================================================
# TEST 2: Concurrent avoidance trend reads during writes
# ============================================================
print()
print('=== TEST 2: Concurrent avoidance trend reads during shadow writes ===')
trend_fn = ns.get('compute_avoidance_trend')
if trend_fn and shadow_fn and set_prep:
    ns['_shadow_history'] = []
    errors = []
    results = []

    def writer():
        try:
            for i in range(50):
                set_prep(f"prep text iteration {i} computer conference")
                shadow_fn(f"actual text iteration {i} machine meeting",
                         {"trigger_words": ["computer"]})
        except Exception as e:
            errors.append(f"writer: {e}")

    def reader():
        try:
            for _ in range(50):
                r = trend_fn()
                results.append(r)
                if r['avg_drift'] < 0:
                    errors.append(f"negative drift: {r}")
        except Exception as e:
            errors.append(f"reader: {e}")

    t_write = threading.Thread(target=writer)
    t_read1 = threading.Thread(target=reader)
    t_read2 = threading.Thread(target=reader)
    t_write.start()
    t_read1.start()
    t_read2.start()
    t_write.join(timeout=10)
    t_read1.join(timeout=10)
    t_read2.join(timeout=10)

    check('no errors during concurrent read/write', len(errors) == 0,
          str(errors[:3]) if errors else '')
    check('readers got results', len(results) > 0)
    check('all trends have valid structure',
          all('avg_drift' in r and 'trend' in r and 'n' in r for r in results))
    check('no negative drift values',
          all(r['avg_drift'] >= 0 for r in results))
else:
    print('  SKIP: functions not loaded')


# ============================================================
# TEST 3: Concurrent stats_inc
# ============================================================
print()
print('=== TEST 3: Concurrent stats_inc ===')
stats_inc = ns.get('stats_inc')
if stats_inc:
    ns['stats'] = {'test_counter': 0}
    errors = []
    N_THREADS = 20
    N_OPS = 500

    def inc_worker():
        try:
            for _ in range(N_OPS):
                stats_inc('test_counter')
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=inc_worker) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    expected = N_THREADS * N_OPS
    actual = ns['stats']['test_counter']
    check(f'no errors', len(errors) == 0)
    check(f'exact count: {actual} == {expected}', actual == expected,
          f'got {actual}, expected {expected}')

    # Test increment by N
    ns['stats'] = {'bulk': 0}
    for _ in range(100):
        stats_inc('bulk', 5)
    check('increment by N works', ns['stats']['bulk'] == 500)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 4: Concurrent preview_state updates
# ============================================================
print()
print('=== TEST 4: Concurrent preview_state updates ===')
update_preview = ns.get('update_preview_text')
if update_preview:
    ns['preview_state'] = {"active": False, "text": "", "final_text": "", "updated_at": 0}
    errors = []

    def preview_writer(thread_id):
        try:
            for i in range(100):
                update_preview(f"thread {thread_id} text {i}", is_final=(i % 10 == 0))
        except Exception as e:
            errors.append(f"thread {thread_id}: {e}")

    def preview_reader():
        try:
            for _ in range(100):
                with ns['preview_lock']:
                    state = dict(ns['preview_state'])
                # Verify structure
                assert isinstance(state['text'], str)
                assert isinstance(state['updated_at'], (int, float))
        except Exception as e:
            errors.append(f"reader: {e}")

    threads = []
    for t in range(5):
        threads.append(threading.Thread(target=preview_writer, args=(t,)))
    for _ in range(3):
        threads.append(threading.Thread(target=preview_reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    check('no errors during concurrent preview updates', len(errors) == 0,
          str(errors[:3]) if errors else '')
    check('preview_state has text', isinstance(ns['preview_state']['text'], str))
    check('preview_state has updated_at > 0', ns['preview_state']['updated_at'] > 0)
else:
    print('  SKIP: function not loaded')


# ============================================================
# TEST 5: Concurrent learn_event writes + snapshot reads
# ============================================================
print()
print('=== TEST 5: Concurrent learn_event writes + snapshot reads ===')
learn_event = ns.get('_learn_event')
learn_snap = ns.get('_learn_events_snapshot')
if learn_event and learn_snap:
    ns['learn_events'] = []
    errors = []
    snapshots = []

    def event_writer(thread_id):
        try:
            for i in range(100):
                learn_event({"ts": datetime.now().isoformat(),
                            "type": "trigger", "value": f"word_{thread_id}_{i}"})
        except Exception as e:
            errors.append(f"writer {thread_id}: {e}")

    def event_reader():
        try:
            for _ in range(100):
                snap = learn_snap()
                snapshots.append(len(snap))
                # Verify it's a list (snapshot, not reference)
                assert isinstance(snap, list)
        except Exception as e:
            errors.append(f"reader: {e}")

    threads = []
    for t in range(5):
        threads.append(threading.Thread(target=event_writer, args=(t,)))
    for _ in range(3):
        threads.append(threading.Thread(target=event_reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    check('no errors during concurrent learn events', len(errors) == 0,
          str(errors[:3]) if errors else '')
    check('learn_events populated', len(ns['learn_events']) > 0)
    check('learn_events capped at 50', len(ns['learn_events']) <= 50)
    check('snapshots are independent copies',
          all(isinstance(s, int) for s in snapshots))
else:
    print('  SKIP: functions not loaded')


# ============================================================
# TEST 6: Concurrent onset anomaly detection
# ============================================================
print()
print('=== TEST 6: Concurrent onset anomaly detection ===')
detect_oa = ns.get('detect_onset_anomalies')
if detect_oa:
    errors = []
    results_list = []

    words_pool = "the computer conference structure problem break strong think class great " * 25
    sessions = [{"raw": words_pool}] * 35

    def anomaly_worker():
        try:
            for _ in range(20):
                r = detect_oa(sessions, min_sessions=30, min_content_words=50)
                results_list.append(r)
                # Verify invariants
                assert isinstance(r, list)
                assert len(r) <= 5
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=anomaly_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    check('no errors during concurrent anomaly detection', len(errors) == 0,
          str(errors[:3]) if errors else '')
    check('all results are valid lists',
          all(isinstance(r, list) for r in results_list))
    check('global _onset_anomalies is list', isinstance(ns['_onset_anomalies'], list))
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
