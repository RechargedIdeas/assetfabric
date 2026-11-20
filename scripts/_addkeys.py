"""Dev helper: add/replace locale keys in locales/en.json keeping order (python scripts/_addkeys.py k=v ...)."""
import json, sys
from pathlib import Path
p = Path(__file__).resolve().parents[1] / "locales" / "en.json"
d = json.loads(p.read_text(encoding="utf-8"))
for a in sys.argv[1:]:
    k, v = a.split("=", 1)
    d[k] = v
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
