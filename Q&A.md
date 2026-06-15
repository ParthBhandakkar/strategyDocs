# Q&A

## Which canonical module was implemented in this session?
`range_sweep_mss` (video 54, cluster Q) — the next missing canonical module per the recommended coding order in STRATEGY_DEDUP_FINDINGS.md.

## Why synthetic data for the backtest?
The cloud workspace has no MT5 server or local Exness history path. `BACKTEST_DATA_SOURCE=synthetic` generates reproducible OHLCV so the engine can run end-to-end; swap to `local` or `mt5` when real data is available.
