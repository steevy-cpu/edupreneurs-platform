"""Learner self-service: profile edit, onboarding state, account lifecycle.

Every write goes through a ``SECURITY DEFINER`` function in the private
``account`` schema; the API role has no direct write privilege on any table.
"""
