"""Entitlements: the read side of the private ``billing`` schema.

What this package does
    * ``service``       reads the caller's own active grants (student API role, RLS);
    * ``schemas``       the response shape of ``GET /v1/entitlements``;
    * ``mock_provider`` a pure, in-process SIMULATED payment provider for tests.

What it deliberately does not do
    * It gates nothing. The catalogue, lesson and sync code never import it.
    * It cannot create, extend or revoke a grant: the database role the API
      logs in with has no write privilege in ``billing`` and may execute one
      read-only function there.
    * It makes no network call and imports no payment SDK.
"""
