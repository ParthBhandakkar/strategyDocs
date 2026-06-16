# Q&A

## Q: Should production backtests run on Linux cloud agents?
**A:** No. Real Exness CSV history lives at `O:\D temp\UltimateTradeBot\Data\Exness\structured\history` on Windows. Cloud runs implement code and mark `coded_pending_production_backtest` until that path is available.

## Q: How is orderflow approximated without L2 data?
**A:** Video #1 uses tick_volume concentration in candle wicks as a proxy for aggressive order absorption, consistent with the video's wick-vs-body rule. No synthetic OHLCV is generated.
