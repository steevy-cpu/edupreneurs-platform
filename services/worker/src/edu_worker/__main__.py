"""Run one worker process:

    uv run python -m edu_worker --kinds noop --exit-when-idle

Reads ``EDU_WORKER_DATABASE_URL`` from the environment (or the local ``.env``).
It refuses to start unless the database says the login is a worker login.
Stops gracefully on SIGINT / SIGTERM. Nothing installs or schedules it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path

import asyncpg

from edu_worker.handlers import default_handlers, test_handlers
from edu_worker.queue import JobQueue, plain_postgres_url
from edu_worker.runner import Worker


def _database_url() -> str:
    url = os.environ.get("EDU_WORKER_DATABASE_URL", "")
    env_file = Path(".env")
    if not url and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "EDU_WORKER_DATABASE_URL":
                url = value.strip()
    if not url:
        raise SystemExit("error: EDU_WORKER_DATABASE_URL is not set")
    return plain_postgres_url(url)


async def _main(args: argparse.Namespace) -> int:
    handlers = default_handlers()
    if args.test_handlers:
        handlers.update(test_handlers())
    if args.kinds:
        unknown = sorted(set(args.kinds) - set(handlers))
        if unknown:
            raise SystemExit(f"error: no handler for kind(s) {unknown}")
        handlers = {kind: handlers[kind] for kind in args.kinds}

    pool = await asyncpg.create_pool(
        _database_url(),
        min_size=1,
        max_size=args.concurrency + 2,
        timeout=10,
        server_settings={"application_name": "edu-worker"},
    )
    try:
        queue = JobQueue(pool)
        kind = await queue.session_kind()
        if kind != "worker":
            raise SystemExit(f"error: the database login is a '{kind}' login, not a worker login")
        worker = Worker(
            queue,
            handlers,
            concurrency=args.concurrency,
            lease_seconds=args.lease_seconds,
            poll_interval=args.poll_interval,
        )
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, worker.stop)
        return await worker.run(max_jobs=args.max_jobs, exit_when_idle=args.exit_when_idle)
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="edu_worker", description=__doc__)
    parser.add_argument("--kinds", nargs="+", help="job kinds to work on (default: all handlers)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--lease-seconds", type=int, default=60)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-jobs", type=int, default=None, help="exit after claiming this many")
    parser.add_argument(
        "--exit-when-idle", action="store_true", help="exit when the queue is empty"
    )
    parser.add_argument("--test-handlers", action="store_true", help="enable test_sleep/test_fail")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    claimed = asyncio.run(_main(args))
    logging.getLogger("edu_worker").info("claimed %d job(s)", claimed)


if __name__ == "__main__":
    main()
