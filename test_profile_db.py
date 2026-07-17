"""
Tests for profile lifecycle and database operations.
Covers: load_profile, save_profile, switch_profile, create_profile,
        migrate_profile, normalize_profile, _init_db, log_session,
        db_get_sessions, _migrate_candidate_corrections.

Uses temporary directories to isolate from the real user profile.
"""
import json, sys, os, sqlite3, tempfile, shutil, threading, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

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
# Setup: create an isolated environment with temp directories
# ============================================================
_tmpdir = tempfile.mkdtemp(prefix="lavrentiy_test_")
_profiles_root = os.path.join(_tmpdir, "profiles")
os.makedirs(_profiles_root, exist_ok=True)

# We need to exec carefully: the module has side effects (audio, API, keyboard).
# Instead, we extract functions + constants and wire them to our temp paths.
import ast, re
from pathlib import Path
from datetime import datetime

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()
tree = ast.parse(source)
lines = source.split('\n')

# Build a namespace with the constants and stubs we need
ns = {
    're': re, 'json': json, 'os': os, 'sqlite3': sqlite3,
    'time': time, 'threading': threading,
    'datetime': datetime,  # datetime.datetime class, not the module
    'pathlib': __import__('pathlib'), 'Path': Path,
    'tempfile': __import__('tempfile'), 'shutil': __import__('shutil'),
    # Stubs
    'log': lambda msg, level='info': None,
    'stats': {'api_calls': 0, 'sessions': 0, 'falcon_rejects': 0,
              'words': 0, 'chars': 0, 'start_time': time.time()},
    'stats_inc': lambda *a, **kw: None,
}

# Load constants block
start_idx = next(i for i, l in enumerate(lines) if l.startswith('LANGUAGE = '))
end_idx = next(i for i, l in enumerate(lines) if '_personal_onset_weights_by_lang' in l and '=' in l)
exec('\n'.join(lines[start_idx:end_idx + 1]), ns)

# Override paths to temp dir
ns['LAVRENTIY_DIR'] = Path(_tmpdir)
ns['PROFILES_ROOT'] = Path(_profiles_root)
ns['ACTIVE_FILE'] = Path(_tmpdir) / "active_profile"
ns['DEFAULT_PROFILE_NAME'] = "Default"

# Resolve default profile paths
default_pdir = Path(_profiles_root) / "Default"
default_pdir.mkdir(parents=True, exist_ok=True)
ns['PROFILE_DIR'] = default_pdir
ns['PROFILE_PATH'] = default_pdir / "profile.json"
ns['DB_PATH'] = default_pdir / "history.db"
ns['BACKUP_DIR'] = default_pdir / "backups"
ns['_active_profile_name'] = "Default"
ns['_profile_switch_epoch'] = 0

# Profile constants
ns['PROFILE_VERSION'] = 4
ns['MAX_PROFILE_ITEMS'] = 200
ns['LEARN_PROMOTION_THRESHOLD'] = 2
ns['LEARN_EVERY'] = 3
ns['DECAY_EVERY'] = 10

# Default profile
ns['DEFAULT_PROFILE'] = {
    "version": 4,
    "created": None,
    "trigger_words": [],
    "filler_words": ["um", "uh", "like", "you know"],
    "corrections": {},
    "vocabulary": [],
    "candidate_corrections": {},
    "candidate_fillers": {},
    "candidate_vocabulary": {},
    "preferences": {"tone": "casual", "layer": 2, "paralinguistic": False,
                     "prosodic": False, "paralinguistic_transcribe": False}
}

ns['KNOWN_FILLERS'] = {"en": {"um", "uh", "er", "ah"}, "ru": {"э", "ээ", "ну"}}

# Load target functions from AST
target_funcs = [
    'load_profile', 'save_profile', 'create_profile', 'switch_profile',
    'migrate_profile', 'normalize_profile', '_snapshot_profile',
    '_migrate_candidate_corrections', 'migrate_fillers',
    '_norm_str', '_dedupe_list', '_norm_corrections',
    '_resolve_profile_paths', '_read_active_profile_name', '_write_active_profile_name',
    'list_profiles',
    '_init_db', 'log_session', 'db_get_sessions', 'db_session_count',
    'detect_word_language',
    'learn_onset_weights',
]

