# Strategy Deduplication Findings (90 Videos)

Generated from Faiz SMC individual video docs in `individual/`.

## Summary

| Metric | Count |
|--------|-------|
| Total videos | 90 |
| Backtestable strategies | 75 |
| Non-strategy (skip) | 15 |
| **Unique modules to code** | **22** |
| Duplicate / skip for coding | 68 |

## Action legend

| Action | Meaning |
|--------|---------|
| `CODE-CANONICAL` | Implement this module; use this video as the spec |
| `DUPLICATE-SKIP` | Same concept as canonical video; do not code separately |
| `SKIP` | Not backtestable (mindset, tutorial, live demo) |

## Unique modules to implement (22)

| Module | Cluster | Canonical video(s) | Videos covered |
|--------|---------|-------------------|----------------|
| `vp_orderflow_absorption` | A | **1** | 1, 2, 34 |
| `gold_london_vp_failed_auction` | C | **4** | 4, 10 |
| `multi_vp_ict` | D | **5** | 5 |
| `htf_fvg_inversion` | E | **6** | 6, 47, 50 |
| `vp_failed_auction_generic` | G | **8** | 8, 11 |
| `htf_trend_smt_cisd` | I | **13** | 13, 38, 68, 73, 88 |
| `hourly_po3_fib` | J | **17** | 17, 18 |
| `ifvg_inversion_ladder` | K | **28** | 24, 25, 26, 28, 41, 43, 46, 48, 49, 53, 57, 63, 66, 67, 70, 79, 84, 85 |
| `tbv_absorption` | L | **29** | 29, 30, 32 |
| `po3_10am_4h` | H | **31** | 9, 20, 21, 22, 23, 27, 31, 36, 40, 76, 80, 86 |
| `daily_bias_judas` | N | **39** | 39, 64, 82 |
| `one_candle_8am` | F | **42** | 7, 12, 14, 16, 35, 37, 42, 45 |
| `london_orb` | O | **44** | 44 |
| `session_dol_fib` | P | **52** | 52 |
| `range_sweep_mss` | Q | **54** | 54, 55, 89, 90 |
| `gold_judas_8pm` | M | **56** | 33, 51, 56, 58, 59, 60, 61, 72 |
| `continuation_purge` | R | **62** | 62 |
| `us30_judas` | S | **65** | 65 |
| `mmxm` | T | **69** | 69 |
| `4h_swing_liquidity` | U | **77** | 77 |
| `forex_session_judas` | V | **78** | 78 |
| `osok_1h_po3` | W | **81** | 81 |

## Largest duplicate families

1. **H — 10AM 4H PO3/AMD** (12 videos): Use video **31** as canonical. Hyperparams: entry TF (1M vs 5M), Silver Bullet -1.0 vs -2/-2.5, daily bias gate.
2. **K — Post-9:30 IFVG ladder** (14 videos): Use video **28** as canonical. Hyperparams: HTF bias framing, SMT filter, session window.
3. **F — 8AM one-candle sweep** (8 videos): Use video **42** as canonical. Hyperparams: IFVG vs breaker vs 2M CISD, 9:30 filter.
4. **M — Gold Judas/Midas 8-9PM** (8 videos): Use video **56** as canonical. Videos 58-60 are teaching repeats only.
5. **C — Gold London VP** (2 videos): Videos **04** and **10** are exact duplicates — code once.

## Non-strategy videos (do not code)

| Video | Title | Reason |
|-------|-------|--------|
| 15 | Orderflow Boot Camp Lesson 1: Volume Profile | non strategy tutorial |
| 19 | Become a Profitable Trader in ONE DAY | non strategy mindset |
| 26 | Live Trading NQ - Inverse FVG Scalp | non strategy demo |
| 43 | Live Day Trading Session - IFVG Focus | non strategy demo |
| 48 | Life Of A Day Trader in Bali | non strategy demo |
| 58 | Midas Model Trade Breakdowns | non strategy demo |
| 59 | Midas Model Trade Breakdowns Cont. | non strategy demo |
| 60 | Midas Model EOW Breakdowns | non strategy demo |
| 68 | $7,940 Trade Breakdown | non strategy demo |
| 71 | Why You're Failing as a Trader | non strategy mindset |
| 74 | Backtesting Tutorial | non strategy tutorial |
| 75 | Mindfulness for Traders | non strategy mindset |
| 83 | Day Trading for Profit | non strategy demo |
| 85 | 1-Minute Scalping Live Trade | non strategy demo |
| 87 | $3,270 in 5 Minutes Breakdown | non strategy demo |

## Cluster reference

| ID | Name | Code? |
|----|------|-------|
| A | VP + Orderflow Absorption | Yes (V01) |
| B | 1M Range Sweep + HTF DOL | Merge into Q (V54) as hyperparams |
| C | Gold London VP Failed Auction | Yes (V04) |
| D | Multi-VP + 1M ICT | Yes (V05) |
| E | HTF FVG Inversion Stack | Yes (V06) |
| F | 8AM One-Candle Sweep | Yes (V42) |
| G | VP Failed Auction / Breakout | Yes (V08) |
| H | 10AM 4H PO3 / AMD | Yes (V31) |
| I | HTF Trend + SMT + CISD | Yes (V13) |
| J | Hourly-Open PO3 + Fib | Yes (V17) |
| K | Post-9:30 IFVG Ladder | Yes (V28) |
| L | TBV Absorption | Yes (V29) |
| M | Gold Judas / Midas 8-9PM | Yes (V56) |
| N | Daily Bias + 15M Judas | Yes (V39) |
| O | London 3AM ORB | Yes (V44) |
| P | Session DOL via 0.79 Fib | Yes (V52) |
| Q | Range Sweep + MSS | Yes (V54) |
| R | Continuation Purge + IFVG | Yes (V62) |
| S | US30 Pre-Open Judas | Yes (V65) |
| T | MMXM | Yes (V69) |
| U | 4H Swing Liquidity Sweep | Yes (V77) |
| V | Session-Range Judas (Forex) | Yes (V78) |
| W | OSOK 1H PO3 | Yes (V81) |

## Recommended coding order

1. `po3_10am_4h` (V31) — most repeated concept
2. `ifvg_inversion_ladder` (V28) — second largest family
3. `one_candle_8am` (V42) — simple mechanical anchor
4. `gold_judas_8pm` (V56) — Gold-specific session model
5. `gold_london_vp_failed_auction` (V04) — skip V10
6. `range_sweep_mss` (V54) — covers B/Q variants via TF hyperparams
7. Remaining unique modules (O, P, R, T, W, U, V, D, G, A, I, J, L, N, S)

## Files

- **CSV registry:** `strategy_videos_90.csv` (all 90 rows with full columns)
- **Individual docs:** `individual/video_XX_*.md`
- **Batch source docs:** `batches/batch_XX_*.md`

## Architecture note

Consider shared sub-modules:

- `RangeSweepReversal` — clusters F, Q, B, M, S, V (sweep → MSS → close inside)
- `IFVGEntry` — clusters K, E, R (inversion FVG entry logic)
- `PO3Engine` — clusters H, J, W, N (anchor candle time as hyperparameter)
- `VPFailedAuction` — clusters A, C, G (volume profile auction logic)
