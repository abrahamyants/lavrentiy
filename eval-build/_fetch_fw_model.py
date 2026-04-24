"""One-time installer staging script.

Downloads Systran/faster-whisper-large-v3-turbo model files directly via
stdlib urllib, bypassing huggingface_hub's httpx dependency (which is
broken on this machine's Python installs).

Resulting tree:
    eval-build/models/faster-whisper/large-v3-turbo/
        model.bin
        config.json
        tokenizer.json
        vocabulary.json
        preprocessor_config.json

This matches what the installer will ship into
    {app}/models/faster-whisper/large-v3-turbo/
and what fw_local._resolve_model_dir() looks for.
"""
import os
import sys
import urllib.request
from pathlib import Path

# Systran repo is gated (401) as of April 2026. deepdml's ct2 conversion
# is the current community-public mirror.
REPO = "deepdml/faster-whisper-large-v3-turbo-ct2"
BASE = f"https://huggingface.co/{REPO}/resolve/main"
FILES = [
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.json",
    "preprocessor_config.json",
]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

HERE = Path(__file__).resolve().parent
DEST = HERE / "models" / "faster-whisper" / "large-v3-turbo"
DEST.mkdir(parents=True, exist_ok=True)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fetch(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  SKIP (already present, {human(dest.stat().st_size)}): {dest.name}")
        return
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as r:
        total = int(r.headers.get("Content-Length", "0") or 0)
        done = 0
        last_pct = -5
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)  # 1 MB at a time
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total > 0:
                    pct = int(100 * done / total)
                    if pct >= last_pct + 5:
                        sys.stdout.write(f"    {pct}% ({human(done)} / {human(total)})\n")
                        sys.stdout.flush()
                        last_pct = pct
    print(f"  DONE ({human(dest.stat().st_size)}): {dest.name}")


def main():
    print(f"Staging {REPO} -> {DEST}")
    for fname in FILES:
        url = f"{BASE}/{fname}"
        dest = DEST / fname
        print(f"Fetching {fname}")
        try:
            fetch(url, dest)
        except urllib.error.HTTPError as e:
            if e.code == 404 and fname in ("vocabulary.json", "preprocessor_config.json"):
                print(f"  (404 — optional file, skipping)")
                continue
            raise
    print("ALL DONE")


if __name__ == "__main__":
    main()