loaded = []
# Load every module-level function, not just the enumerated targets — the
# tested functions call private helpers the old name filter omitted, causing
# NameErrors at call time. Defining a function never runs its body, so this is
# side-effect-free; the target list is kept only for the coverage report.
for node in tree.body:
    # skip names already seeded above (intentional stubs like a no-op log()) —
    # loading the real one would drag in unseeded module state (e.g. _log_lock).
    if isinstance(node, ast.FunctionDef) and node.name not in ns:
        func_source = ast.get_source_segment(source, node)
        if func_source:
            try:
                exec(func_source, ns)
                loaded.append(node.name)
            except Exception as e:
                print(f'SKIP {node.name}: {e}')

print(f'Loaded {len(loaded)}/{len(target_funcs)} functions: {sorted(loaded)}')

# Set up locks (needed by save_profile, log_session, switch_profile)
ns['_profile_lock'] = threading.Lock()
ns['_db_lock'] = threading.Lock()

# Stubs for Firebase/Firestore integration (not testable without credentials)
ns['is_authenticated'] = lambda: False
ns['_auth_user'] = None
ns['_firebase_id_token'] = None
ns['BACKEND_URL'] = 'http://localhost:0'
ns['sync_profile_to_firestore'] = lambda prof: None

# Wire current_situation for log_session
ns['current_situation'] = 'default'

# Initialize learn_status / learn_events (needed by switch_profile)
ns['learn_events'] = []
ns['learn_status'] = {"last_run": None, "total_learned": 0, "next_in": ns['LEARN_EVERY']}

# Grab refs for convenience
load_profile = ns['load_profile']
save_profile = ns['save_profile']
create_profile = ns['create_profile']
normalize_profile = ns['normalize_profile']
migrate_profile = ns['migrate_profile']
_snapshot_profile = ns['_snapshot_profile']
_migrate_candidate_corrections = ns['_migrate_candidate_corrections']
migrate_fillers = ns['migrate_fillers']
_init_db = ns['_init_db']
log_session = ns['log_session']
db_get_sessions = ns['db_get_sessions']
db_session_count = ns['db_session_count']

# Initialize DB
ns['_db'] = _init_db(ns['DB_PATH'])

# Make profile a ref in ns
ns['profile'] = load_profile()

# ============================================================
# TEST 1: load_profile — default creation
# ============================================================
print()
print('=== TEST 1: load_profile (no existing file) ===')
p = load_profile()
check('returns dict', isinstance(p, dict))
check('has version', p.get('version') == 4)
check('has trigger_words list', isinstance(p.get('trigger_words'), list))
check('has filler_words list', isinstance(p.get('filler_words'), list))
check('has corrections dict', isinstance(p.get('corrections'), dict))
check('has vocabulary list', isinstance(p.get('vocabulary'), list))
check('has created timestamp', p.get('created') is not None)

# ============================================================
# TEST 2: save_profile + load_profile round-trip
# ============================================================
print()
print('=== TEST 2: save_profile + load_profile round-trip ===')
p['corrections'] = {"Duncan": "Dankeschoen", "notch": "noch"}
p['trigger_words'] = ["computer", "conference"]
p['vocabulary'] = ["synecdoche", "Kubernetes"]
save_profile(p)
check('profile.json exists', ns['PROFILE_PATH'].exists())
p2 = load_profile()
check('corrections survived', p2['corrections'] == {"Duncan": "Dankeschoen", "notch": "noch"})
check('trigger_words survived', p2['trigger_words'] == ["computer", "conference"])
check('vocabulary survived', p2['vocabulary'] == ["synecdoche", "Kubernetes"])
check('version survived', p2['version'] == 4)

# ============================================================
# TEST 3: load_profile — corrupt JSON recovery
# ============================================================
print()
print('=== TEST 3: load_profile — corrupt JSON recovery ===')
with open(ns['PROFILE_PATH'], 'w') as f:
    f.write('{{{{not valid json}}}')
p3 = load_profile()
check('corrupt file -> default profile', p3.get('version') == 4)
check('corrupt file -> empty trigger_words', p3['trigger_words'] == [])

# ============================================================
# TEST 4: normalize_profile
# ============================================================
print()
print('=== TEST 4: normalize_profile ===')
p4 = {
    "version": 4,
    "trigger_words": ["Hello", "hello", "HELLO", "world"],
    "filler_words": ["um", "UM", "um"],
    "vocabulary": [],
    "corrections": {"  Duncan  ": "  Dankeschoen  ", "": "empty_key"},
}
changed = normalize_profile(p4)
check('detected changes', changed is True)
check('trigger_words deduped', len(p4['trigger_words']) == 2)
check('filler_words deduped', len(p4['filler_words']) == 1)
check('corrections stripped', "Duncan" in p4['corrections'])
check('empty key removed', "" not in p4['corrections'])

