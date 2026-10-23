from pathlib import Path
import re

root = Path(__file__).resolve().parent
keys = ["requestDate", "claimReceiveDate", "serviceFromDate", "serviceThruDate"]
pat = re.compile(r'"(' + "|".join(keys) + r')"\s*:\s*"[^"]*"')

count_files = 0
count_repl = 0
for p in root.rglob("*.bru"):
    if p.name in ("collection.bru", "folder.bru") or "environments" in p.parts:
        continue
    text = p.read_text(encoding="utf-8")
    def repl(m):
        return '"' + m.group(1) + '": "{{today}}"'

    new, n = pat.subn(repl, text)
    if n:
        p.write_text(new, encoding="utf-8")
        count_files += 1
        count_repl += n
        print(f"{n:3d}  {p.relative_to(root)}")

print(f"DONE files={count_files} replacements={count_repl}")
