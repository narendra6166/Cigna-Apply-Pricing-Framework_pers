"""Write today's YYYYMMDD into date fields so Bruno Body shows a real date.
Collection pre-request still overwrites these at Send time."""
from datetime import date
from pathlib import Path
import re

root = Path(__file__).resolve().parent
today = date.today().strftime("%Y%m%d")
keys = ["requestDate", "claimReceiveDate", "serviceFromDate", "serviceThruDate"]
pat = re.compile(r'"(' + "|".join(keys) + r')"\s*:\s*"[^"]*"')

count_files = 0
count_repl = 0
for p in root.rglob("*.bru"):
    if p.name in ("collection.bru", "folder.bru") or "environments" in p.parts:
        continue
    text = p.read_text(encoding="utf-8")

    def repl(m):
        return '"' + m.group(1) + '": "' + today + '"'

    new, n = pat.subn(repl, text)
    if n:
        p.write_text(new, encoding="utf-8")
        count_files += 1
        count_repl += n
        print(f"{n:3d}  {p.relative_to(root)}")

env = root / "environments" / "DEV.bru"
if env.exists():
    env_text = env.read_text(encoding="utf-8")
    env_new, n_env = re.subn(r"(^\s*today:\s*)\S+", r"\g<1>" + today, env_text, count=1, flags=re.M)
    if n_env:
        env.write_text(env_new, encoding="utf-8")
        print(f"  1  environments/DEV.bru (today={today})")

print(f"DONE today={today} files={count_files} replacements={count_repl}")
