"""Phase 6: demand forecasting.

A standalone batch pipeline (pandas + scikit-learn, no Spark/JVM) reading/
writing Parquet under `settings.forecasting_path` in MinIO — synthetic
history -> feature-engineered dataset -> baseline + secondary model ->
chronological evaluation -> champion selection -> future forecast. See
docs/phase-6-demand-forecasting.md and ADR 0006.
"""
