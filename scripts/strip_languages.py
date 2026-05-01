"""Collapse I18N entries in dashboard.html to en-only.

Each entry like `key:{en:'X',ru:'Y',es:'Z',pt:'W',fr:'V'}` becomes
`key:{en:'X'}`. Apostrophes in values are escaped as \\' inside the
single-quoted JS string, and the regex's quoted-string class accounts for
that escape pattern.
"""
import re
from pathlib import Path

P = Path(r"C:/Users/georg/Documents/GitHub/lavrentiy/dashboard.html")

text = P.read_text(encoding="utf-8")

# Quoted JS string body — backslash-any OR non-quote.
QUOTED = r"(?:\\.|[^'])*"

# Match entry start through end of object literal.
# Keep only the en:'...' block; drop the rest before the closing }.
pattern = re.compile(
    r"(\b\w+:\{en:'" + QUOTED + r"')(?:,(?:ru|es|pt|fr):'" + QUOTED + r"')+\}"
)

count = [0]

def replacer(m):
    count[0] += 1
    return m.group(1) + "}"

new_text = pattern.sub(replacer, text)
P.write_text(new_text, encoding="utf-8")
print(f"Entries collapsed: {count[0]}")
