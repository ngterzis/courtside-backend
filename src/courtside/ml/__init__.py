"""Shared ML logic used by both request-time serving and offline training.

Living under `courtside` (the package shipped in the Lambda image) guarantees the
serving path and the training path compute features the same way — the single most
common source of train/serve skew. The offline pipeline in the top-level `ml/`
directory imports from here rather than re-implementing anything.
"""
