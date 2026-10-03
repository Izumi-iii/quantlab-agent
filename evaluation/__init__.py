"""Evaluation cases and runner for the deterministic tool chain.

E01–E24 come from ``Docs/PROJECT_PLAN.md §13.3``. Cases marked
``status: deferred`` cannot be exercised without a real model and are
scheduled for M3. The runner executes every case whose ``status`` is
``"ready"`` and asserts the expected behavior recorded in
``cases.jsonl``.
"""
