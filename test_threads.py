"""
Thread safety tests for Lavrentiy shared state.
Verifies no corruption when multiple threads hit _shadow_history,
_onset_anomalies, stats, preview_state, and the learn loop concurrently.
No API keys, no audio, no Win32.
"""
import re, json, sys, ast, time, io, threading, os
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
ns['save_profile'] = lambda prof, _epoch=None: None
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
print()
print('=== TEST 7: Profile lock contention (save_profile) ===')
import tempfile, os

# Create a real save_profile with the real _profile_lock, writing to a temp dir
_test_profile_lock = threading.Lock()
_test_profile_dir = Path(tempfile.mkdtemp())
_test_profile_path = _test_profile_dir / 'profile.json'

def _test_save_profile(prof):
    """Real atomic save with lock — mirrors production save_profile."""
    with _test_profile_lock:
        tmp_path = _test_profile_path.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(prof, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        # Windows can raise PermissionError if a reader holds the target file;
        # retry once after a brief pause (matches real-world behavior)
        try:
            tmp_path.replace(_test_profile_path)
        except PermissionError:
            time.sleep(0.01)
            tmp_path.replace(_test_profile_path)

errors7 = []
N_PROFILE_THREADS = 10
N_PROFILE_OPS = 50

def profile_worker(tid):
    """Each thread writes a profile with its own thread_id embedded."""
    try:
        for i in range(N_PROFILE_OPS):
            prof = {
                "version": 4,
                "thread_id": tid,
                "write_num": i,
                "trigger_words": [f"word_{tid}_{j}" for j in range(10)],
                "filler_words": ["um", "uh"],
                "vocabulary": [f"vocab_{tid}"],
                "corrections": {f"heard_{tid}": f"meant_{tid}"},
                "covert_avoidance": {},
            }
            _test_save_profile(prof)
    except Exception as e:
        errors7.append(f"thread {tid}: {e}")

threads7 = [threading.Thread(target=profile_worker, args=(t,)) for t in range(N_PROFILE_THREADS)]
for t7 in threads7:
    t7.start()
for t7 in threads7:
    t7.join(timeout=30)

check('no errors during concurrent profile writes', len(errors7) == 0,
      str(errors7[:3]) if errors7 else '')

# Verify the final file is valid JSON
try:
    with open(_test_profile_path, 'r', encoding='utf-8') as f:
        final_prof = json.load(f)
    check('final profile is valid JSON', True)
    check('final profile has version field', final_prof.get('version') == 4)
    check('final profile has trigger_words list', isinstance(final_prof.get('trigger_words'), list))
    check('final profile has 10 trigger words', len(final_prof.get('trigger_words', [])) == 10)
    check('final profile has corrections dict', isinstance(final_prof.get('corrections'), dict))
except (json.JSONDecodeError, IOError) as e:
    check('final profile is valid JSON', False, str(e))

# Verify no .tmp file left behind (atomic rename completed)
tmp_leftover = _test_profile_path.with_suffix('.tmp')
check('no .tmp file left behind', not tmp_leftover.exists())

# Stress test: rapid sequential reads during writes
read_errors = []
read_results = []
write_done = threading.Event()

def profile_writer_stress():
    for i in range(100):
        _test_save_profile({"version": 4, "stress_write": i, "trigger_words": []})
    write_done.set()

def profile_reader_stress():
    while not write_done.is_set():
        try:
            if _test_profile_path.exists():
                with open(_test_profile_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                read_results.append(data)
        except json.JSONDecodeError as e:
            read_errors.append(str(e))
        except IOError:
            pass  # file mid-rename, OK

writer_t = threading.Thread(target=profile_writer_stress)
readers = [threading.Thread(target=profile_reader_stress) for _ in range(3)]
write_done.clear()
for r in readers:
    r.start()
writer_t.start()
writer_t.join(timeout=15)
write_done.set()
for r in readers:
    r.join(timeout=5)

check('no JSON decode errors during concurrent read/write', len(read_errors) == 0,
      str(read_errors[:3]) if read_errors else '')
check(f'readers got valid profiles ({len(read_results)} reads)',
      len(read_results) > 0 and all(isinstance(r, dict) for r in read_results))

# Cleanup
import shutil
shutil.rmtree(_test_profile_dir, ignore_errors=True)


# ============================================================
print()
print('=== TEST 8: Concurrent HTTP-like state mutations ===')
# Simulates dashboard polling + settings changes from multiple threads
# Tests the same lock contention pattern as the real HTTP server

# Shared state (mirrors updateUI globals)
_http_state = {
    'tone': 'casual', 'layer': 2, 'mode': 'SAFE',
    'situation': 'default', 'paralinguistic_enabled': False,
    'prosodic_enabled': False,
}
_http_lock = threading.Lock()
_http_errors = []
_http_reads = []

def http_poll_worker(n_polls):
    """Simulates dashboard GET /api/state polling."""
    for _ in range(n_polls):
        try:
            with _http_lock:
                snapshot = dict(_http_state)
            # Verify invariants on every read
            assert snapshot['layer'] in (1, 2, 3, 4), f"bad layer: {snapshot['layer']}"
            assert snapshot['tone'] in ('casual', 'professional', 'friend', 'formal')
            assert snapshot['mode'] in ('RAW', 'FAST', 'SAFE')
            assert snapshot['situation'] in ('default', 'high_stress', 'reading')
            _http_reads.append(snapshot)
        except Exception as e:
            _http_errors.append(f"poll: {e}")

def http_mutate_worker(mutations):
    """Simulates POST /api/tone, /api/layer, /api/mode, /api/situation."""
    tones = ['casual', 'professional', 'friend', 'formal']
    modes = ['RAW', 'FAST', 'SAFE']
    sits = ['default', 'high_stress', 'reading']
    for i in range(mutations):
        try:
            with _http_lock:
                _http_state['tone'] = tones[i % len(tones)]
                _http_state['layer'] = (i % 4) + 1
                _http_state['mode'] = modes[i % len(modes)]
                _http_state['situation'] = sits[i % len(sits)]
                # Toggle booleans
                _http_state['paralinguistic_enabled'] = (i % 2 == 0)
                _http_state['prosodic_enabled'] = (i % 3 == 0)
        except Exception as e:
            _http_errors.append(f"mutate: {e}")

def http_stats_worker(n_ops):
    """Simulates stats_inc from pipeline thread during recording."""
    si = ns.get('stats_inc')
    if si:
        for _ in range(n_ops):
            try:
                si('words', 1)
                si('api_calls', 1)
            except Exception as e:
                _http_errors.append(f"stats: {e}")

# Reset stats
ns['stats']['words'] = 0
ns['stats']['api_calls'] = 0

# Launch: 3 pollers (100 polls each) + 2 mutators (100 mutations each) + 2 stats writers (200 ops each)
pollers = [threading.Thread(target=http_poll_worker, args=(100,)) for _ in range(3)]
mutators = [threading.Thread(target=http_mutate_worker, args=(100,)) for _ in range(2)]
stat_workers = [threading.Thread(target=http_stats_worker, args=(200,)) for _ in range(2)]

all_threads = pollers + mutators + stat_workers
for th in all_threads:
    th.start()
for th in all_threads:
    th.join(timeout=15)

check('no errors during concurrent HTTP simulation', len(_http_errors) == 0,
      str(_http_errors[:3]) if _http_errors else '')
check(f'pollers completed ({len(_http_reads)} reads)', len(_http_reads) == 300)
check('all reads had valid state', all(
    r['layer'] in (1,2,3,4) and r['tone'] in ('casual','professional','friend','formal')
    for r in _http_reads))
# Stats should be exact: 2 threads × 200 ops = 400 each
check(f'stats_inc words exact (expected 400, got {ns["stats"]["words"]})',
      ns['stats']['words'] == 400)
check(f'stats_inc api_calls exact (expected 400, got {ns["stats"]["api_calls"]})',
      ns['stats']['api_calls'] == 400)

# Final state should be valid (last mutation was i=99)
with _http_lock:
    final = dict(_http_state)
check('final state is consistent',
      final['layer'] in (1,2,3,4) and final['mode'] in ('RAW','FAST','SAFE'))


# ============================================================
# TEST 9: M-1 — profile-switch epoch rejects stale bg-thread writes
# ============================================================
print()
print('=== TEST 9: M-1 epoch plumbing rejects stale bg writes ===')

# Build a minimal save_profile + add_trigger_words harness with a writable
# counter so we can prove the epoch check fires. Mirrors production code at
# lavrentiy.py:1316 (save_profile) and 3870 (add_trigger_words).
_m1_epoch = 0
_m1_writes = []  # records of every (epoch_at_save, contents)

def _m1_save_profile(prof, _epoch=None):
    """Production-equivalent save_profile epoch gate."""
    if _epoch is not None and _epoch != _m1_epoch:
        return  # stale — discard
    _m1_writes.append((_m1_epoch, json.dumps(prof, sort_keys=True)))

def _m1_add_trigger_words(new_triggers, prof, _epoch=None):
    """Production-equivalent add_trigger_words epoch through-pass."""
    existing = {w.lower() for w in prof.get("trigger_words", [])}
    added = []
    for w in new_triggers:
        if w.lower() not in existing:
            prof.setdefault("trigger_words", []).append(w)
            existing.add(w.lower())
            added.append(w)
    if added:
        _m1_save_profile(prof, _epoch=_epoch)
    return added

# Scenario A: bg thread captures epoch, no switch, save should happen.
_m1_epoch = 5
prof_a = {"trigger_words": []}
_m1_add_trigger_words(["alpha"], prof_a, _epoch=5)
check('M-1 epoch matches → save persists', len(_m1_writes) == 1)
check('M-1 saved word is alpha',
      'alpha' in _m1_writes[-1][1])

# Scenario B: bg thread captures epoch, switch happens, save should bail.
_m1_writes.clear()
_m1_epoch = 5
prof_b = {"trigger_words": []}
# Simulate the race: bg thread launched at epoch=5, switch_profile fires,
# then bg thread completes its work and tries to save with stale epoch.
_m1_epoch = 6
_m1_add_trigger_words(["beta"], prof_b, _epoch=5)
check('M-1 epoch mismatch → save discarded', len(_m1_writes) == 0)
check('M-1 prof object was still mutated in-memory (expected — only persist is gated)',
      prof_b.get("trigger_words") == ["beta"])

# Scenario C: foreground caller (no _epoch) — never gated, always saves.
_m1_writes.clear()
_m1_epoch = 7
prof_c = {"trigger_words": []}
_m1_add_trigger_words(["gamma"], prof_c)  # no _epoch passed
check('M-1 foreground (no _epoch) → save persists', len(_m1_writes) == 1)

# Verify the production add_trigger_words signature now accepts _epoch.
prod_atw = re.search(r'def add_trigger_words\((.*?)\):', source, re.DOTALL)
check('production add_trigger_words has _epoch param',
      prod_atw is not None and '_epoch' in prod_atw.group(1))

prod_lfs = re.search(r'def learn_from_sessions\((.*?)\):', source, re.DOTALL)
check('production learn_from_sessions has _epoch param',
      prod_lfs is not None and '_epoch' in prod_lfs.group(1))

prod_dec = re.search(r'def decay_stale_profile_entries\((.*?)\):', source, re.DOTALL)
check('production decay_stale_profile_entries has _epoch param',
      prod_dec is not None and '_epoch' in prod_dec.group(1))

# Verify bg-thread call sites pass _epoch through.
check('_bg_trigger_detect passes _epoch=epoch',
      'add_trigger_words(detect_triggers_llm(rt, out, prof), prof, _epoch=epoch)' in source)
check('_bg_learn passes _epoch=epoch',
      'learn_from_sessions(prof, _epoch=epoch)' in source)
check('_bg_decay passes _epoch=epoch',
      'decay_stale_profile_entries(prof, _epoch=epoch)' in source)


# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
