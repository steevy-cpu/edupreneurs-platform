#!/usr/bin/env bash
set -euo pipefail
test "$RUNNER_ENVIRONMENT" = github-hosted
test "$(git rev-parse HEAD)" = "$CANDIDATE"
test -z "${EDU_TEST_ALLOW_SHARED_STACK:-}"
test ! -e .env
mkdir -p "$EVIDENCE"
git rev-parse HEAD > "$EVIDENCE/commit.txt"
project="edu-qa-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
export QA_PROJECT="$project"
python3 - <<'PY'
import os
from pathlib import Path
p = Path("supabase/config.toml")
s = p.read_text()
for old, new in [('project_id = "mon-edupreneur"', f'project_id = "{os.environ["QA_PROJECT"]}"'),
                 ("port = 54322", "port = 41002"), ("port = 54321", "port = 41001"),
                 ("port = 54320", "port = 41003"), ("port = 54323", "port = 41004")]:
    if s.count(old) != 1:
        raise SystemExit(f"Unexpected base config for {old}")
    s = s.replace(old, new)
p.write_text(s)
PY
npm ci --no-fund --no-audit
uv sync --frozen
if docker ps -a --format '{{.Names}}' | grep -Fx "supabase_db_$project"; then exit 1; fi
make start >/dev/null
for pair in 'db 5432 41002' 'kong 8000 41001'; do
  read -r service internal external <<< "$pair"
  bindings=$(docker port "supabase_${service}_$project" "$internal/tcp")
  test -n "$bindings"
  while IFS= read -r binding; do test "${binding##*:}" = "$external"; done <<< "$bindings"
done
make db-reset >/dev/null
uv run python - <<'PY'
import os
from pathlib import Path
from urllib.parse import urlsplit
env = dict(line.split("=", 1) for line in Path(".env").read_text().splitlines() if line and not line.startswith("#") and "=" in line)
for key in ("LOCAL_ADMIN_DATABASE_URL", "EDU_DATABASE_URL", "LOCAL_SUPABASE_URL", "EDU_AUTH_ISSUER", "EDU_AUTH_JWKS_URL"):
    url = urlsplit(env[key])
    assert os.getenv(key, env[key]) == env[key], key
    assert url.hostname in {"127.0.0.1", "localhost"}, key
    assert url.port == (41002 if "DATABASE" in key else 41001), key
    assert not url.query and not url.fragment, key
print("Verified disposable database and Auth bindings before test execution")
PY
