# Q&A

## Which canonical modules are still missing strategy files?

Eight modules from `strategy_videos_90.csv` have no `s{video}_*.py` file yet: `session_dol_fib`, `gold_judas_8pm`, `continuation_purge`, `us30_judas`, `mmxm`, `4h_swing_liquidity`, `forex_session_judas`, `osok_1h_po3`.

## What data source is used when local Exness history is unavailable?

`get_data_client()` falls back to `SyntheticClient` so cloud agents can still run backtests. Set `BACKTEST_DATA_SOURCE=local` and `LOCAL_HISTORY_PATH` for production runs on the user's machine.