p5 = {"version": 4, "trigger_words": ["a", "b"], "filler_words": ["um"],
      "vocabulary": [], "corrections": {"x": "y"}}
changed2 = normalize_profile(p5)
check('clean profile -> no change', changed2 is False)

# ============================================================
# TEST 5: migrate_profile (v1 -> v4)
# ============================================================
print()
print('=== TEST 5: migrate_profile ===')
old_profile = {
    "version": 1,
    "trigger_words": ["computer", "строительство"],
    "filler_words": ["um"],
    "corrections": {},
    "vocabulary": [],
}
ns['BACKUP_DIR'].mkdir(parents=True, exist_ok=True)
# Save old profile first so _snapshot_profile can write
save_profile(old_profile)
migrated = migrate_profile(dict(old_profile))
check('version upgraded', migrated.get('version') == 4)
check('candidate_corrections added', 'candidate_corrections' in migrated)
check('candidate_fillers added', 'candidate_fillers' in migrated)
check('trigger_words_by_lang added', 'trigger_words_by_lang' in migrated)
by_lang = migrated['trigger_words_by_lang']
check('en triggers populated', 'computer' in by_lang.get('en', []))
check('ru triggers populated', 'строительство' in by_lang.get('ru', []) or
      'строительство' in by_lang.get('en', []))

# ============================================================
# TEST 6: _migrate_candidate_corrections (v2 -> v3)
# ============================================================
print()
print('=== TEST 6: _migrate_candidate_corrections ===')
v2_cands = {
    "hello": {"right": "halo", "count": 3},
    "already_v3": {"votes": {"correct": 5}, "total": 5},
}
v3 = _migrate_candidate_corrections(v2_cands)
check('v2 converted to votes', 'votes' in v3['hello'])
check('v2 vote count correct', v3['hello']['votes']['halo'] == 3)
check('v2 total correct', v3['hello']['total'] == 3)
check('v3 entry unchanged', v3['already_v3'] == {"votes": {"correct": 5}, "total": 5})

# ============================================================
# TEST 7: create_profile
# ============================================================
print()
print('=== TEST 7: create_profile ===')
create_profile("TestUser")
test_dir = Path(_profiles_root) / "TestUser"
check('profile dir created', test_dir.exists())
check('profile.json created', (test_dir / "profile.json").exists())
with open(test_dir / "profile.json") as f:
    tp = json.load(f)
check('new profile has version', tp.get('version') == 4)
check('new profile has created', tp.get('created') is not None)

# Duplicate
try:
    create_profile("TestUser")
    check('duplicate raises ValueError', False)
except ValueError:
    check('duplicate raises ValueError', True)

# Invalid names
for bad_name in ["", "foo/bar", "foo\\bar", "foo..bar"]:
    try:
        # Explicitly calling with name that should fail
        # .. in name should raise, .. in path should raise
        if '..' in bad_name or '/' in bad_name or '\\' in bad_name or bad_name.strip() == '':
            create_profile(bad_name)
            check(f'invalid name "{bad_name}" raises', False)
        else:
            check(f'valid name "{bad_name}" accepted', True)
    except ValueError:
        check(f'invalid name "{bad_name}" raises', True)

# ============================================================
# TEST 8: _init_db — schema creation and migration
# ============================================================
print()
print('=== TEST 8: _init_db ===')
test_db_path = Path(_tmpdir) / "test_init.db"
db = _init_db(test_db_path)
# Check all expected columns exist
cursor = db.execute("PRAGMA table_info(sessions)")
cols = {row[1] for row in cursor.fetchall()}
expected_cols = {
    'id', 'ts', 'raw', 'out', 'tone', 'layer', 'words', 'falcon',
    'decision', 'timings', 'situation', 'disfluency_counts',
    'exposure_difficulty', 'editorial_distance', 'speech_metrics',
    'lang', 'paralinguistic_events', 'prosodic_summary'
}
check('all columns present', expected_cols.issubset(cols))
missing = expected_cols - cols
if missing:
    print(f'    Missing columns: {missing}')

# Idempotent: call _init_db again on same file
db.close()
db2 = _init_db(test_db_path)
cursor2 = db2.execute("PRAGMA table_info(sessions)")
cols2 = {row[1] for row in cursor2.fetchall()}
check('idempotent init preserves columns', cols2 == cols)
db2.close()

