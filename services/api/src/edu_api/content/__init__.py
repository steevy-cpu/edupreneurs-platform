"""Content format v2: contracts, validators, reference scoring, pack manifests.

Everything in this package is PURE (no database, no network, standard library
only), so the same rules can be run by the API, by ``scripts/build_pack.py``
and by tests, and can be ported line by line to the phone.

Nothing here is wired into what learners are served today: ``/v1/catalog``,
``/v1/lessons`` and ``app.sync_apply_operation`` are unchanged. See
``docs/overnight-2026-11-24/lanes/content.md``.
"""
