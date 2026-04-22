"""Regenerate ``docs/openapi.json`` from the live FastAPI app.

Run ``python -m scripts.dump_openapi`` from the repo root. Overwrites
the checked-in snapshot; commit the diff as part of the PR that added
or changed the endpoint. The regression guard in
``tests/test_openapi_contract.py`` tolerates additive changes to the
spec so there's no need to run the dumper on every unrelated edit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.openapi.utils import get_openapi

from en_reader.app import app


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    spec = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    out.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(spec['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
