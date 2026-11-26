"""Jude-02A evaluation harness: an offline-first way to compare candidate models for Jude.

Lives outside the API package on purpose: nothing in ``edu_api`` imports it and
it adds no route. It reuses Jude-01's own pieces (lesson contracts, retrieval,
prompt template, provider interface, output validation, service) so a candidate
is measured against exactly what production would send and accept.

Run ``python benchmarks/jude-02a/evaluate.py --help``.
"""

from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = BENCH_ROOT / "dataset"
CONFIG_DIR = BENCH_ROOT / "config"
RESULTS_DIR = BENCH_ROOT / "results"
