# Q&A

## Q: Where is backtest OHLCV data loaded from in cloud runs?
**A:** `LOCAL_HISTORY_PATH` env var (default Windows path from spec). Cloud runs use `/workspace/data/exness/structured/history` with Exness-format CSV fixtures when the Windows path is unavailable.

## Q: Why approximate orderflow instead of L2 data?
**A:** Exness CSV provides tick_volume only. Wick-vs-body volume ratio proxies absorption per Video #1 spec (wick absorption rule).
