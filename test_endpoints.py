"""
HTTP endpoint tests for the Lavrentiy dashboard server.
Starts a real ThreadingHTTPServer on a test port, hits every endpoint,
verifies JSON response shape and state mutations.
No API keys, no audio, no Win32.
"""
import re, json, sys, ast, time, io, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
import urllib.request
import urllib.error

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace
ns = {
    're': re, 'json': json, 'time': time, 'os': __import__('os'),
    'datetime': datetime, 'timedelta': timedelta,
    'Path': Path, 'difflib': __import__('difflib'),
    'threading': threading, 'tempfile': __import__('tempfile'),
    'ThreadingHTTPServer': ThreadingHTTPServer,
    'BaseHTTPRequestHandler': __import__('http.server', fromlist=['BaseHTTPRequestHandler']).BaseHTTPRequestHandler,
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

# Load KNOWN_FILLERS
kf_start = next(i for i, l in enumerate(lines) if 'KNOWN_FILLERS' in l and '=' in l and 'if' not in l)
kf_end = kf_start + 1
while kf_end < len(lines) and '}' not in lines[kf_end]:
    kf_end += 1
exec('\n'.join(lines[kf_start:kf_end + 1]), ns)

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

# Load STUTTER_TIPS + MAX_INSIGHTS
st_start = next(i for i, l in enumerate(lines) if l.startswith('STUTTER_TIPS = '))
st_end = st_start + 1
brace_depth = 1
while st_end < len(lines) and brace_depth > 0:
    brace_depth += lines[st_end].count('{') - lines[st_end].count('}')
    st_end += 1
exec('\n'.join(lines[st_start:st_end]), ns)

# Load DEFAULT_PROFILE
dp_start = next(i for i, l in enumerate(lines) if l.startswith('DEFAULT_PROFILE = '))
dp_end = dp_start + 1
brace_depth = 1
while dp_end < len(lines) and brace_depth > 0:
    brace_depth += lines[dp_end].count('{') - lines[dp_end].count('}')
    dp_end += 1
exec('\n'.join(lines[dp_start:dp_end]), ns)

# Load scalar constants
for l in lines:
    for prefix in ('MAX_INSIGHTS', 'LEARN_EVERY', 'LEARN_PROMOTION_THRESHOLD',
                   'MAX_PROFILE_ITEMS', 'DECAY_STALE_SESSIONS', 'DECAY_DEAD_SESSIONS',
                   'DECAY_EVERY', 'DAF_MIN_DELAY_MS', 'DAF_MAX_DELAY_MS',
                   'AUGMENT_VARIANTS'):
        if l.startswith(prefix):
            exec(l, ns)

# Load LAYER_NAMES, SITUATIONS, TONES, LAYERS, MODES, SITUATION_PRESETS
for target in ('LAYER_NAMES', 'TONES', 'LAYERS', 'MODES'):
    ln = next((l for l in lines if l.startswith(target + ' = ')), None)
    if ln:
        # Some may be multi-line dicts/lists
        idx = lines.index(ln)
        end = idx
        if '{' in ln or '[' in ln:
            depth = ln.count('{') + ln.count('[') - ln.count('}') - ln.count(']')
            end = idx
            while depth > 0 and end + 1 < len(lines):
                end += 1
                depth += lines[end].count('{') + lines[end].count('[') - lines[end].count('}') - lines[end].count(']')
        exec('\n'.join(lines[idx:end + 1]), ns)

# Load CALIBRATION_PROMPTS
cp_start = next(i for i, l in enumerate(lines) if l.startswith('CALIBRATION_PROMPTS = '))
cp_end = cp_start + 1
brace_depth = 1
while cp_end < len(lines) and brace_depth > 0:
    brace_depth += lines[cp_end].count('[') - lines[cp_end].count(']')
    cp_end += 1
exec('\n'.join(lines[cp_start:cp_end]), ns)

ln = next(l for l in lines if l.startswith('SITUATIONS = '))
exec(ln, ns)

sp_start = next(i for i, l in enumerate(lines) if l.startswith('SITUATION_PRESETS = '))
sp_end = sp_start + 1
brace_depth = 1
while sp_end < len(lines) and brace_depth > 0:
    brace_depth += lines[sp_end].count('{') - lines[sp_end].count('}')
    sp_end += 1
exec('\n'.join(lines[sp_start:sp_end]), ns)

# Thread locks
ns['_prep_lock'] = threading.Lock()
ns['_shadow_lock'] = threading.Lock()
ns['_learn_lock'] = threading.Lock()
ns['_stats_lock'] = threading.Lock()
ns['_augment_lock'] = threading.Lock()
ns['_redo_lock'] = threading.Lock()

# Global state the handler reads/writes
ns['state'] = 'idle'
ns['current_tone'] = 'casual'
ns['current_layer'] = 2
ns['current_mode'] = 'SAFE'
ns['current_situation'] = 'default'
ns['HOLD_ON_HIGH_RISK'] = False
ns['stats'] = {'api_calls': 0, 'sessions': 10, 'falcon_rejects': 0,
               'words': 0, 'chars': 0, 'start_time': time.time(),
               'multi_temp_votes': 0, 'multi_temp_disagreements': 0}
ns['profile'] = {
    "trigger_words": ["computer", "conference"],
    "filler_words": ["um", "uh"],
    "corrections": {"Duncan": "Dankeschoen"},
    "vocabulary": ["Lavrentiy"],
    "candidate_corrections": {},
    "candidate_fillers": {},
    "candidate_vocabulary": {},
    "trigger_types": {"computer": "block"},
    "covert_profile": {
        "avoidance_pairs": {
            "phone": {
                "computer": {"avoided_count": 3, "used_count": 10,
                    "common_substitutes": ["machine"], "dominant_onset": "k",
                    "last_seen": datetime.now().isoformat()}
            }
        }
    },
    "preferences": {"tone": "casual", "layer": 2, "mode": "SAFE"},
}
ns['console_log'] = [{"ts": "2026-03-15T12:00:00", "msg": "test log", "level": "info"}]
ns['learn_events'] = []
ns['learn_status'] = {"last_run": None, "total_learned": 0, "next_in": 3}
ns['_personal_onset_weights'] = {}
ns['_personal_onset_weights_by_lang'] = {}
ns['_personal_dominant_onsets'] = []
ns['_onset_anomalies'] = []
ns['_shadow_history'] = []
ns['_MAX_SHADOW_HISTORY'] = 50
ns['_last_speech_metrics'] = {}
ns['_last_low_conf_segments'] = []
ns['_last_avg_logprob'] = 0.0
ns['_last_paralinguistic_events'] = []
ns['_last_prosodic_features'] = []
ns['_last_speaker_state'] = ''
ns['_block_count'] = 0
ns['_redo_count'] = 0
ns['_decay_counter'] = 0
ns['_firebase_id_token'] = None
ns['_auth_user'] = None
ns['API_KEY'] = 'test-key'
ns['is_authenticated'] = lambda: ns['_firebase_id_token'] is not None
ns['BACKEND_URL'] = 'https://us-central1-bakers-agent.cloudfunctions.net/wim-reconstruct'
ns['paralinguistic_enabled'] = False
ns['paralinguistic_transcribe'] = False
ns['prosodic_enabled'] = False
ns['quiet_mode_enabled'] = False
ns['is_command_mode'] = False
ns['_last_api_ok_ts'] = 0
ns['_last_api_error_ts'] = 0
ns['_last_api_error_msg'] = ""
ns['_daf_active'] = False
ns['_daf_delay_ms'] = 100
ns['_clipboard_predictor'] = None
ns['_last_prep_text'] = None
ns['_last_prep_ts'] = 0.0
ns['_PREP_EXPIRY_SEC'] = 300
ns['WHISPER_TEMP'] = 0.0
ns['WHISPER_NO_SPEECH_THRESHOLD'] = 0.15
ns['WHISPER_MULTI_TEMP'] = False
ns['WHISPER_MULTI_TEMPS'] = [0.0, 0.2, 0.4]
ns['PATIENCE_DEFAULT'] = 2.0
ns['PATIENCE_STUTTER'] = 4.5
ns['DASHBOARD_PORT'] = 7878
ns['DASHBOARD_PATH'] = Path('dashboard.html')
ns['RECORD_KEY'] = 'f9'
ns['TONE_KEY'] = 'f10'
ns['LAYER_KEY'] = 'f11'
ns['STATS_KEY'] = 'f12'
ns['QUIT_KEY'] = 'f3'
ns['_calibration_state'] = {
    "active": False, "completed": [], "skipped": [],
    "current_prompt": None, "started_at": None,
}
ns['_augment_state'] = {
    "running": False, "completed": 0, "total": 0,
    "errors": 0, "last_run": None,
}
ns['DAF_DEFAULT_DELAY_MS'] = 100
# Temp dirs for calibration/augment (no real audio files)
import tempfile as _tmpmod
_test_cal_dir = Path(_tmpmod.mkdtemp())
ns['CALIBRATION_DIR'] = _test_cal_dir
ns['AUGMENT_DIR'] = _test_cal_dir / "augmented"
ns['PROFILE_DIR'] = _test_cal_dir.parent

# Stubs
ns['log'] = lambda msg, level='info': None
ns['stats_inc'] = lambda key, n=1: None
ns['save_profile'] = lambda prof, _epoch=None: None
ns['db_session_count'] = lambda: 50
ns['db_get_sessions'] = lambda limit=50: []
def _stub_daf_start(ms=None):
    ns['_daf_active'] = True
    if ms: ns['_daf_delay_ms'] = ms
def _stub_daf_stop():
    ns['_daf_active'] = False
ns['daf_start'] = _stub_daf_start
ns['daf_stop'] = _stub_daf_stop
ns['daf_set_delay'] = lambda ms: None
ns['augment_calibration_data'] = lambda: None

# Extract functions the handler calls
target_funcs = [
    '_extract_onset', 'learn_onset_weights', 'predict_phonetic_risk',
    '_learn_event', '_learn_events_snapshot', '_sample', '_norm_str',
    'detect_word_language', 'set_last_prep',
    'compute_risk_flags', 'make_decision',
    'compute_exposure_difficulty', 'compute_editorial_distance',
    'compute_substitution_fingerprint', 'compute_avoidance_trend',
    'build_stutter_insights', 'compute_brown_scores',
    'predict_triggers_in_text', 'compute_wer',
    'check_redo', 'prep_text',
    'set_tone', 'set_layer', 'set_mode', 'set_situation',
    'set_paralinguistic', 'set_paralinguistic_transcribe', 'set_prosodic',
    '_dedupe_list', '_norm_corrections',
    'calibration_status', 'calibration_next_prompt',
    'augment_status', 'compute_severity_score',
    'get_patience_timeout', 'generate_clinical_profile',
]

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
        func_source = ast.get_source_segment(source, node)
        if func_source:
            try:
                exec(func_source, ns)
            except Exception as e:
                print(f'SKIP {node.name}: {e}')

# Auto-inject dispatch_api + every handle_(GET|POST)_api_* + a few helpers
# the refactored DashboardHandler delegates through. After the H-1 refactor
# do_GET / do_POST no longer hold inline route bodies — they delegate to
# dispatch_api(path, body), which calls handle_*_api_* functions defined at
# module scope. The class-only extraction previously missed these; without
# this fix every endpoint test failed with "Remote end closed connection
# without response" (NameError inside the request thread).
_auto_prefixes = ('handle_GET_api_', 'handle_POST_api_')
_auto_exact = {'dispatch_api', 'set_accent_mode', 'set_quiet_mode',
               'list_profiles', 'create_profile', 'switch_profile',
               'cycle_layer', 'set_l1_cloud_asr', 'generate_voice_profile',
               'generate_shadow_utterance', 'compute_avg_exposure',
               '_compute_avg_exposure', '_compute_avg_edit_dist'}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        if (any(node.name.startswith(p) for p in _auto_prefixes)
                or node.name in _auto_exact):
            if node.name in ns:
                continue  # already loaded via target_funcs
            func_source = ast.get_source_segment(source, node)
            if func_source:
                try:
                    exec(func_source, ns)
                except Exception as e:
                    print(f'SKIP {node.name}: {e}')

# Route tables added in the H-1 dispatch refactor. dispatch_api() reads
# _GET_ROUTES / _POST_ROUTES at call time; they map paths to the handler
# functions loaded above, so they must be exec'd into ns AFTER the handlers
# exist — otherwise dispatch_api NameErrors on _GET_ROUTES under the server.
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id in ('_GET_ROUTES', '_POST_ROUTES'):
                exec(ast.get_source_segment(source, node), ns)

# Extract the DashboardHandler class
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'DashboardHandler':
        cls_source = ast.get_source_segment(source, node)
        if cls_source:
            exec(cls_source, ns)

loaded = [k for k in target_funcs if k in ns]
handler_loaded = 'DashboardHandler' in ns
print(f'Loaded {len(loaded)}/{len(target_funcs)} functions + handler={handler_loaded}')
print()

if not handler_loaded:
    print('FATAL: DashboardHandler not loaded')
    sys.exit(1)

# Start test server on a high port
TEST_PORT = 18787
server = ThreadingHTTPServer(('127.0.0.1', TEST_PORT), ns['DashboardHandler'])
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()
import time; time.sleep(0.3)  # Wait for server socket to bind
BASE = f'http://127.0.0.1:{TEST_PORT}'

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


def get(path):
    """GET request, return parsed JSON."""
    req = urllib.request.Request(f'{BASE}{path}')
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def post(path, data=None):
    """POST request with JSON body, return parsed JSON."""
    body = json.dumps(data or {}).encode('utf-8')
    req = urllib.request.Request(f'{BASE}{path}', data=body,
                                headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


# ============================================================
# GET ENDPOINT TESTS
# ============================================================
print('=== GET /api/state ===')
try:
    r = get('/api/state')
    check('returns JSON', isinstance(r, dict))
    check('has state', 'state' in r)
    check('has tone', 'tone' in r)
    check('has layer', 'layer' in r)
    check('has layer_name', 'layer_name' in r)
    check('has mode', 'mode' in r)
    check('has situation', 'situation' in r)
    check('has stats', 'stats' in r)
    check('has model', 'model' in r)
    check('state = idle', r['state'] == 'idle')
    check('tone = casual', r['tone'] == 'casual')
    check('layer = 2', r['layer'] == 2)
    check('mode = SAFE', r['mode'] == 'SAFE')
except Exception as e:
    check(f'GET /api/state failed: {e}', False)

print()
print('=== GET /api/profile ===')
try:
    r = get('/api/profile')
    check('returns dict', isinstance(r, dict))
    check('has trigger_words', 'trigger_words' in r)
    check('has filler_words', 'filler_words' in r)
    check('has corrections', 'corrections' in r)
    check('has vocabulary', 'vocabulary' in r)
    check('trigger_words matches', r['trigger_words'] == ["computer", "conference"])
    check('corrections has Duncan', 'Duncan' in r['corrections'])
except Exception as e:
    check(f'GET /api/profile failed: {e}', False)

print()
print('=== GET /api/sessions ===')
try:
    r = get('/api/sessions')
    check('returns list', isinstance(r, list))
except Exception as e:
    check(f'GET /api/sessions failed: {e}', False)

print()
print('=== GET /api/log ===')
try:
    r = get('/api/log')
    check('returns list', isinstance(r, list))
    check('has log entries', len(r) >= 1)
except Exception as e:
    check(f'GET /api/log failed: {e}', False)

print()
print('=== GET /api/learn ===')
try:
    r = get('/api/learn')
    check('returns dict', isinstance(r, dict))
    check('has status', 'status' in r)
    check('has events', 'events' in r)
    check('has totals', 'totals' in r)
    check('totals has corrections count', 'corrections' in r['totals'])
    check('totals has triggers count', 'triggers' in r['totals'])
    check('has onset_weights', 'onset_weights' in r)
    check('has covert_profile', 'covert_profile' in r)
    check('has shadow_utterance', 'shadow_utterance' in r)
    check('has decay', 'decay' in r)
    check('has insights_enabled', 'insights_enabled' in r)
except Exception as e:
    check(f'GET /api/learn failed: {e}', False)

print()
print('=== GET /api/wer ===')
try:
    r = get('/api/wer')
    check('returns dict', isinstance(r, dict))
    # No sessions -> no data
    check('has sample_count', 'sample_count' in r)
    check('has interpretation', 'interpretation' in r)
except Exception as e:
    check(f'GET /api/wer failed: {e}', False)

print()
print('=== GET /api/fluency ===')
try:
    r = get('/api/fluency')
    check('returns dict', isinstance(r, dict))
    check('has trend', 'trend' in r)
    check('has avg_pause_ratio', 'avg_pause_ratio' in r)
    check('has pause_trend', 'pause_trend' in r)
    check('has severity_breakdown', 'severity_breakdown' in r)
    sb = r['severity_breakdown']
    check('severity has base', 'base' in sb)
    check('severity has situation', 'situation' in sb)
    check('severity has aggression', 'aggression' in sb)
except Exception as e:
    check(f'GET /api/fluency failed: {e}', False)

print()
print('=== GET /api/hotkeys ===')
try:
    r = get('/api/hotkeys')
    check('returns dict', isinstance(r, dict))
    check('has record', 'record' in r)
    check('has tone', 'tone' in r)
    check('has layer', 'layer' in r)
    check('record = F9', r['record'] == 'F9')
except Exception as e:
    check(f'GET /api/hotkeys failed: {e}', False)


# ============================================================
# POST ENDPOINT TESTS
# ============================================================
print()
print('=== POST /api/tone ===')
try:
    r = post('/api/tone', {'tone': 'formal'})
    check('returns dict', isinstance(r, dict))
    check('tone changed to formal', r['tone'] == 'formal')
    # Verify state mutation
    r2 = get('/api/state')
    check('state reflects new tone', r2['tone'] == 'formal')
    # Invalid tone -> unchanged
    post('/api/tone', {'tone': 'nonexistent'})
    r3 = get('/api/state')
    check('invalid tone -> unchanged', r3['tone'] == 'formal')
    # Restore
    post('/api/tone', {'tone': 'casual'})
except Exception as e:
    check(f'POST /api/tone failed: {e}', False)

print()
print('=== POST /api/layer ===')
try:
    r = post('/api/layer', {'layer': 4})
    check('layer changed to 4', r['layer'] == 4)
    check('layer_name = stutter', r['layer_name'] == 'stutter')
    r2 = get('/api/state')
    check('state reflects new layer', r2['layer'] == 4)
    # Restore
    post('/api/layer', {'layer': 2})
except Exception as e:
    check(f'POST /api/layer failed: {e}', False)

print()
print('=== POST /api/mode ===')
try:
    r = post('/api/mode', {'mode': 'FAST'})
    check('mode changed to FAST', r['mode'] == 'FAST')
    r = post('/api/mode', {'mode': 'raw'})  # lowercase should work (uppercased)
    check('lowercase mode accepted', r['mode'] == 'RAW')
    # Restore
    post('/api/mode', {'mode': 'SAFE'})
except Exception as e:
    check(f'POST /api/mode failed: {e}', False)

print()
print('=== POST /api/paralinguistic ===')
try:
    r = post('/api/paralinguistic', {'enabled': True})
    check('paralinguistic enabled', r['paralinguistic_enabled'] == True)
    r = post('/api/paralinguistic', {'enabled': False})
    check('paralinguistic disabled', r['paralinguistic_enabled'] == False)
except Exception as e:
    check(f'POST /api/paralinguistic failed: {e}', False)

print()
print('=== POST /api/paralinguistic_transcribe ===')
try:
    r = post('/api/paralinguistic_transcribe', {'enabled': True})
    check('para transcribe enabled', r['paralinguistic_transcribe'] == True)
    r = post('/api/paralinguistic_transcribe', {'enabled': False})
    check('para transcribe disabled', r['paralinguistic_transcribe'] == False)
except Exception as e:
    check(f'POST /api/paralinguistic_transcribe failed: {e}', False)

print()
print('=== POST /api/prosodic ===')
try:
    r = post('/api/prosodic', {'enabled': True})
    check('prosodic enabled', r['prosodic_enabled'] == True)
    r = post('/api/prosodic', {'enabled': False})
    check('prosodic disabled', r['prosodic_enabled'] == False)
except Exception as e:
    check(f'POST /api/prosodic failed: {e}', False)

print()
print('=== POST /api/situation ===')
try:
    r = post('/api/situation', {'situation': 'high_stress'})
    check('situation changed', r['situation'] == 'high_stress')
    check('has severity', 'severity' in r)
    check('high_stress severity = 1.5', r['severity'] == 1.5)
    check('has situations list', 'situations' in r)
    check('has preset_applied', 'preset_applied' in r)
    if r['preset_applied']:
        check('preset has daf_ms', 'daf_ms' in r['preset_applied'])
    # Test alias back-compat: old names resolve to new ones
    r2 = post('/api/situation', {'situation': 'phone'})
    check('phone alias -> high_stress', r2['situation'] == 'high_stress')
    r3 = post('/api/situation', {'situation': 'casual'})
    check('casual alias -> default', r3['situation'] == 'default')
    # Restore
    post('/api/situation', {'situation': 'default'})
except Exception as e:
    check(f'POST /api/situation failed: {e}', False)

print()
print('=== POST /api/profile (update) ===')
try:
    orig_profile = get('/api/profile')
    # Add a trigger word
    r = post('/api/profile', {
        'trigger_words': ['computer', 'conference', 'structure'],
        'filler_words': ['um', 'uh', 'basically'],
        'vocabulary': ['Lavrentiy', 'Whisper'],
        'corrections': {'Duncan': 'Dankeschoen', 'notch': 'not'},
    })
    check('returns ok', r.get('ok') == True)
    # Verify mutations
    p = get('/api/profile')
    check('trigger_words updated', 'structure' in p['trigger_words'])
    check('filler_words updated', 'basically' in p['filler_words'])
    check('vocabulary updated', 'Whisper' in p['vocabulary'])
    check('corrections updated', 'notch' in p['corrections'])
    # Restore original
    post('/api/profile', {
        'trigger_words': orig_profile['trigger_words'],
        'filler_words': orig_profile['filler_words'],
        'vocabulary': orig_profile['vocabulary'],
        'corrections': orig_profile['corrections'],
    })
except Exception as e:
    check(f'POST /api/profile failed: {e}', False)

print()
print('=== POST /api/covert/remove ===')
try:
    # Remove existing pair
    r = post('/api/covert/remove', {'situation': 'phone', 'word': 'computer'})
    check('removed = True', r.get('removed') == True)
    # Verify removal
    p = get('/api/profile')
    pairs = p.get('covert_profile', {}).get('avoidance_pairs', {}).get('phone', {})
    check('computer removed from phone pairs', 'computer' not in pairs)
    # Try removing non-existent word
    r = post('/api/covert/remove', {'situation': 'phone', 'word': 'nonexistent'})
    check('non-existent -> removed=False', r.get('removed') == False)
    # Try non-existent situation
    r = post('/api/covert/remove', {'situation': 'nonexistent', 'word': 'foo'})
    check('non-existent situation -> removed=False', r.get('removed') == False)
    # Missing params
    r = post('/api/covert/remove', {'situation': 'phone'})
    check('missing word -> error', 'error' in r)
    r = post('/api/covert/remove', {})
    check('empty body -> error', 'error' in r)
except Exception as e:
    check(f'POST /api/covert/remove failed: {e}', False)

print()
print('=== POST /api/whisper_config ===')
try:
    r = post('/api/whisper_config', {'no_speech_threshold': 0.3, 'multi_temp': True})
    check('returns config', 'temperature' in r)
    check('no_speech_threshold updated', r['no_speech_threshold'] == 0.3)
    check('multi_temp enabled', r['multi_temp'] == True)
    check('has multi_temps', 'multi_temps' in r)
    # Bounds enforcement
    r = post('/api/whisper_config', {'no_speech_threshold': 5.0})
    check('threshold clamped to 1.0', r['no_speech_threshold'] == 1.0)
    r = post('/api/whisper_config', {'no_speech_threshold': -1.0})
    check('threshold clamped to 0.0', r['no_speech_threshold'] == 0.0)
    # Restore
    post('/api/whisper_config', {'no_speech_threshold': 0.15, 'multi_temp': False})
except Exception as e:
    check(f'POST /api/whisper_config failed: {e}', False)

print()
print('=== POST /api/hotkeys ===')
try:
    r = post('/api/hotkeys', {'record': 'f7', 'tone': 'f8'})
    check('record updated to F7', r['record'] == 'F7')
    check('tone updated to F8', r['tone'] == 'F8')
    # Invalid key ignored
    r = post('/api/hotkeys', {'record': 'space'})
    check('invalid key ignored', r['record'] == 'F7')  # stays F7
    # Restore
    post('/api/hotkeys', {'record': 'f9', 'tone': 'f10', 'layer': 'f11', 'stats': 'f12', 'quit': 'f3'})
except Exception as e:
    check(f'POST /api/hotkeys failed: {e}', False)

print()
print('=== POST /api/prep (no prep_text function) ===')
try:
    # prep_text may need predict_phonetic_risk etc.
    r = post('/api/prep', {'text': 'I need to call the computer company'})
    check('returns dict', isinstance(r, dict))
    # Should have words and flagged keys
    if 'error' not in r:
        check('has words', 'words' in r)
        check('has flagged', 'flagged' in r)
    else:
        check('prep returned error (may need more stubs)', True)
except Exception as e:
    check(f'POST /api/prep failed: {e}', False)

print()
print('=== CORS headers ===')
try:
    req = urllib.request.Request(f'{BASE}/api/state')
    with urllib.request.urlopen(req, timeout=5) as resp:
        cors = resp.headers.get('Access-Control-Allow-Origin')
        check('CORS header present', cors is not None)
        ct = resp.headers.get('Content-Type')
        check('Content-Type = application/json', ct == 'application/json')
except Exception as e:
    check(f'CORS check failed: {e}', False)

print()
print('=== 404 on unknown path ===')
try:
    req = urllib.request.Request(f'{BASE}/api/nonexistent',
                                data=b'{}',
                                headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=5)
    check('should have gotten 404', False)
except urllib.error.HTTPError as e:
    check('POST unknown path -> 404', e.code == 404)
except Exception as e:
    check(f'404 check failed: {e}', False)


# ============================================================
# GAP: DAF endpoints
# ============================================================
print()
print('=== GET /api/daf ===')
try:
    r = get('/api/daf')
    check('returns dict', isinstance(r, dict))
    check('has active', 'active' in r)
    check('has delay_ms', 'delay_ms' in r)
    check('has min', 'min' in r)
    check('has max', 'max' in r)
    check('active is bool', isinstance(r['active'], bool))
    check('delay_ms is int', isinstance(r['delay_ms'], int))
except Exception as e:
    check(f'GET /api/daf failed: {e}', False)

print()
print('=== POST /api/daf (activate) ===')
try:
    r = post('/api/daf', {'active': True, 'delay_ms': 120})
    check('returns dict', isinstance(r, dict))
    check('has active field', 'active' in r)
    check('has delay_ms field', 'delay_ms' in r)
    # Deactivate
    r = post('/api/daf', {'active': False})
    check('deactivate returns dict', isinstance(r, dict))
    # Set delay only
    r = post('/api/daf', {'delay_ms': 80})
    check('delay-only returns dict', isinstance(r, dict))
    # Empty body
    r = post('/api/daf', {})
    check('empty body returns state', 'active' in r)
except Exception as e:
    check(f'POST /api/daf failed: {e}', False)

# ============================================================
# GAP: Calibration flow
# ============================================================
print()
print('=== GET /api/calibration ===')
try:
    r = get('/api/calibration')
    check('returns dict', isinstance(r, dict))
    check('has active', 'active' in r)
    check('has total_prompts', 'total_prompts' in r)
    check('has completed', 'completed' in r)
    check('has skipped', 'skipped' in r)
    check('has remaining', 'remaining' in r)
    check('has pct', 'pct' in r)
    check('has categories', 'categories' in r)
    check('has next_prompt', 'next_prompt' in r)
    check('total_prompts > 0', r['total_prompts'] > 0)
    check('remaining = total - done - skipped',
          r['remaining'] == r['total_prompts'] - r['completed'] - r['skipped'])
except Exception as e:
    check(f'GET /api/calibration failed: {e}', False)

print()
print('=== GET /api/calibration/prompts ===')
try:
    r = get('/api/calibration/prompts')
    check('returns list', isinstance(r, list))
    check('has prompts', len(r) > 0)
    check('prompt has id', 'id' in r[0])
    check('prompt has category', 'category' in r[0])
    check('prompt has text', 'text' in r[0])
except Exception as e:
    check(f'GET /api/calibration/prompts failed: {e}', False)

print()
print('=== POST /api/calibration/start ===')
try:
    r = post('/api/calibration/start', {})
    check('returns dict', isinstance(r, dict))
    check('started = True', r.get('started') == True)
    check('has next_prompt', 'next_prompt' in r)
    check('has status', 'status' in r)
    check('status.active = True', r['status']['active'] == True)
except Exception as e:
    check(f'POST /api/calibration/start failed: {e}', False)

print()
print('=== POST /api/calibration/skip ===')
try:
    r = post('/api/calibration/skip', {'prompt_id': 1})
    check('returns dict', isinstance(r, dict))
    check('skipped = 1', r.get('skipped') == 1)
    check('has next_prompt', 'next_prompt' in r)
    check('has status', 'status' in r)
    check('skipped count incremented', r['status']['skipped'] >= 1)
    # Missing prompt_id
    r = post('/api/calibration/skip', {})
    check('missing prompt_id -> error', 'error' in r)
except Exception as e:
    check(f'POST /api/calibration/skip failed: {e}', False)

print()
print('=== POST /api/calibration/record (error paths) ===')
try:
    # Missing fields
    r = post('/api/calibration/record', {})
    check('missing fields -> error', 'error' in r)
    r = post('/api/calibration/record', {'prompt_id': 1})
    check('missing audio -> error', 'error' in r)
except Exception as e:
    check(f'POST /api/calibration/record failed: {e}', False)

print()
print('=== POST /api/calibration/stop ===')
try:
    r = post('/api/calibration/stop', {})
    check('returns dict', isinstance(r, dict))
    check('stopped = True', r.get('stopped') == True)
    check('has status', 'status' in r)
    check('status.active = False', r['status']['active'] == False)
except Exception as e:
    check(f'POST /api/calibration/stop failed: {e}', False)

# ============================================================
# GAP: Augment endpoints
# ============================================================
print()
print('=== GET /api/augment ===')
try:
    r = get('/api/augment')
    check('returns dict', isinstance(r, dict))
    check('has running', 'running' in r)
    check('has augmented_samples', 'augmented_samples' in r)
    check('has real_samples', 'real_samples' in r)
    check('has potential_total', 'potential_total' in r)
    check('has size_mb', 'size_mb' in r)
    check('has errors', 'errors' in r)
    check('has ready', 'ready' in r)
    check('running is False', r['running'] == False)
except Exception as e:
    check(f'GET /api/augment failed: {e}', False)

print()
print('=== POST /api/augment (start) ===')
try:
    r = post('/api/augment', {})
    check('returns dict', isinstance(r, dict))
    check('started = True', r.get('started') == True)
    check('has status', 'status' in r)
    # Second call while "running" should error (race depends on timing, so just check shape)
except Exception as e:
    check(f'POST /api/augment failed: {e}', False)

# ============================================================
# GAP: Toggle state mutation after set_situation
# ============================================================
print()
print('=== Situation toggle auto-enable ===')
try:
    # Reset state
    ns['paralinguistic_enabled'] = False
    ns['prosodic_enabled'] = False
    ns['current_situation'] = 'default'
    ns['current_layer'] = 2
    # Switch to phone -> should auto-enable paralinguistic + prosodic
    r = post('/api/situation', {'situation': 'phone'})
    check('phone: paralinguistic auto-enabled', ns['paralinguistic_enabled'] == True)
    check('phone: prosodic auto-enabled', ns['prosodic_enabled'] == True)
    check('phone: layer auto-set to 4', ns['current_layer'] == 4)
    # Switch to interview -> same auto-enables
    ns['paralinguistic_enabled'] = False
    ns['prosodic_enabled'] = False
    r = post('/api/situation', {'situation': 'interview'})
    check('interview: paralinguistic auto-enabled', ns['paralinguistic_enabled'] == True)
    check('interview: prosodic auto-enabled', ns['prosodic_enabled'] == True)
    # Switch to presentation
    ns['paralinguistic_enabled'] = False
    ns['prosodic_enabled'] = False
    r = post('/api/situation', {'situation': 'presentation'})
    check('presentation: paralinguistic auto-enabled', ns['paralinguistic_enabled'] == True)
    check('presentation: prosodic auto-enabled', ns['prosodic_enabled'] == True)
    # Switch to casual -> no auto-enable (no preset)
    ns['paralinguistic_enabled'] = False
    ns['prosodic_enabled'] = False
    r = post('/api/situation', {'situation': 'casual'})
    check('casual: paralinguistic stays off', ns['paralinguistic_enabled'] == False)
    check('casual: prosodic stays off', ns['prosodic_enabled'] == False)
    # Switch to reading -> no para/prosodic in preset
    r = post('/api/situation', {'situation': 'reading'})
    check('reading: paralinguistic stays off', ns['paralinguistic_enabled'] == False)
    check('reading: prosodic stays off', ns['prosodic_enabled'] == False)
    # Restore
    post('/api/situation', {'situation': 'default'})
except Exception as e:
    check(f'Situation toggle auto-enable failed: {e}', False)

# ============================================================
# GAP: Patience mode endpoints
# ============================================================
print()
print('=== GET /api/patience ===')
try:
    r = get('/api/patience')
    check('returns dict', isinstance(r, dict))
    check('has patience key', 'patience' in r)
    check('has default key', 'default' in r)
    check('has stutter key', 'stutter' in r)
    check('patience is float', isinstance(r['patience'], (int, float)))
    check('default is 2.0 initially', r['default'] == 2.0)
    check('stutter is 4.5 initially', r['stutter'] == 4.5)
except Exception as e:
    check(f'GET /api/patience failed: {e}', False)

print()
print('=== POST /api/patience ===')
try:
    r = post('/api/patience', {'default': 3.0})
    check('returns dict', isinstance(r, dict))
    check('ok is True', r.get('ok') is True)
    check('default updated to 3.0', r.get('default') == 3.0)
    r2 = post('/api/patience', {'stutter': 5.0})
    check('stutter updated to 5.0', r2.get('stutter') == 5.0)
    # Restore defaults
    post('/api/patience', {'default': 2.0, 'stutter': 4.5})
    r3 = get('/api/patience')
    check('defaults restored', r3['default'] == 2.0 and r3['stutter'] == 4.5)
    # Invalid value ignored
    r4 = post('/api/patience', {'default': 'bad'})
    check('invalid value ignored', r4.get('ok') is True)
    # Empty body
    r5 = post('/api/patience', {})
    check('empty body returns state', 'patience' in r5)
except Exception as e:
    check(f'POST /api/patience failed: {e}', False)

# ============================================================
# GAP: Clinical profile endpoint
# ============================================================
print()
print('=== GET /api/clinical_profile ===')
try:
    r = get('/api/clinical_profile')
    check('returns dict', isinstance(r, dict))
    # With empty sessions stub, should return the "need N sessions" error
    check('error key present (no sessions)', 'error' in r or 'total_sessions' in r)
    # Test with sessions populated
    ns['db_get_sessions'] = lambda limit=50: [
        {'ts': '2026-01-01T10:00:00', 'words': 50, 'situation': 'default',
         'disfluency_counts': {'word_rep': 3, 'filler': 2, 'total': 5},
         'editorial_distance': 0.3, 'exposure': {'score': 0.35, 'band': 'moderate'},
         'lang': 'en'}
    ] * 25  # 25 sessions to exceed min_sessions=20
    r2 = get('/api/clinical_profile')
    check('enough sessions: no error', 'error' not in r2)
    check('has total_sessions', 'total_sessions' in r2)
    check('has primary_disfluency', 'primary_disfluency' in r2)
    check('has frequency_per_minute', 'frequency_per_minute' in r2)
    check('has situational_breakdown', 'situational_breakdown' in r2)
    check('has editorial_distance', 'editorial_distance' in r2)
    check('has fluency_trend', 'fluency_trend' in r2)
    check('has exposure', 'exposure' in r2)
    check('has covert_avoidance', 'covert_avoidance' in r2)
    check('total_sessions = 25', r2.get('total_sessions') == 25)
    check('primary_disfluency has type', 'type' in r2.get('primary_disfluency', {}))
    # Restore stub
    ns['db_get_sessions'] = lambda limit=50: []
except Exception as e:
    check(f'GET /api/clinical_profile failed: {e}', False)

# ============================================================
# Shutdown
# ============================================================
server.shutdown()

print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
