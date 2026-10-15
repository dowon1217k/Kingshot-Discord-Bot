"""Display-only translations; API values and component IDs remain unchanged."""
import json
from pathlib import Path

_CATALOG = json.loads((Path(__file__).parent / "locales" / "ko.json").read_text(encoding="utf-8"))

def tr(key, **values):
    return _CATALOG[key].format(**values)
