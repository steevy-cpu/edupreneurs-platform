"""Give a synthetic seed account a password you can type into the app (LOCAL only).

    uv run python scripts/dev_login.py student_a

Seed accounts have no password. This sets a fresh random one through the LOCAL
Auth admin API and prints the e-mail and password once. Nothing is stored.

Note: `make token` and the automated test-suites also assign random passwords
to these accounts, so run this again after running them.
"""

from __future__ import annotations

import secrets
import sys
from urllib.parse import urlsplit

import httpx

from dev_token import SEED_ACCOUNTS
from local_stack import LOCAL_HOSTS, read_env_file


def main(account: str) -> None:
    env = read_env_file()
    base = env["LOCAL_SUPABASE_URL"].rstrip("/")
    if urlsplit(base).hostname not in LOCAL_HOSTS:
        raise SystemExit("error: LOCAL_SUPABASE_URL is not this machine. Refusing to continue.")
    user_id, email = SEED_ACCOUNTS[account]
    password = secrets.token_urlsafe(12)
    secret_key = env["LOCAL_SUPABASE_SECRET_KEY"]
    httpx.put(
        f"{base}/auth/v1/admin/users/{user_id}",
        headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
        json={"password": password},
        timeout=10,
    ).raise_for_status()
    print(f"e-mail:   {email}")
    print(f"password: {password}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SEED_ACCOUNTS:
        raise SystemExit(f"usage: dev_login.py {{{'|'.join(SEED_ACCOUNTS)}}}")
    main(sys.argv[1])