# WAL mode
db3 = _init_db(test_db_path)
mode = db3.execute("PRAGMA journal_mode").fetchone()[0]
check('WAL mode enabled', mode == 'wal')
db3.close()

# ============================================================
# TEST 9: _init_db on v1 schema (migration path)
# ============================================================
print()
print('=== TEST 9: _init_db migration from v1 schema ===')
v1_db_path = Path(_tmpdir) / "v1_test.db"
# Create a v1 schema manually (only core columns)
v1_db = sqlite3.connect(str(v1_db_path))
v1_db.execute("""
    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL, raw TEXT NOT NULL, out TEXT NOT NULL,
        tone TEXT NOT NULL, layer INTEGER NOT NULL,
        words INTEGER NOT NULL, falcon INTEGER NOT NULL DEFAULT 1,
        decision TEXT, timings TEXT
    )
""")
v1_db.execute("INSERT INTO sessions (ts, raw, out, tone, layer, words) VALUES (?, ?, ?, ?, ?, ?)",
              ("2026-01-01T00:00:00", "test raw", "test out", "casual", 2, 3))
v1_db.commit()
v1_db.close()

# Now run _init_db on it — should add missing columns
migrated_db = _init_db(v1_db_path)
cursor_m = migrated_db.execute("PRAGMA table_info(sessions)")
migrated_cols = {row[1] for row in cursor_m.fetchall()}
check('migration added situation', 'situation' in migrated_cols)
check('migration added disfluency_counts', 'disfluency_counts' in migrated_cols)
check('migration added exposure_difficulty', 'exposure_difficulty' in migrated_cols)
check('migration added editorial_distance', 'editorial_distance' in migrated_cols)
check('migration added speech_metrics', 'speech_metrics' in migrated_cols)
check('migration added lang', 'lang' in migrated_cols)
check('migration added paralinguistic_events', 'paralinguistic_events' in migrated_cols)
check('migration added prosodic_summary', 'prosodic_summary' in migrated_cols)

# Original data preserved
row = migrated_db.execute("SELECT raw, out FROM sessions WHERE id=1").fetchone()
check('v1 data preserved after migration', row == ("test raw", "test out"))
migrated_db.close()

# ============================================================
# TEST 10: log_session + db_get_sessions round-trip
# ============================================================
print()
print('=== TEST 10: log_session + db_get_sessions round-trip ===')
# Reset the DB to our test instance
ns['_db'] = _init_db(ns['DB_PATH'])

test_decision = {"falcon_ok": True, "action": "paste_clean", "mode": "SAFE",
                 "flags": [], "reason": "ok"}
test_timings = {"whisper_ms": 1200, "reconstruct_ms": 800, "total_ms": 2000}
test_disf = {"total": 3, "repetition": 2, "filler": 1}
test_exposure = {"score": 0.45, "band": "medium", "components": {}}
test_edit_dist = 0.234
test_speech = {"pause_ratio": 0.15, "speaking_rate_sps": 3.2, "severity_modifier": 0.1}
test_para = [{"type": "cough", "start": 1.2, "end": 1.5, "confidence": 0.8}]
test_prosodic = {"f0_mean": 120.5, "energy_mean": 0.05, "rate": 3.1}

log_session(
    ns['profile'], "I I want to go to the store", "I want to go to the store",
    "casual", 3,
    decision=test_decision, timings=test_timings, situation="high_stress",
    disf_counts=test_disf, exposure=test_exposure, edit_dist=test_edit_dist,
    speech_metrics=test_speech, lang="en",
    paralinguistic_events=test_para, prosodic_summary=test_prosodic
)

sessions = db_get_sessions(limit=1)
check('got 1 session', len(sessions) == 1)
s = sessions[0]
check('raw text preserved', s['raw'] == "I I want to go to the store")
check('output text preserved', s['out'] == "I want to go to the store")
check('tone preserved', s['tone'] == "casual")
check('layer preserved', s['layer'] == 3)
check('words counted', s['words'] == 7)
check('falcon preserved', s['falcon'] is True)
check('situation preserved', s['situation'] == "high_stress")
check('lang preserved', s['lang'] == "en")

