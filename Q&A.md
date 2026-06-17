# Q&A

## Q: Why is Video #1 marked `coded_pending_production_backtest`?
**A:** The Linux cloud agent environment has no access to the Windows Exness structured history path (`O:\D temp\UltimateTradeBot\Data\Exness\structured\history`). Code and anti-bias review are complete; production multi-instrument backtest must run on Windows with real CSV data.

## Q: Why delete legacy flat `s*.py` strategies?
**A:** The pipeline spec requires folder-per-strategy architecture with a shared `main_backtester.py`. Legacy MT5/flat files were removed during bootstrap to avoid conflicting discovery paths.
