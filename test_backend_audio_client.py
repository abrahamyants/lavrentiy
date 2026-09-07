"""
Contract test: the desktop's authenticated audio upload against the backend's
own parser.

Since 2026-09-06 `_backend_audio_transcribe` sends the recording raw, as a
multipart `file` part — the envelope WiM Android sends and wim-reconstruct
revision 00043+ reads. This test stands up a local stand-in for the Cloud
Function that:

  1. parses the desktop's multipart body the way the function's `handle()`
     does (form fields as strings, the `file` part as bytes) and feeds the
     result through the REAL `wim/api/audio_backend.prepare_audio_request`,
     so a drift between the two repos fails here before it fails on a user;
  2. in "old revision" mode answers a multipart body with 400
     "Missing 'raw' field" — exactly what a pre-00043 function does — and
     checks the desktop resends the take once in the base64 JSON envelope.

The real lavrentiy module is imported with the same hardware stubs
test_endpoints.py uses. No network, no keys, no audio hardware.
"""
import base64
import email
import email.policy
import io
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "wim" / "api"))

from audio_backend import prepare_audio_request  # the real server-side parser

# --- hardware / OS stubs so the real engine imports on any box (see test_endpoints.py)
_fake_sd = MagicMock(name='sounddevice')
_FAKE_DEVICE = {'name': 'Fake Test Mic', 'max_input_channels': 2,
                'max_output_channels': 2, 'default_samplerate': 16000.0}
_fake_sd.query_devices = lambda index=None, kind=None: _FAKE_DEVICE if index is not None else [_FAKE_DEVICE]
_fake_sd.default = MagicMock()
_fake_sd.default.device = [0, 0]
sys.modules['sounddevice'] = _fake_sd
_fake_pyperclip = MagicMock(name='pyperclip')
_fake_pyperclip.paste = lambda: ""
sys.modules['pyperclip'] = _fake_pyperclip
for _name in ('soundfile', 'keyboard', 'pyautogui'):
    sys.modules[_name] = MagicMock(name=_name)
for _name in ('openai', 'numpy', 'scipy.signal'):
    try:
        __import__(_name)
    except Exception:
        pass
import ctypes
ctypes.windll = MagicMock(name='windll')
(Path.home() / ".lavrentiy" / "profiles" / "Default").mkdir(parents=True, exist_ok=True)

import lavrentiy
try:
    lavrentiy._clipboard_predictor.stop()
except Exception:
    pass
ns = lavrentiy.__dict__

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print("PASS:", label)
    else:
        failed += 1
        print("FAIL:", label)


# --- a stand-in for wim-reconstruct on localhost
class FakeFunction(BaseHTTPRequestHandler):
    """Replays the two envelopes `handle()` accepts, plus the old-revision answer."""
    old_revision = False           # True = pre-00043: multipart is invisible
    calls = []                     # (content_type, body_len, kwargs_or_None)

    def log_message(self, *a):     # keep the test output clean
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer test-token":
            FakeFunction.calls.append((ctype, len(raw), "401"))
            return self._reply(401, {"error": "Missing Authorization header"})
        if ctype.lower().startswith("multipart/form-data"):
            if FakeFunction.old_revision:
                # A function older than 00043 never looks at multipart: it
                # sees an empty JSON body and complains about the text field.
                FakeFunction.calls.append((ctype, len(raw), None))
                return self._reply(400, {"error": "Missing 'raw' field"})
            body, audio_bytes = self._parse_multipart(raw, ctype)
            kwargs, size, model = prepare_audio_request(body, audio_bytes=audio_bytes)
        else:
            body = json.loads(raw.decode("utf-8"))
            kwargs, size, model = prepare_audio_request(body)
        kwargs = dict(kwargs)
        kwargs["_file_bytes"] = kwargs.pop("file").read()
        FakeFunction.calls.append((ctype, len(raw), kwargs))
        return self._reply(200, {"text": " hello from the fake function ",
                                 "segments": [{"text": "hello", "avg_logprob": -0.1}],
                                 "model": model, "remaining": 299})

    @staticmethod
    def _parse_multipart(raw, ctype):
        """Form fields -> strings, the `file` part -> bytes, like handle() does."""
        msg = email.message_from_bytes(
            b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw,
            policy=email.policy.HTTP)
        body, audio = {}, b""
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if part.get_filename():
                if name == "file":
                    audio = part.get_payload(decode=True)
            else:
                body[name] = part.get_payload(decode=True).decode("utf-8")
        return body, audio

    def _reply(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFunction)
