"""Jude — the grounded AI tutor (Jude-01).

A self-contained module: nothing in ``edu_api.main`` imports it, so it adds no
route and cannot affect lessons, downloads, quizzes or sync. See
``docs/jude-01/`` for the architecture and for what is built versus designed.

Entry points:

* ``edu_api.tutor.factory.build_tutor_service`` — wire a service.
* ``edu_api.tutor.router.build_tutor_router`` — an unregistered FastAPI router.
* ``python -m edu_api.tutor.demo`` — the pipeline end to end on a mock model.
"""
