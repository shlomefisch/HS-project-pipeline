"""Writes the API description to web/openapi.json for client generation.

    python -m scripts.export_openapi
"""

import json
from pathlib import Path

from app.main import app

out = Path(__file__).resolve().parents[2] / "web" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2))
print(f"Wrote {out}")