threading.Thread(target=server.serve_forever, daemon=True).start()
ns['BACKEND_URL'] = f"http://127.0.0.1:{server.server_address[1]}/"
ns['_firebase_id_token'] = "test-token"
ns['dictation_language'] = "es"
ns['log'] = lambda text, kind="info": print(f"   [engine log/{kind}] {text}")
stats_calls = []
ns['stats_inc'] = lambda key, n=1: stats_calls.append(key)

# A WAV the server's sniffer accepts, big enough that base64 overhead shows.
wav = b"RIFF" + (44 + 60000).to_bytes(4, "little") + b"WAVE" + bytes(range(256)) * 235
tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
tmp.write(wav)
tmp.close()

# --- 1. new revision: raw multipart, parsed by the real server code
FakeFunction.calls.clear()
out = ns['_backend_audio_transcribe'](tmp.name, 0.2, "Dr. Nwosu, Lavrentiy")
check("one request for the take", len(FakeFunction.calls) == 1)
ctype, body_len, kwargs = FakeFunction.calls[0]
check("goes up as multipart/form-data", ctype.startswith("multipart/form-data; boundary="))
check("server got the exact recording bytes", kwargs["_file_bytes"] == wav)
check("model whisper-1", kwargs["model"] == "whisper-1")
check("verbose segments for L4 confidence", kwargs["response_format"] == "verbose_json")
check("dictation language carried", kwargs["language"] == "es")
check("temperature carried as a number", abs(kwargs["temperature"] - 0.2) < 1e-9)
check("prompt carried", kwargs["prompt"] == "Dr. Nwosu, Lavrentiy")
wrapped_len = len(json.dumps({"audio_base64": base64.b64encode(wav).decode("ascii")}))
check(f"raw body smaller than base64 JSON ({body_len} < {wrapped_len} bytes)", body_len < wrapped_len)
check("text trimmed", out["text"] == "hello from the fake function")
check("segments passed through", out["segments"] and out["segments"][0]["text"] == "hello")
check("engine tag", out["engine"] == "backend-whisper-1")
check("stats counted once", stats_calls == ["api_calls", "cloud_transcriptions"])

# --- 2. old revision: 400 "Missing 'raw' field" -> one resend, base64 JSON
FakeFunction.calls.clear()
stats_calls.clear()
FakeFunction.old_revision = True
out = ns['_backend_audio_transcribe'](tmp.name, None, "")
check("exactly two requests: multipart, then the wrapped resend", len(FakeFunction.calls) == 2)
check("first was multipart", FakeFunction.calls[0][0].startswith("multipart/form-data"))
ctype2, _, kwargs2 = FakeFunction.calls[1]
check("resend is application/json", ctype2 == "application/json")
check("resend carries the same recording", kwargs2 and kwargs2["_file_bytes"] == wav)
check("resend keeps whisper-1 + verbose", kwargs2["model"] == "whisper-1" and kwargs2["response_format"] == "verbose_json")
check("resend default temperature 0.0", kwargs2["temperature"] == 0.0)
check("resend has no prompt when none given", "prompt" not in kwargs2)
check("take succeeded through the fallback", out["text"] == "hello from the fake function")
check("stats counted once, not per attempt", stats_calls == ["api_calls", "cloud_transcriptions"])
FakeFunction.old_revision = False

# --- 3. any other error still surfaces (no silent retry loop)
FakeFunction.calls.clear()
ns['_firebase_id_token'] = "stale-token"
try:
    ns['_backend_audio_transcribe'](tmp.name, 0.0, "")
    check("401 raises", False)
except Exception as e:
    check(f"401 raises, is not retried ({type(e).__name__}: {e})",
          len(FakeFunction.calls) == 1 and "401" in str(e))
ns['_firebase_id_token'] = "test-token"

# --- 4. size gate unchanged
big = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
big.write(b"RIFF" + b"\0" * (12 * 1024 * 1024 + 1))
big.close()
try:
    ns['_backend_audio_transcribe'](big.name, 0.0, "")
    check("12 MB gate", False)
except RuntimeError as e:
    check("12 MB gate still local, before any upload", "12 MB" in str(e) and not FakeFunction.calls[1:])
os.unlink(big.name)

os.unlink(tmp.name)
server.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
