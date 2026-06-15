# Q&A

## Q: Which strategies from the CSV are coded and backtested?
**A:** See `backtester-app/documents/backtester/results/strategy_audit.json`. Of 22 canonical modules, 6 emit trade signals; 2 have saved backtest results as of this run (`session_dol_fib`, `london_orb`).

## Q: Which strategy was implemented in this session?
**A:** `session_dol_fib` (video 52) — the only canonical module that had no file and no backtest. Implemented as `s052_session_dol_fib.py`.

## Q: What data source was used for backtests?
**A:** Synthetic OHLCV fallback (`--data-source synthetic`) because the Exness local history path and MT5 ngrok server are unavailable in the cloud environment. Re-run with `BACKTEST_DATA_SOURCE=local` when `LOCAL_HISTORY_PATH` is set on the user's machine.
