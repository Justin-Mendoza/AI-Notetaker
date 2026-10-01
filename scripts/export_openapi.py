"""Write the FastAPI schema used for frontend type generation."""

import json
from pathlib import Path

from app.main import app

root = Path(__file__).resolve().parents[1]
target = root / "docs" / "openapi.json"
target.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(target)
