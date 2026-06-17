# Q&A

## Q: Why is Video #1 marked `coded_pending_production_backtest` instead of `coded_and_backtested`?
**A:** The Linux cloud agent environment has no access to the Windows Exness history path (`O:\D temp\UltimateTradeBot\Data\Exness\structured\history`). Per pipeline rules, we implement code and defer production backtest rather than using synthetic fixtures.

## Q: How is orderflow approximated without L2 data?
**A:** CSV history provides tick_volume only. The strategy uses the video's wick-vs-body rule: elevated tick_volume in wicks without price follow-through signals absorption. This is documented in anti_bias_notes.
