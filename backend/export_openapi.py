"""
Utility script to export the OpenAPI / Swagger specification to JSON and YAML files.
Usage:
    python backend/export_openapi.py
"""
import json
import sys
from pathlib import Path
import yaml

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app


def export_openapi():
    schema = app.openapi()

    json_path = BACKEND_DIR / "openapi.json"
    yaml_path = BACKEND_DIR / "openapi.yaml"

    # Export JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    # Export YAML
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, sort_keys=False)

    print(f"OpenAPI specification successfully exported to:")
    print(f"  - JSON: {json_path}")
    print(f"  - YAML: {yaml_path}")
    print(f"Total API Paths documented: {len(schema.get('paths', {}))}")


if __name__ == "__main__":
    export_openapi()