# JSON fields round-tripped
check('decision round-tripped', s.get('decision', {}).get('action') == "paste_clean")
check('timings round-tripped', s.get('timings', {}).get('whisper_ms') == 1200)
check('disfluency_counts round-tripped', s.get('disfluency_counts', {}).get('total') == 3)
check('exposure round-tripped', s.get('exposure', {}).get('score') == 0.45)
check('editorial_distance round-tripped', isinstance(s.get('editorial_distance'), float))
check('speech_metrics round-tripped', s.get('speech_metrics', {}).get('pause_ratio') == 0.15)
check('prosodic_summary round-tripped', s.get('prosodic_summary', {}).get('f0_mean') == 120.5)

# ============================================================
# TEST 11: db_session_count
# ============================================================
print()
print('=== TEST 11: db_session_count ===')
count = db_session_count()
check('session count >= 1', count >= 1)

# Log a few more sessions
for i in range(5):
    log_session(ns['profile'], f"raw {i}", f"out {i}", "casual", 2)
count2 = db_session_count()
check('count increased by 5', count2 == count + 5)

# ============================================================
# TEST 12: log_session with None/missing optional fields
# ============================================================
print()
print('=== TEST 12: log_session minimal (no optional fields) ===')
log_session(ns['profile'], "minimal raw", "minimal out", "formal", 1)
sessions = db_get_sessions(limit=1)
s = sessions[0]
check('minimal session stored', s['raw'] == "minimal raw")
check('decision is None-safe', 'decision' not in s or s.get('decision') is None)
check('situation defaults', s['situation'] == 'default')
check('lang defaults to en', s['lang'] == 'en')

# ============================================================
# TEST 13: concurrent DB writes
# ============================================================
print()
print('=== TEST 13: concurrent DB writes ===')
before = db_session_count()
errors = []
def _write_session(idx):
    try:
        log_session(ns['profile'], f"concurrent raw {idx}", f"concurrent out {idx}", "casual", 2)
    except Exception as e:
        errors.append(str(e))

threads = [threading.Thread(target=_write_session, args=(i,)) for i in range(20)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=10)
after = db_session_count()
check('all 20 concurrent writes succeeded', after == before + 20)
check('no errors', len(errors) == 0)

# ============================================================
# TEST 14: save_profile thread safety
# ============================================================
print()
print('=== TEST 14: concurrent save_profile ===')
base_profile = load_profile()
base_profile['trigger_words'] = ['word1']
save_errors = []

def _save_loop(n):
    try:
        for i in range(10):
            p = dict(base_profile)
            p['trigger_words'] = [f'thread{n}_iter{i}']
            save_profile(p)
    except Exception as e:
        save_errors.append(str(e))

threads = [threading.Thread(target=_save_loop, args=(i,)) for i in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=10)
check('concurrent saves no errors', len(save_errors) == 0)
# Final profile should be valid JSON
final = load_profile()
check('profile valid after concurrent writes', isinstance(final.get('trigger_words'), list))

# ============================================================
# TEST 15: _snapshot_profile
# ============================================================
print()
print('=== TEST 15: _snapshot_profile ===')
ns['BACKUP_DIR'].mkdir(parents=True, exist_ok=True)
test_prof = {"version": 4, "test": True}
created_backup = _snapshot_profile(test_prof)
backups = list(ns['BACKUP_DIR'].glob("profile_*.json"))
check('backup created', len(backups) >= 1)
with open(created_backup) as f:
    bk = json.load(f)
check('backup content matches', bk.get('test') is True)

# ============================================================
# TEST 16: migrate_fillers
# ============================================================
print()
print('=== TEST 16: migrate_fillers ===')
sparse_profile = {"version": 4, "filler_words": ["um"]}
# Need to save first so migrate_fillers can call save_profile
save_profile(sparse_profile)
ns['profile'] = sparse_profile
migrate_fillers(sparse_profile)
check('fillers expanded', len(sparse_profile['filler_words']) > 1)
check('original um preserved', 'um' in [f.lower() for f in sparse_profile['filler_words']])
# Russian fillers seeded
lower_fillers = {f.lower() for f in sparse_profile['filler_words']}
has_ru = any(f in lower_fillers for f in ['э', 'ну', 'ээ'])
check('Russian fillers seeded', has_ru)

# Idempotent
before_count = len(sparse_profile['filler_words'])
migrate_fillers(sparse_profile)
check('idempotent (no new fillers on re-run)', len(sparse_profile['filler_words']) == before_count)


# ============================================================
# CLEANUP
# ============================================================
try:
    ns['_db'].close()
except Exception:
    pass
shutil.rmtree(_tmpdir, ignore_errors=True)

# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
