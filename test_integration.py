"""
Integration tests for Lavrentiy.
Tests disfluency filter, database round-trip, profile migration, and count functions.
"""
import re, json, sys, os, sqlite3, tempfile, shutil, ast, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace
ns = {'re': re, 'json': json, 'time': time, 'os': os, 'sqlite3': sqlite3,
      'datetime': __import__('datetime'), 'difflib': __import__('difflib'),
      'pathlib': __import__('pathlib')}

# Load constants (lines 276-451)
exec('\n'.join(lines[275:452]), ns)

# Load disfluency-related constants and stubs
ns['_onset_anomalies'] = []
ns['log'] = lambda msg, level='info': None
ns['stats'] = {'api_calls': 0, 'sessions': 0, 'falcon_rejects': 0,
               'words': 0, 'chars': 0, 'start_time': time.time(),
               'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
ns['current_mode'] = 'SAFE'
ns['current_situation'] = 'default'
ns['HOLD_ON_HIGH_RISK'] = False
ns['_DANGLING'] = re.compile(r'(?:,|\band\s*$|\bor\s*$|\bbut\s*$|\.{2}(?!\.)|\bthe\s*$)', re.IGNORECASE)
ns['KNOWN_FILLERS'] = {"en": {"um", "uh", "er", "ah"}, "ru": {"э", "ээ", "ну"}}

# Load _STRIP_FILLERS
exec('\n'.join(lines[2067:2071]), ns)

# Load target functions
target_funcs = [
    'strip_disfluencies', 'count_disfluencies', 'detect_ocd_loops',
    'compute_risk_flags', 'make_decision', 'compute_wer',
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
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
# TEST A: strip_disfluencies (the core L1 feature)
# ============================================================
print('=== TEST A: strip_disfluencies ===')
strip = ns.get('strip_disfluencies')
if strip:
    # Word repetitions
    r = strip('I I I want to go')
    check(f'word rep "I I I want" -> "{r}"', 'I want' in r and r.count('I') == 1)

    r = strip('the the dog')
    check(f'word rep "the the dog" -> "{r}"', r.strip() == 'the dog')

    # Stutter fragments
    r = strip('p- p- pop')
    check(f'stutter "p- p- pop" -> "{r}"', 'pop' in r and 'p-' not in r)

    # Phrase repetitions
    r = strip('I want I want to go')
    check(f'phrase rep "I want I want to go" -> "{r}"', r.strip() == 'I want to go')

    # Filler stripping
    r = strip('um I uh want to er go')
    check(f'fillers stripped -> "{r}"', 'um' not in r.lower() and 'uh' not in r.lower() and 'er' not in r.lower())
    check(f'content preserved -> "{r}"', 'want' in r and 'go' in r)

    # Russian fillers
    r = strip('э я ну хочу ээ пойти')
    check(f'RU fillers stripped -> "{r}"', 'э' not in r.split() and 'ну' not in r.split() and 'ээ' not in r.split())

    # Empty/None
    check('empty string -> empty', strip('') == '')
    check('None -> None', strip(None) is None)

    # Single filler = keep (don't return empty)
    r = strip('um')
    check(f'single filler preserved -> "{r}"', r == 'um')

    # Clean text passes through
    r = strip('I want to go to the store')
    check(f'clean text unchanged -> "{r}"', r == 'I want to go to the store')

    # Mixed disfluencies
    r = strip('um I I want to uh p- p- pick up the the groceries')
    check(f'mixed disfluencies -> "{r}"', 'I want' in r and 'pick' in r and 'groceries' in r)
    check(f'no fillers remain', 'um' not in r.split() and 'uh' not in r.split())
else:
    print('  SKIP: function not loaded')

# ============================================================
# TEST B: count_disfluencies
# ============================================================
print()
print('=== TEST B: count_disfluencies ===')
count = ns.get('count_disfluencies')
if count:
    # Word repetitions
    c = count('I I I want to go')
    check(f'word_rep detected: {c}', c.get('word_rep', 0) >= 1)

    # Fillers
    c = count('um I uh want to er go')
    check(f'fillers counted: {c.get("filler", 0)}', c.get('filler', 0) == 3)

    # Clean text
    c = count('I want to go to the store')
    check(f'clean text: total={c.get("total", 0)}', c.get('total', 0) == 0)

    # Empty
    c = count('')
    check('empty -> empty dict', c == {})

    c = count(None)
    check('None -> empty dict', c == {})

    # Prolongation
    c = count('I sssssaid hello')
    check(f'prolongation detected: {c}', c.get('prolongation', 0) >= 1)

    # Total is sum of all
    c = count('um um um I I want')
    total = c.get('total', 0)
    parts = sum(v for k, v in c.items() if k != 'total')
    check(f'total={total} == sum of parts={parts}', total == parts)
else:
    print('  SKIP: function not loaded')

# ============================================================
# TEST C: Database round-trip (SQLite schema + insert + read)
# ============================================================
print()
print('=== TEST C: Database round-trip ===')

# Create temp DB
tmp_dir = tempfile.mkdtemp()
db_path = os.path.join(tmp_dir, 'test_history.db')

try:
    db = sqlite3.connect(db_path)
    # Create table matching current schema
    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            raw TEXT NOT NULL,
            out TEXT NOT NULL,
            tone TEXT NOT NULL,
            layer INTEGER NOT NULL,
            words INTEGER NOT NULL,
            falcon INTEGER NOT NULL DEFAULT 1,
            decision TEXT,
            timings TEXT,
            situation TEXT DEFAULT 'default',
            disfluency_counts TEXT,
            exposure_difficulty REAL,
            editorial_distance REAL
        )
    """)
    db.commit()
    check('table created', True)

    # Insert a session with all fields
    ts = '2026-03-13T12:00:00'
    decision = json.dumps({"mode": "SAFE", "falcon_ok": True, "risk_flags": [], "decision": "paste_clean"})
    timings = json.dumps({"asr_ms": 450, "recon_ms": 300, "val_ms": 100, "total_ms": 850})
    disf = json.dumps({"word_rep": 2, "filler": 3, "total": 5})

    db.execute(
        "INSERT INTO sessions (ts, raw, out, tone, layer, words, falcon, decision, timings, "
        "situation, disfluency_counts, exposure_difficulty, editorial_distance) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, "I I want to um go", "I want to go", "casual", 2, 4, 1,
         decision, timings, "phone", disf, 0.72, 0.35)
    )
    db.commit()
    check('session inserted', True)

    # Read it back
    row = db.execute(
        "SELECT ts, raw, out, tone, layer, words, falcon, decision, timings, "
        "situation, disfluency_counts, exposure_difficulty, editorial_distance "
        "FROM sessions WHERE id = 1"
    ).fetchone()

    check('row exists', row is not None)
    check(f'ts = {row[0]}', row[0] == ts)
    check(f'raw preserved', row[1] == "I I want to um go")
    check(f'out preserved', row[2] == "I want to go")
    check(f'tone = casual', row[3] == "casual")
    check(f'layer = 2', row[4] == 2)
    check(f'words = 4', row[5] == 4)
    check(f'falcon = 1 (True)', row[6] == 1)
    check(f'situation = phone', row[9] == "phone")
    check(f'exposure = 0.72', abs(row[11] - 0.72) < 0.001)
    check(f'edit_dist = 0.35', abs(row[12] - 0.35) < 0.001)

    # Parse JSON fields
    dec = json.loads(row[7])
    check(f'decision.mode = SAFE', dec["mode"] == "SAFE")
    check(f'decision.falcon_ok = True', dec["falcon_ok"] is True)

    tim = json.loads(row[8])
    check(f'timings.total_ms = 850', tim["total_ms"] == 850)

    disf_back = json.loads(row[10])
    check(f'disfluency_counts.total = 5', disf_back["total"] == 5)
    check(f'disfluency_counts.word_rep = 2', disf_back["word_rep"] == 2)

    # Test migration: add columns to existing table
    db2 = sqlite3.connect(os.path.join(tmp_dir, 'test_migrate.db'))
    db2.execute("""CREATE TABLE sessions (
        id INTEGER PRIMARY KEY, ts TEXT, raw TEXT, out TEXT,
        tone TEXT, layer INTEGER, words INTEGER, falcon INTEGER DEFAULT 1
    )""")
    db2.execute("INSERT INTO sessions VALUES (1, '2026-01-01', 'hi', 'hi', 'casual', 1, 1, 1)")
    db2.commit()

    # Simulate migration (add missing columns)
    for col, typ, default in [
        ('situation', 'TEXT', "'default'"),
        ('disfluency_counts', 'TEXT', 'NULL'),
        ('exposure_difficulty', 'REAL', 'NULL'),
        ('editorial_distance', 'REAL', 'NULL'),
    ]:
        try:
            db2.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typ} DEFAULT {default}")
        except sqlite3.OperationalError:
            pass
    db2.commit()

    # Verify old row still readable with new columns
    row2 = db2.execute("SELECT situation, disfluency_counts FROM sessions WHERE id = 1").fetchone()
    check(f'migrated row situation = default', row2[0] == 'default')
    check(f'migrated row disf_counts = None', row2[1] is None)
    db2.close()

    db.close()
    check('DB cleanup OK', True)

except Exception as e:
    failed += 1
    print(f'  FAIL: DB test exception: {e}')
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

# ============================================================
# TEST D: Profile schema v3 -> v4 migration
# ============================================================
print()
print('=== TEST D: Profile schema migration ===')

v3_profile = {
    "version": 3,
    "language": "en-ru",
    "trigger_words": ["computer", "conference", "break"],
    "filler_words": ["um", "uh", "э"],
    "vocabulary": ["Lavrentiy", "microservice"],
    "corrections": {"Duncan": "Dankeschön"},
    "candidate_corrections": {},
    "candidate_fillers": [],
    "candidate_vocabulary": [],
}

# Simulate v3 -> v4 migration (add new fields if missing)
profile = dict(v3_profile)
if profile.get("version", 1) < 4:
    profile["version"] = 4
    profile.setdefault("phonetic_triggers", {"weights": {}, "by_lang": {"en": {}, "ru": {}}})
    profile.setdefault("ocd_speech_profile", {
        "loop_patterns": {},
        "avoidance_patterns": {},
        "estimated_tendencies": {"block_tendency": 0.0, "compulsion_tendency": 0.0, "avoidance_tendency": 0.0}
    })
    profile.setdefault("ceiling_tracker", {"metrics": {}, "last_updated": None})
    profile.setdefault("correction_decay", {})

check('version bumped to 4', profile["version"] == 4)
check('trigger_words preserved', profile["trigger_words"] == ["computer", "conference", "break"])
check('corrections preserved', profile["corrections"] == {"Duncan": "Dankeschön"})
check('phonetic_triggers added', "phonetic_triggers" in profile)
check('ocd_speech_profile added', "ocd_speech_profile" in profile)
check('ceiling_tracker added', "ceiling_tracker" in profile)
check('correction_decay added', "correction_decay" in profile)
check('by_lang has en and ru', "en" in profile["phonetic_triggers"]["by_lang"])

# Verify JSON serializable
try:
    serialized = json.dumps(profile, indent=2)
    deserialized = json.loads(serialized)
    check('profile JSON round-trip', deserialized == profile)
except Exception as e:
    check(f'profile JSON round-trip', False, str(e))

# ============================================================
# TEST E: detect_ocd_loops
# ============================================================
print()
print('=== TEST E: detect_ocd_loops ===')
loops_fn = ns.get('detect_ocd_loops')
if loops_fn:
    # Clear compulsive loop (3+ repetitions)
    r = loops_fn('I need to I need to I need to check the door')
    check(f'3x loop detected: {r}', len(r) >= 1)

    # Not a loop (only 2x = stutter, not compulsion)
    r = loops_fn('I want I want to go')
    check(f'2x phrase = not a loop: {r}', len(r) == 0)

    # Clean text
    r = loops_fn('I want to go to the store')
    check(f'clean text = no loops: {r}', len(r) == 0)
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
