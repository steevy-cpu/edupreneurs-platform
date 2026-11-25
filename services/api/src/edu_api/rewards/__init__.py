"""Rewards lane: server-authoritative Gold ledger, streaks and achievements.

Everything here is behind ``EDU_REWARDS_ENABLED`` (default off). The rules live
in PostgreSQL (schema ``rewards``); this package only calls them and reads the
caller's own rows.
"""
