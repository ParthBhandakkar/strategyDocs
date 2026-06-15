# Q&A

## Which strategies are coded vs backtestable in strategy_videos_90.csv?

- 90 total videos; 75 marked backtestable; 22 unique canonical modules (`CODE-CANONICAL`).
- 44 strategy Python files exist (videos 1–46 with intentional gaps for duplicates).
- 9 strategies emit live `Signal` trade logic; the rest are metadata/playbook scaffolds returning no trades.
- Persisted backtest results are stored under `backtester-app/documents/backtester/backtest_results/`.

## Which canonical module was implemented in this session?

Video 52 (`session_dol_fib` — Finding The Correct Draw On Liquidity) was the first uncoded canonical module. It is implemented as `s052_session_dol_fib.py` and backtested with synthetic MNQ data when MT5 is unavailable.

## Why synthetic data for backtesting?

The MT5 HTTP server is not reachable in the cloud agent environment. `SyntheticDataClient` provides deterministic OHLCV so strategies can be validated offline; swap to `MT5Client` for production runs.
