"""Write the API contract to packages/contracts/openapi.json.

    uv run python scripts/export_openapi.py          # regenerate
    uv run python scripts/export_openapi.py --check  # exit 1 if the file is stale

Needs no database and no secrets: placeholder settings are used only to build
the application object, and no request is ever made.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from edu_api.auth.jwks import StaticKeyProvider
from edu_api.config import Settings
from edu_api.main import create_app

TARGET = Path(__file__).resolve().parents[1] / "packages" / "contracts" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+asyncpg://unused@127.0.0.1:1/unused"),
        auth_issuer="http://127.0.0.1:54321/auth/v1",
        auth_jwks_url="http://127.0.0.1:54321/auth/v1/.well-known/jwks.json",
        _env_file=None,
    )
    return create_app(settings, key_provider=StaticKeyProvider({})).openapi()


def render() -> str:
    return json.dumps(build_openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    document = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != document:
            print("packages/contracts/openapi.json is out of date. Run `make openapi`.")
            raise SystemExit(1)
        print("openapi.json is up to date")
    else:
        TARGET.write_text(document, encoding="utf-8")
        print(f"wrote {TARGET}")
