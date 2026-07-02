"""
Preview state and redo guardrail tests.
Targets start/stop/update preview helpers and set_state coverage gap.
"""
import ast, io, sys, time, threading, os
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('lavrentiy.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
lines = source.split('\n')

# Build namespace with needed globals/constants
start_idx = next(i for i, l in enumerate(lines) if l.startswith('LANGUAGE = '))
end_idx = next(i for i, l in enumerate(lines) if '_personal_onset_weights_by_lang' in l and '=' in l)
ns = {'threading': threading, 'time': time, 'Path': Path, 'os': os}
exec('\n'.join(lines[start_idx:end_idx + 1]), ns)

# Locks/state used by preview helpers
ns['preview_lock'] = threading.Lock()
ns['preview_state'] = {"active": False, "text": "seed", "final_text": "seed_final", "updated_at": 0}
ns['_preview_worker'] = None
ns['log'] = lambda msg, level='info': None
ns['state'] = 'idle'

target_funcs = ['start_preview_stream', 'stop_preview_stream', 'update_preview_text', 'set_state']
# Load every module-level function, not just the enumerated targets — the
# tested functions call private helpers the old name filter omitted, causing
# NameErrors at call time. Defining a function never runs its body, so this is
# side-effect-free; the target list is kept only for the coverage report.
for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        func_source = ast.get_source_segment(source, node)
        if func_source:
            exec(func_source, ns)

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
# TEST 1: start_preview_stream guards when disabled
# ============================================================
print('=== TEST 1: start_preview_stream disabled ===')
start_preview = ns.get('start_preview_stream')
if start_preview:
    ns['LIVE_PREVIEW_ENABLED'] = False
    ns['PREVIEW_PROVIDER'] = "none"
    ns['preview_state'] = {"active": False, "text": "keep", "final_text": "keep_final", "updated_at": 0}
    start_preview()
    check('active unchanged', ns['preview_state']['active'] is False)
    check('text preserved', ns['preview_state']['text'] == "keep")
    check('final preserved', ns['preview_state']['final_text'] == "keep_final")
else:
    print('  SKIP: start_preview_stream not loaded')

# ============================================================
# TEST 2: start_preview_stream initializes state when enabled
# ============================================================
print()
print('=== TEST 2: start_preview_stream enabled ===')
if start_preview:
    ns['LIVE_PREVIEW_ENABLED'] = True
    ns['PREVIEW_PROVIDER'] = "stub"
    ns['preview_state'] = {"active": False, "text": "old", "final_text": "old_final", "updated_at": 0}
    start_preview()
    ps = ns['preview_state']
    check('active set true', ps['active'] is True)
    check('text cleared', ps['text'] == "" and ps['final_text'] == "")
    check('timestamp set', ps['updated_at'] > 0)

# ============================================================
# TEST 3: update_preview_text updates interim and final
# ============================================================
print()
print('=== TEST 3: update_preview_text ===')
update_preview = ns.get('update_preview_text')
if update_preview:
    ns['preview_state']['text'] = ""
    ns['preview_state']['final_text'] = ""
    update_preview("first draft")
    first_ts = ns['preview_state']['updated_at']
    check('interim text stored', ns['preview_state']['text'] == "first draft")
    check('final untouched on interim', ns['preview_state']['final_text'] == "")
    time.sleep(0.01)
    update_preview("final draft", is_final=True)
    second_ts = ns['preview_state']['updated_at']
    check('final text stored', ns['preview_state']['final_text'] == "final draft")
    check('timestamp advanced', second_ts >= first_ts)
else:
    print('  SKIP: update_preview_text not loaded')

# ============================================================
# TEST 4: stop_preview_stream deactivates but keeps text
# ============================================================
print()
print('=== TEST 4: stop_preview_stream ===')
stop_preview = ns.get('stop_preview_stream')
if stop_preview:
    ns['preview_state']['active'] = True
    ns['preview_state']['final_text'] = "final draft"
    stop_preview()
    check('active set false', ns['preview_state']['active'] is False)
    check('final text retained', ns['preview_state']['final_text'] == "final draft")
else:
    print('  SKIP: stop_preview_stream not loaded')

# ============================================================
# TEST 5: set_state updates global state
# ============================================================
print()
print('=== TEST 5: set_state ===')
set_state_fn = ns.get('set_state')
if set_state_fn:
    set_state_fn('processing')
    check('state updated', ns['state'] == 'processing')
    set_state_fn('idle')
    check('state reset', ns['state'] == 'idle')
else:
    print('  SKIP: set_state not loaded')

# ============================================================
# SUMMARY
# ============================================================
print()
print('=' * 40)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print('=' * 40)
sys.exit(1 if failed > 0 else 0)
