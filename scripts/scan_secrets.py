"""Check Git-index contents without printing credential values. Not a replacement for secret scanning services."""

import re
import subprocess

paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
patterns = [
    r"gsk_[A-Za-z0-9]{20,}",
    r"pa-[A-Za-z0-9_-]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]
bad = []
for path in filter(None, paths):
    if path.startswith(".env") and path != ".env.example":
        bad.append(path)
        continue
    content = subprocess.check_output(["git", "show", ":" + path]).decode(
        "utf-8", errors="ignore"
    )
    if any(re.search(pattern, content) for pattern in patterns):
        bad.append(path)
print("Credential scan: " + ("PASS" if not bad else "FAIL in " + ", ".join(bad)))
raise SystemExit(bool(bad))
