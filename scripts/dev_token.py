"""Print a real access token for one of the synthetic seed accounts (LOCAL only).

    uv run python scripts/dev_token.py student_a
    TOKEN=$(uv run python scripts/dev_token.py student_a)
    curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/v1/me

How it works: the seed accounts have no password. This script asks the LOCAL
Auth admin API to set a fresh random password, signs in with it, prints the
access token, and forgets the password. The token is short-lived (1 hour).
"""

from __future__ import annotations

import secrets
import sys

import httpx

from disposable import verify
from local_stack import read_env_file

SEED_ACCOUNTS = {
    "student_a": ("a0000000-0000-4000-8000-000000000001", "student.a@edupreneur.test"),
    "student_b": ("a0000000-0000-4000-8000-000000000002", "student.b@edupreneur.test"),
    "editor": ("a0000000-0000-4000-8000-000000000003", "editor@edupreneur.test"),
    "reviewer": ("a0000000-0000-4000-8000-000000000004", "reviewer@edupreneur.test"),
}


def issue_token(account: str, env: dict[str, str] | None = None) -> str:
    env = read_env_file() if env is None else env
    verify(env=env)
    base = env["LOCAL_SUPABASE_URL"]
    user_id, email = SEED_ACCOUNTS[account]
    password = secrets.token_urlsafe(32)
    secret_key = env["LOCAL_SUPABASE_SECRET_KEY"]
    with httpx.Client(timeout=10, trust_env=False) as client:
        client.put(
            f"{base}/auth/v1/admin/users/{user_id}",
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
            json={"password": password},
        ).raise_for_status()
        response = client.post(
            f"{base}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
            json={"email": email, "password": password},
        )
        response.raise_for_status()
        return str(response.json()["access_token"])


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SEED_ACCOUNTS:
        raise SystemExit(f"usage: dev_token.py {{{'|'.join(SEED_ACCOUNTS)}}}")
    print(issue_token(sys.argv[1]))
