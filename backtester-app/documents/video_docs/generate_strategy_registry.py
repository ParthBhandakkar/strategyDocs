"""Generate strategy_videos_90.csv from the deduplication analysis."""
import csv
import json
from pathlib import Path

VIDEO_DOCS_DIR = Path(__file__).parent
CSV_PATH = VIDEO_DOCS_DIR / "strategy_videos_90.csv"
FINDINGS_PATH = VIDEO_DOCS_DIR / "STRATEGY_DEDUP_FINDINGS.md"

# fmt: off
VIDEOS = [
    # video, filename, title, source, type, cluster, cluster_name, action, dup_of, module, concept, ref_range, entry, htf, ltf, session, asset, notes
    (1, "video_01_Orderflow_and_Volume_Profile_Da.md", "Orderflow and Volume Profile Day Trading Strategy", "How I Made $14,068 Day Trading With Orderflow", "strategy", "A", "VP + Orderflow Absorption", "CODE-CANONICAL", "", "vp_orderflow_absorption", "Fade absorption at developing VP extremes when aggressive orders fail at wicks and price inverts order clusters", "NY open developing VP (VWAP/POC/VAH/VAL)", "Orderflow absorption + order-cluster inversion", "Daily VP", "1M", "Post 9:30 NY", "NQ", "Canonical for cluster A"),
    (2, "video_02_Volume_Profile_and_Orderflow_Re.md", "Volume Profile and Orderflow Reversal Strategy", "Volume Profile + Orderflow = Profit", "strategy", "A", "VP + Orderflow Absorption", "DUPLICATE-SKIP", "1", "vp_orderflow_absorption", "Fade failed auctions at overnight VP VAH/VAL with wick absorption and order-box reclaim", "Overnight VP 18:00-9:30 NY", "L2 absorption + box reclaim", "Overnight VP", "1M", "NY session", "NQ", "Overnight VP variant of A"),
    (3, "video_03_One-Minute_Liquidity_Sweep_Trad.md", "One-Minute Liquidity Sweep Trading Strategy", "Secret ICT Liquidity Sweep Trading Strategy With Insane Winrate!", "strategy", "B", "1M Range Sweep + HTF DOL", "DUPLICATE-SKIP", "54", "range_sweep_mss", "1M range-bound liquidity sweep with HTF orderflow and DOL alignment; invalidate if opposite range breaks first", "1M fractal range after internal MSS", "Liquidity sweep + CISD or IFVG", "5M/15M bias; 1H/4H DOL", "1M", "9:30-14:00 NY", "NQ", "1M+HTF DOL variant of range sweep; hyperparams on Q module"),
    (4, "video_04_Gold_Fixed_Range_Volume_Profile.md", "Gold Fixed Range Volume Profile Scalping Strategy", "The Easiest Gold Volume Profile Trading Strategy That Works!", "strategy", "C", "Gold London VP Failed Auction", "CODE-CANONICAL", "", "gold_london_vp_failed_auction", "5M Gold London 3-7AM FRVP failed auction or P/B-shape breakout", "London FRVP 3:00-7:00 AM NY", "5M reclaim close at VAH/VAL", "5M only", "5M", "London profile; NY execution", "Gold", "Exact duplicate concept with video 10"),
    (5, "video_05_Macro_Volume_Profile_and_ICT_Co.md", "Macro Volume Profile and ICT Confluence Strategy", "Volume Profile + ICT = Easy Profit", "strategy", "D", "Multi-VP + 1M ICT", "CODE-CANONICAL", "", "multi_vp_ict", "5M failed auctions at stacked weekly/daily/overnight VP with 1M ICT confirmation", "Multi VP (week/day/overnight)", "CISD / IFVG / MSS / breaker on 1M", "Week/day/ON VP", "5M -> 1M", "NY developing profile", "NQ", "Unique stacked VP confluence"),
    (6, "video_06_Strategy_1_Fractal-Based_Inversion_Order_Flow_Str.md", "Fractal-Based Inversion Order Flow Strategy", "The Only Trading Strategy I'd Use If I Had To Start Over (Stupid Simple)", "strategy", "E", "HTF FVG Inversion Stack", "CODE-CANONICAL", "", "htf_fvg_inversion", "With 1H orderflow and 4H DOL set; post-9:30 invert all micro-FVGs inside 5M/15M FVG", "Post-9:30 5M/15M FVG", "1M FVG inversion stack", "1H/4H", "5M/15M -> 1M", "After 9:30 NY", "NQ/ES", "Canonical for HTF FVG inversion family"),
    (7, "video_07_Strategy_2_Intraday_8_AM_Candle_Liquidity_Strategy.md", "Intraday 8 AM Candle Liquidity Strategy", "Strategy 2 from course", "strategy", "F", "8AM One-Candle Sweep", "DUPLICATE-SKIP", "42", "one_candle_8am", "Sweep 8AM 1H high/low plus adjacent swing/FVG; 1M MSS/CISD with close back inside 8AM range", "8AM 1H candle", "MSS/CISD + FVG/OB", "1H", "1M", "Pre/post 9:30 NY", "NQ", "Duplicate of 8AM one-candle; see V42"),
    (8, "video_08_Strategy_3_Volume_Profile_Auction_Breakout_Strate.md", "Volume Profile Auction Breakout Strategy", "The Only Volume Profile Strategy You'll Ever Need! (FULL COURSE)", "strategy", "G", "VP Failed Auction / Breakout", "CODE-CANONICAL", "", "vp_failed_auction_generic", "VP D/P/B shape chooses failed-auction fade vs acceptance breakout; 1M absorption confirm", "Session FRVP (Asia or prior day)", "5M reclaim or breakout + 1M absorption", "5M", "5M -> 1M", "Asia / intraday", "NQ", "Generic VP auction model"),
    (9, "video_09_Strategy_4_Daily_Power_of_Three_PO3_Strategy.md", "Daily Power of Three (PO3) Strategy", "I Simplified ICT PO3.. And It Actually Works!", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "10AM 4H open manipulation at 15M swing/FVG with SMT; 1M CISD/breaker; Fib -2/-2.5 targets", "10AM 4H PO3; 6AM vs 2AM bias", "SMT + CISD / breaker", "4H", "15M -> 1M", "10AM 4H window", "NQ/ES", "Duplicate of 10AM PO3 family"),
    (10, "video_10_Strategy_5_Gold_Scalping_Failed_Auction_Strategy.md", "Gold Scalping Failed Auction Strategy", "ICT Not Working? Use This Gold Trading Strategy Instead..", "strategy", "C", "Gold London VP Failed Auction", "DUPLICATE-SKIP", "4", "gold_london_vp_failed_auction", "Same as V04: 5M Gold London 3-7AM VP failed auction", "London FRVP 3-7AM NY", "5M reclaim close", "5M only", "5M", "Post 7AM", "Gold", "Exact duplicate of video 04"),
    (11, "video_11_ICT_Volume_Profile_Breakout_St.md", "ICT + Volume Profile Breakout Strategy", "ICT + Volume Profile = Insane Profit", "strategy", "G", "VP Failed Auction / Breakout", "DUPLICATE-SKIP", "8", "vp_failed_auction_generic", "18:00-8:55 pre-market NQ VP failed auction or breakout with 5M ICT FVG/OB", "Pre-market FRVP", "Failed auction or breakout + FVG/OB", "5M", "5M", "Pre 9:00 / NY", "NQ", "NQ-specific VP window variant of G"),
    (12, "video_12_The_800_AM_Candle_Strategy.md", "The 8:00 AM Candle Strategy", "This 8AM Candle Strategy Is Boring But It Makes Money", "strategy", "F", "8AM One-Candle Sweep", "DUPLICATE-SKIP", "42", "one_candle_8am", "Mark 8AM 1H range; sweep range + neighbor swing; 1M MSS/IFVG close inside", "8AM 1H", "MSS / IFVG + close inside", "1H", "1M", "Pre-market / NY open", "NQ, Gold", "Duplicate of 8AM one-candle"),
    (13, "video_13_The_3-Step_A_ICT_Gold_Strategy.md", "The 3-Step A+ ICT Gold Strategy", "The 3-Step A+ ICT Gold Strategy (that actually works)", "strategy", "I", "HTF Trend + SMT + CISD", "CODE-CANONICAL", "", "htf_trend_smt_cisd", "Trade obvious 1H/4H Gold trend into hourly FVG with Gold/Silver SMT; 5M CISD or MSS retest", "1H/4H trend FVG", "SMT + CISD / breaker", "1H/4H", "5M", "Trend session", "Gold/Silver", "Canonical HTF trend + SMT model"),
    (14, "video_14_The_One-Candle_Trading_Strategy.md", "The One-Candle Trading Strategy", "This One Candle Trading Strategy Is The Fastest Way To Become Profitable", "strategy", "F", "8AM One-Candle Sweep", "DUPLICATE-SKIP", "42", "one_candle_8am", "8AM 1H boundaries + adjacent swing sweep; 1M MSS/IFVG; close inside; target opposite boundary", "8AM 1H", "MSS / IFVG", "1H", "1M", "Pre 9:30 NY", "NQ", "Duplicate of 8AM one-candle"),
    (15, "video_15_Orderflow_Boot_Camp_Lesson_1_Vo.md", "Orderflow Boot Camp Lesson 1: Volume Profile", "Orderflow Boot Camp", "non_strategy_tutorial", "", "", "SKIP", "", "", "Educational lesson on VP shapes and D-shape breakout mechanics", "", "", "", "", "", "General", "Not a standalone backtestable edge"),
    (16, "video_16_The_Easiest_Trading_Strategy_for_Beginners_in_2026.md", "Easiest Strategy for Beginners 2026", "The Easiest Trading Strategy for Beginners in 2026", "strategy", "F", "8AM One-Candle Sweep", "DUPLICATE-SKIP", "42", "one_candle_8am", "Mechanical 8AM 1H sweep of range + left PD array; 1M MSS/CISD close inside", "8AM 1H + HTF PD", "MSS / CISD + FVG/breaker", "1H", "1M", "Morning", "NQ", "Duplicate of 8AM one-candle"),
    (17, "video_17_The_1H_Pattern_Nobody_Talks_About_1H_1M_Strategy.md", "1H Pattern Nobody Talks About", "The 4H Pattern Nobody Talks About (step by step) - hourly variant", "strategy", "J", "Hourly-Open PO3 + Fib", "CODE-CANONICAL", "", "hourly_po3_fib", "On hourly open sweep nearest unswept 5M swing; manipulation ends at Fib -2/-2.5; 1M MSS/FVG", "Session 1H opens (8PM/4AM/8AM)", "PO3 hourly + Fib SD + MSS", "1H", "5M -> 1M", "Per session candle", "Gold", "Distinct from 10AM 4H PO3 anchor"),
    (18, "video_18_The_Only_GOLD_Trading_Strategy_You_Need_In_2026_St.md", "Only GOLD Strategy 2026", "The Only GOLD Trading Strategy You Need In 2026", "strategy", "J", "Hourly-Open PO3 + Fib", "DUPLICATE-SKIP", "17", "hourly_po3_fib", "Nearly all 1H candles wick: sweep pre-open 5M liquidity to Fib -2/-2.5 then 1M MSS/CISD", "Any 1H open", "5M sweep + Fib + MSS/CISD", "1H", "5M -> 1M", "Asia/London/NY", "Gold, NQ", "Duplicate of hourly PO3"),
    (19, "video_19_Become_a_Profitable_Trader_in_ONE_DAY.md", "Become a Profitable Trader in ONE DAY", "Become a Profitable Trader in ONE DAY!", "non_strategy_mindset", "", "", "SKIP", "", "", "Trading psychology and identity — no executable setup", "", "", "", "", "", "", "Mindset only"),
    (20, "video_20_This_Secret_One_Candle_Trading_Strategy.md", "Secret One-Candle Strategy", "This Secret One Candle Trading Strategy", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "10AM 4H open PO3: 1M MSS; Fib -2/-2.5; SMT + CISD", "10AM 4H", "Fib SD + SMT + CISD", "4H", "1M", "10AM", "NQ, Gold", "Duplicate 10AM PO3"),
    (21, "video_21_Video_1_This_Trading_Strategy_Will_Change_Your_Lif.md", "Video 1: Strategy Will Change Your Life 2026", "This Trading Strategy Will Change Your Life In 2026", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "10AM 4H AMD: tap 5M/15M PDA; SMT; CISD; Fib expansion", "10AM 4H PO3", "SMT + CISD + Fib", "4H", "5M/15M -> 1M", "10AM", "NQ, Gold", "Duplicate 10AM PO3"),
    (22, "video_22_Video_2_I_Simplified_ICT_AMD_Trading_Strategy.md", "Video 2: Simplified ICT AMD", "I Simplified ICT AMD Trading Strategy", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "10AM 4H PO3 with HTF PO3 indicator; manipulation to -2/-2.5; SMT; CISD", "10AM 4H", "SMT + CISD + Fib", "4H", "1M/5M", "10AM", "NQ/ES", "Duplicate 10AM PO3"),
    (23, "video_23_Video_3_The_4H_Pattern_Nobody_Talks_About_step_by.md", "Video 3: 4H Pattern step by step", "The 4H Pattern Nobody Talks About (step by step)", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "10AM 4H premium/discount + 5M/15M PDA + SMT + CISD + Fib", "10AM 4H", "SMT + CISD", "4H", "5M/15M -> 1M", "10AM", "Gold, NQ", "Duplicate 10AM PO3"),
    (24, "video_24_Video_4_The_Only_ICT_Trading_Strategy_Ill_Be_Using.md", "Video 4: Only ICT Strategy 2026", "The Only ICT Trading Strategy I'll Be Using In 2026", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "Post-9:30 tap 5M/15M IRL FVG toward DOL; 1M sweep + invert all FVGs in leg", "DOL + 5M/15M FVG", "1M IFVG stack", "1H/4H DOL", "5M/15M -> 1M", "9:30-11:30 NY", "NQ", "Duplicate IFVG ladder; see V28"),
    (25, "video_25_Video_5_The_3-Step_A_ICT_Strategy_That_Works_Every.md", "Video 5: 3-Step A+ ICT Strategy", "The 3-Step A+ ICT Strategy That Works Every Time", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "1H trend; post-9:30 5M/15M FVG; highest-TF inversion ladder (1M-5M)", "1H structure", "Multi-TF highest IFVG", "1H", "5M/15M -> 1M-5M", "After 9:30", "NQ", "Duplicate IFVG ladder"),
    (26, "video_26_Live_Trading_NQ_-_Inverse_FVG_Scalp_Setup.md", "Live Trading NQ - Inverse FVG Scalp", "Live trading session", "non_strategy_demo", "K", "Post-9:30 IFVG Ladder", "SKIP", "28", "ifvg_inversion_ladder", "Live demo applying IFVG scalp — not new rules", "", "IFVG scalp", "", "1M", "Live NY", "NQ", "Demo only; subset of K"),
    (27, "video_27_The_Power_of_3_AMD_Silver_Bullet_Strategy.md", "Power of 3 AMD Silver Bullet", "This ICT Strategy Is Boring But It Made Me Profitable", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "10AM 4H PO3: enter after -1.0 Silver Bullet close; PD array retest", "10AM 4H", "-1.0 SB + FVG/OB", "4H", "1M", "10AM", "NQ", "Silver Bullet entry variant; hyperparam on H"),
    (28, "video_28_Multi-Timeframe_Highest_Inversion_FVG_Model.md", "Multi-Timeframe Highest Inversion FVG Model", "This iFVG Strategy is The Easiest Way to Become Profitable FAST", "strategy", "K", "Post-9:30 IFVG Ladder", "CODE-CANONICAL", "", "ifvg_inversion_ladder", "Post-9:30 displacement into 5M/15M FVG; pick highest TF IFVG in manipulation leg", "Post-9:30 displacement FVG", "Highest-TF IFVG", "1H/4H", "5M/15M -> 1M-5M", "After 9:30", "NQ", "Best canonical for IFVG ladder"),
    (29, "video_29_Time-Based_Volume_TBV_Core_Strategy.md", "Time-Based Volume (TBV) Core Strategy", "Give Me 9 Minutes & I'll Teach You My 80% Winrate Trading Strategy", "strategy", "L", "TBV Absorption", "CODE-CANONICAL", "", "tbv_absorption", "Same-TF FVG + swing sweep: sweep candle must close as absorption; enter next open", "Same-TF FVG zone", "TBV absorption close", "3M+", "3M+", "Session-agnostic", "Multi", "Canonical TBV model"),
    (30, "video_30_3-Step_Time-Based_Volume_TBV_Reassessment_Model.md", "TBV Reassessment Model", "My 80% Winrate 3-Step Trading Strategy That Works!", "strategy", "L", "TBV Absorption", "DUPLICATE-SKIP", "29", "tbv_absorption", "Same TBV engine with optional 50% equilibrium or opening-price retest", "Same-TF FVG", "TBV + 50% / open retest", "5M/15M/1H", "5M/15M/1H", "Any", "Multi", "Entry refinement on L; hyperparams"),
    (31, "video_31_1_One_Trading_Setup_For_Life_-_ICT_10AM_PO3.md", "One Trading Setup For Life - ICT 10AM PO3", "One Trading Setup For Life - ICT 10AM PO3", "strategy", "H", "10AM 4H PO3 / AMD", "CODE-CANONICAL", "", "po3_10am_4h", "6AM vs 2AM 4H bias; 10AM manipulation to 15M FVG at Fib -2/-2.5; 1M MSS/IFVG", "2AM/6AM/10AM 4H", "2-candle bias + PO3 + MSS/IFVG", "4H", "15M -> 1M", "10AM", "NQ, Gold", "Best canonical for 10AM PO3"),
    (32, "video_32_2_Insane_ICT_Liquidity_Sweep_Trading_Strategy_That.md", "Insane ICT Liquidity Sweep", "Insane ICT Liquidity Sweep Trading Strategy That Works Like Magic", "strategy", "L", "TBV Absorption", "DUPLICATE-SKIP", "29", "tbv_absorption", "15M-only: first sweep candle must close bullish/bearish (TBV); market entry next bar", "15M intraday swings", "TBV 15M-only", "15M", "15M", "All sessions", "Multi", "15M-only TBV variant"),
    (33, "video_33_3_Stupid_Simple_Gold_Trading_Strategy_That_Works_E.md", "Stupid Simple Gold Strategy", "Stupid Simple Gold Trading Strategy That Works Everyday!", "strategy", "M", "Gold Judas / Midas 8-9PM", "DUPLICATE-SKIP", "56", "gold_judas_8pm", "Asian 8PM: 15M pre-open H/L; sweep + 1M MSS + close inside; breaker or FVG", "8PM Asian open (15M ref)", "Judas sweep + MSS + breaker/FVG", "15M", "1M", "8PM-12AM NY", "Gold", "Duplicate Gold Judas"),
    (34, "video_34_4_Combining_ICT_Footprint_Chart_To_Take_High_Prob.md", "ICT + Footprint Chart", "Combining ICT & Footprint Chart To Take High Probability Trades", "strategy", "A", "VP + Orderflow Absorption", "DUPLICATE-SKIP", "1", "vp_orderflow_absorption", "ICT liquidity sweep at key level + footprint delta absorption in wick", "Session/key liquidity", "Footprint absorption", "15M/1M", "15M/1M + footprint", "Key levels", "NQ", "Footprint confirmation variant of A"),
    (35, "video_35_5_Easy_9AM_Candle_PO3_Strategy_That_Actually_Works.md", "Easy 9AM Candle PO3", "Easy 9AM Candle PO3 Strategy That Actually Works!", "strategy", "F", "8AM One-Candle Sweep", "DUPLICATE-SKIP", "42", "one_candle_8am", "Mislabeled PO3: uses 8AM 1H range after 9AM open; MSS + breaker retest", "8AM 1H + 9AM open", "MSS + breaker retest", "1H", "1M", "9AM+ NY", "NQ", "Breaker retest variant of F"),
    (36, "video_36_10AM_PO3_Trading_Setup.md", "10AM PO3 Trading Setup", "My One Trading Setup For Life - 10AM PO3", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "6AM vs 2AM bias; 10AM sweep left 5M liquidity; 5M CISD/IFVG", "10AM 4H PO3", "5M CISD/IFVG", "4H", "5M", "10AM", "NQ, Gold", "5M execution variant of H"),
    (37, "video_37_The_1-Candle_Hourly_Range_Strat.md", "1-Candle Hourly Range Strategy", "The 1-Candle Hourly Range Strategy", "strategy", "F", "8AM One-Candle Sweep", "DUPLICATE-SKIP", "42", "one_candle_8am", "7AM Gold or 8AM NQ 1H range; sweep boundary; 2M CISD + close inside", "7AM/8AM 1H", "CISD + range re-entry", "1H", "2M", "NY", "Gold, NQ", "2M execution variant of F"),
    (38, "video_38_4H_Core_Trend_SMT_Divergence_S.md", "4H Core Trend & SMT Divergence System", "Ultimate ICT Gold Trading Strategy With 73% Winrate", "strategy", "I", "HTF Trend + SMT + CISD", "DUPLICATE-SKIP", "13", "htf_trend_smt_cisd", "Obvious 4H trend into 4H FVG; Gold/Silver SMT; 15M CISD toward DOL", "4H FVG", "SMT + CISD", "4H", "15M", "London 3-5AM; NY 7-11AM", "Gold/Silver", "4H+15M variant of I"),
    (39, "video_39_Mechanical_2-Day_Daily_Bias_Str.md", "Mechanical 2-Day Daily Bias Strategy", "Best ICT Gold Trading Strategy That Works Everyday!", "strategy", "N", "Daily Bias + 15M Judas", "CODE-CANONICAL", "", "daily_bias_judas", "Two same-direction daily closes -> day-3 bias; 15M pre-open liquidity sweep against bias; MSS/CISD", "Daily 2-candle bias", "15M sweep + MSS/CISD", "Daily", "15M", "Asia/London/NY", "Gold, NQ", "Canonical daily bias judas"),
    (40, "video_40_Advanced_AMD_Precision_Project.md", "Advanced AMD & Precision Projection Model", "I Simplified ICT PO3 Trading Strategy.. (High Winrate)", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "2-day daily bias + 15M manipulation to Fib -2/-2.5; reverse Fib distribution target", "Daily + 15M open", "2-day bias + Fib PO3 + CISD", "Daily", "15M", "London/NY", "NQ, Gold", "Daily bias + PO3 projections on H"),
    (41, "video_41_ICT_Daily_Bias_Simplified_Strategy.md", "ICT Daily Bias Simplified Strategy", "I Simplified ICT Daily Bias..", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "Daily origin + DOL + 1H orderflow; post-9:30 Judas into 15M/5M FVG; 1M IFVG", "Daily/1H narrative", "1M IFVG at NY open", "Daily", "1H -> 15M/5M -> 1M", "9:30 NY", "Multi", "Adds daily bias framing to K"),
    (42, "video_42_The_8_AM_One-Candle_Trading_Strategy.md", "8 AM One-Candle Trading Strategy", "This One Candle Can Change Your Life.. (Stupid Simple Strategy)", "strategy", "F", "8AM One-Candle Sweep", "CODE-CANONICAL", "", "one_candle_8am", "8AM 1H range sweep; after 9:30; 1M MSS + close inside; breaker/OB/FVG", "8AM 1H", "MSS + PD array", "1H", "1M", "After 9:30", "NQ", "Best canonical for 8AM one-candle"),
    (43, "video_43_Live_Day_Trading_Session_Inversion_FVG_Focus.md", "Live Day Trading Session - IFVG Focus", "Live Day Trading Making $5,625", "non_strategy_demo", "K", "Post-9:30 IFVG Ladder", "SKIP", "28", "ifvg_inversion_ladder", "Live IFVG-focused session — application demo", "", "IFVG", "", "1M", "Live", "NQ", "Demo only"),
    (44, "video_44_The_Lazy_Liquidity_Strategy_Mechanical_ORB_Setup.md", "Lazy Liquidity / Mechanical ORB", "The Laziest Liquidity Trading Strategy Making $15,000/Month", "strategy", "O", "London 3AM ORB", "CODE-CANONICAL", "", "london_orb", "London 3AM 15M candle range; 15M body breakout with retest or aggressive close; 1:2 RR", "3AM 15M ORB", "ORB breakout/retest", "15M", "15M", "London 3AM", "GBPUSD", "Unique ORB model"),
    (45, "video_45_Lower-Timeframe_Inversion_Masterclass.md", "Lower-TF Inversion Masterclass", "Lower Timeframe Inversion Masterclass", "strategy", "F", "8AM One-Candle Sweep", "DUPLICATE-SKIP", "42", "one_candle_8am", "8AM 1H sweep post-9:30; highest available TF IFVG (5M down to 1M)", "8AM 1H + D/1H magnets", "IFVG hierarchy", "Daily/1H", "5M-1M", "After 9:30", "NQ", "F+K hybrid; IFVG entry is hyperparam on F"),
    (46, "video_46_1_My_Simple_Scalping_Trading_Strategy_To_Make_1087.md", "Simple Scalping $10,870/Month", "My Simple Scalping Trading Strategy To Make $10,870/Month", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "Daily/15M bias; 9:30-11:30 tap 15M FVG; 1M highest IFVG + SMT", "15M FVG", "Highest-TF IFVG + SMT", "Daily", "15M -> 1M-5M", "9:30-11:30", "NQ/ES", "Duplicate IFVG ladder"),
    (47, "video_47_2_Gold_Scalping_Strategy_For_Beginners_FULL_GUIDE.md", "Gold Scalping Beginners Guide", "Gold Scalping Strategy For Beginners (FULL GUIDE)", "strategy", "E", "HTF FVG Inversion Stack", "DUPLICATE-SKIP", "6", "htf_fvg_inversion", "1H key levels; 5M dealing-range FVG inversion; max 3 trades/day", "1H FVG/levels", "5M IFVG stack", "1H", "5M", "Asia/London/NY", "Gold", "Gold 5M inversion variant of E"),
    (48, "video_48_3_Life_Of_A_Day_Trader_Living_in_Bali.md", "Life Of A Day Trader in Bali", "Life Of A Day Trader Living in Bali", "non_strategy_demo", "K", "Post-9:30 IFVG Ladder", "SKIP", "28", "ifvg_inversion_ladder", "Vlog + brief IFVG recap — lifestyle content", "", "IFVG ladder", "", "", "", "", "Lifestyle + demo"),
    (49, "video_49_4_Stupid_ICT_IFVG_Trading_Strategy_That_Works.md", "Stupid ICT IFVG Strategy", "Stupid ICT IFVG Trading Strategy That Works", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "Standalone IFVG entry rules with minimal HTF context", "Dealing range", "IFVG", "LTF", "LTF", "", "Multi", "Simplified K variant"),
    (50, "video_50_5_Dumbest_ICT_Gold_Trading_Strategy_Makes_10000Mon.md", "Dumbest ICT Gold Strategy", "Dumbest ICT Gold Trading Strategy Makes $10,000/Month", "strategy", "E", "HTF FVG Inversion Stack", "DUPLICATE-SKIP", "6", "htf_fvg_inversion", "1H orderflow; Asia 8PM-12AM; tap 1H PDA; 5M sweep + FVG inversion", "1H PDA", "5M IFVG", "1H", "5M", "Asia 8PM-12AM", "Gold", "Asia Gold variant of E"),
    (51, "video_51_Midas_Model_5M_Timeframe.md", "Midas Model 5M", "Easy Gold Trading Strategy That Works Every Time!", "strategy", "M", "Gold Judas / Midas 8-9PM", "DUPLICATE-SKIP", "56", "gold_judas_8pm", "Asian session 5M liquidity sweep; invert all FVGs in dealing range", "5M dealing range", "5M IFVG", "5M", "5M", "Asian post-8PM", "Gold", "5M Midas variant of M"),
    (52, "video_52_Finding_The_Correct_Draw_On_Liquidity.md", "Finding Correct Draw on Liquidity", "Finding The Correct Draw On Liquidity With 96% Accuracy", "strategy", "P", "Session DOL via 0.79 Fib", "CODE-CANONICAL", "", "session_dol_fib", "London session H/L sweep; 1M close beyond 0.79 Fib confirms DOL; extreme FVG entry", "London 15M session", "0.79 Fib DOL + FVG", "15M", "1M", "Pre-NY London", "Futures", "Unique Fib DOL filter"),
    (53, "video_53_ICT_Trading_Strategy_for_Consistent_Profits.md", "ICT Strategy for Consistent Profits", "This Stupid ICT Trading Strategy Makes $1,000 Everyday!", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "Pre-9:30 mark 15M FVG; tap + 1M SMT + W-shape IFVG", "15M FVG", "SMT + IFVG", "15M", "1M", "NY open", "MNQ/ES", "Duplicate IFVG ladder"),
    (54, "video_54_Liquidity_Range_Trading_Strategy.md", "Liquidity Range Trading Strategy", "The Only Liquidity Strategy You'll Ever Need", "strategy", "Q", "Range Sweep + MSS", "CODE-CANONICAL", "", "range_sweep_mss", "5M range via MSS in pullback; sweep boundary; MSS + close inside; auto/breaker block", "5M liquidity range", "Range sweep + MSS + breaker", "5M", "5M", "NY; 3/session max", "NQ", "Canonical 5M range sweep"),
    (55, "video_55_Gold_Trading_Strategy_High_Winrate.md", "Gold Trading High Winrate", "NEW Gold Trading Strategy That Works Everyday!", "strategy", "Q", "Range Sweep + MSS", "DUPLICATE-SKIP", "54", "range_sweep_mss", "Same 5M range sweep-reversal as V54 on Gold", "5M range", "Auto block after sweep", "5M", "5M", "Per session", "Gold", "Gold variant of Q"),
    (56, "video_56_Midas_Model_Scalping_Strategy.md", "Midas Model Scalping Strategy", "The Midas Model Scalping Strategy", "strategy", "M", "Gold Judas / Midas 8-9PM", "CODE-CANONICAL", "", "gold_judas_8pm", "Gold 8PM/9PM: 15M pre-open H/L sweep; 1M MSS+displacement; FVG/breaker", "8PM/9PM 15M ref", "Judas + MSS + FVG", "15M", "1M", "8PM-12AM NY", "Gold", "Canonical Gold Judas/Midas"),
    (57, "video_57_NQ_Funded_Account_Trading_Strategy.md", "NQ Funded Account Strategy", "This Simple NQ Trading Strategy Got Me Funded With $300,000", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "Tap 1H/15M/5M FVG at open; 1M SMT; invert all FVGs in dealing range", "HTF FVG", "1M IFVG stack", "1H/15M/5M", "1M", "9:30 NY", "NQ/ES", "Duplicate IFVG ladder"),
    (58, "video_58_Midas_Model_Trade_Breakdowns.md", "Midas Model Trade Breakdowns", "The Midas Model A+ Setup - GOLD Trade Breakdown", "non_strategy_demo", "M", "Gold Judas / Midas 8-9PM", "SKIP", "56", "gold_judas_8pm", "Midas rules recap with trade examples", "8PM 15M", "Midas IFVG", "15M", "1M", "Asian", "Gold", "Teaching repeat of M"),
    (59, "video_59_Midas_Model_Trade_Breakdowns_Cont.md", "Midas Model Trade Breakdowns Cont.", "Use This Gold Trading Strategy To Quit Your Job In 60 Days!", "non_strategy_demo", "M", "Gold Judas / Midas 8-9PM", "SKIP", "56", "gold_judas_8pm", "Continued Midas trade examples", "8PM 15M", "Midas", "15M", "1M", "Asian", "Gold", "Teaching repeat of M"),
    (60, "video_60_Midas_Model_Trade_Breakdowns_End_of_Week.md", "Midas Model EOW Breakdowns", "The Midas Model A+ Setup - GOLD Trade Breakdown", "non_strategy_demo", "M", "Gold Judas / Midas 8-9PM", "SKIP", "56", "gold_judas_8pm", "End-of-week Midas examples", "8PM 15M", "Midas", "15M", "1M", "Asian", "Gold", "Teaching repeat of M"),
    (61, "video_61_Gold_Trading_Strategy_The_800_PM_900_PM_Judas_Swi.md", "Gold 8PM/9PM Judas Swing", "Give me 20 mins & I'll teach you best GOLD trading strategy", "strategy", "M", "Gold Judas / Midas 8-9PM", "DUPLICATE-SKIP", "56", "gold_judas_8pm", "15M/1M Judas at 8PM & 9PM + separate 5M liquidity run + FVG inversion", "8PM/9PM; 5M runs", "Judas MSS / 5M IFVG", "15M", "1M; 5M", "Asia/NY", "Gold, AUDJPY", "Extended M variant"),
    (62, "video_62_Trend_Continuation_Continuation_Purge_Entry_Model.md", "Continuation Purge Entry Model", "Trend Continuation Continuation Purge Entry Model", "strategy", "R", "Continuation Purge + IFVG", "CODE-CANONICAL", "", "continuation_purge", "With-trend: sweep swing that caused BOS; invert FVGs in dealing range; enter on close", "Trend structure", "Continuation purge + IFVG", "4H trend", "5M", "Killzone if <4H", "Gold, GBPUSD", "Unique trend-continuation model"),
    (63, "video_63_ICT_Liquidity_Sweep_Strategy.md", "ICT Liquidity Sweep Strategy", "Easy ICT Liquidity Sweep Strategy Made Me $14,512 Today!", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "HTF POI tap + LTF SMT + FVG inversion", "HTF FVG", "SMT + IFVG", "1H/4H or 15M", "5M/1M", "", "Forex, NQ", "Multi-asset K variant"),
    (64, "video_64_ICT_Daily_Bias_Guide.md", "ICT Daily Bias Guide", "I Simplified ICT Daily Bias..", "strategy", "N", "Daily Bias + 15M Judas", "DUPLICATE-SKIP", "39", "daily_bias_judas", "Four bias methods — framework more than single entry", "Daily", "Bias rules -> Judas post-9:30", "Daily", "LTF", "9:30+", "Multi", "Bias framework; overlaps N"),
    (65, "video_65_US30_Trading_Strategy_Judas_Swing.md", "US30 Judas Swing Strategy", "Best ICT Judas Swing Trading Strategy With 79% Winrate!", "strategy", "S", "US30 Pre-Open Judas", "CODE-CANONICAL", "", "us30_judas", "Mark 15M H/L before 9:30; post-open sweep; 1M MSS+displacement; target opposite 15M level", "Pre-9:30 15M", "Judas + MSS + FVG/OB", "15M", "1M", "9:30 NY", "US30", "Unique US30 judas anchor"),
    (66, "video_66_1_Easy_ICT_1_Minute_Trading_Strategy.md", "Easy ICT 1 Minute Strategy", "Easy ICT 1 Minute Trading Strategy That Works Everyday!", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "15M FVG during 9:30-11:30; 1M SMT; invert 1M FVG", "15M FVG", "SMT + IFVG", "Daily", "15M -> 1M", "9:30-11:30", "NQ/ES", "Duplicate IFVG ladder"),
    (67, "video_67_2_Easy_ICT_Scalping_Strategy.md", "Easy ICT Scalping Strategy", "Easy ICT Scalping Trading Strategy That Makes $1,000/Day", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "15M orderflow; tap 15M FVG; 1M SMT + FVG inversion", "15M FVG", "SMT + IFVG", "15M", "1M", "Post 9:30", "NQ/ES", "Duplicate IFVG ladder"),
    (68, "video_68_3_7940_Trade_Breakdown.md", "$7,940 Trade Breakdown", "I Made $7,940 Today Using This Boring ICT Trading Strategy", "non_strategy_demo", "I", "HTF Trend + SMT + CISD", "SKIP", "73", "htf_trend_smt_cisd", "GBPUSD walkthrough using 4H OB + SMT + sweep — demo of I/73", "4H OB", "SMT + OB retest", "4H", "15M", "", "GBPUSD", "Demo only"),
    (69, "video_69_4_ICT_Market_Maker_Model.md", "ICT Market Maker Model (MMXM)", "Make Money With This Simple ICT MMXM Strategy", "strategy", "T", "MMXM", "CODE-CANONICAL", "", "mmxm", "4H trend; sweep liquidity before BOS; 15M MSS+displacement; FVG/breaker retest", "4H structure", "MMXM reversal", "4H", "15M", "London/NY killzone", "Multi", "Unique MMXM model"),
    (70, "video_70_5_Simple_ICT_1000Day_Scalping_Strategy.md", "Simple $1,000/Day Scalping", "Simple ICT Trading Strategy Makes $1,000/Day", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "Daily bias + 1H engineered liquidity; 9:30 Judas sweep; 1M autoblock/IFVG", "Daily PDA", "Judas + autoblock/IFVG", "Daily", "1H -> 1M", "9:30 NY", "NQ", "N+K hybrid; code via K + N modules"),
    (71, "video_71_1_Why_Youre_Failing_as_a_Trader.md", "Why You're Failing as a Trader", "Please Quit Trading Before Its Too Late!", "non_strategy_mindset", "", "", "SKIP", "", "", "Psychology / discipline — no setup", "", "", "", "", "", "", "Mindset only"),
    (72, "video_72_2_Gold_1-Minute_Scalping_Strategy.md", "Gold 1-Minute Scalping", "GOLD 1 Minute Trading Strategy That Actually Works", "strategy", "M", "Gold Judas / Midas 8-9PM", "DUPLICATE-SKIP", "56", "gold_judas_8pm", "15M pre-8PM H/L; sweep; MSS+displacement; FVG/breaker", "8PM Asian", "Judas + MSS", "15M", "1M", "8PM+", "Gold", "Duplicate Gold Judas"),
    (73, "video_73_3_Simple_Trading_Strategy_for_GBPUSD.md", "Simple Strategy for GBPUSD", "This boring trading strategy made me $6,620 in a few minutes", "strategy", "I", "HTF Trend + SMT + CISD", "DUPLICATE-SKIP", "13", "htf_trend_smt_cisd", "4H orderflow into OB/FVG; 15M SMT; enter on sweep candle body break", "4H PD array", "SMT + sweep candle OB", "4H", "15M", "", "GBPUSD/EURUSD", "Forex 4H+15M variant of I"),
    (74, "video_74_4_Backtesting_Tutorial.md", "Backtesting Tutorial", "Backtesting Tutorial", "non_strategy_tutorial", "", "", "SKIP", "", "", "FX Replay tutorial using ORB example — tool demo", "", "ORB demo", "", "", "", "NQ", "Tutorial only"),
    (75, "video_75_5_Mindfulness_for_Traders.md", "Mindfulness for Traders", "Give me 6 minutes of your life and I'll make you a better trader forever", "non_strategy_mindset", "", "", "SKIP", "", "", "Meditation/breathing for discipline", "", "", "", "", "", "", "Mindset only"),
    (76, "video_76_Simplified_ICT_PO3_Trading_Strategy.md", "Simplified ICT PO3", "I Simplified ICT PO3 Trading Strategy...", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "PO3 with daily bias prerequisite; accumulation/manipulation/distribution", "Daily/4H PO3", "PO3 + bias", "Daily", "15M", "", "Multi", "Bias-gated PO3 on H"),
    (77, "video_77_Simple_ICT_Liquidity_Trading_Strategy.md", "Simple ICT Liquidity Strategy", "Simple ICT Liquidity Trading Strategy That Makes $500/Day", "strategy", "U", "4H Swing Liquidity Sweep", "CODE-CANONICAL", "", "4h_swing_liquidity", "4H 3-candle swing: mark 3rd candle H/L; next 4H bar sweep on 5M with MSS", "4H 3-candle swing", "5M MSS + OB/FVG", "4H", "5M", "Killzone", "NQ", "Unique 4H swing marker"),
    (78, "video_78_Easy_ICT_Judas_Swing_Trading_Strategy.md", "Easy Judas Swing Strategy", "Easy ICT Judas Swing Trading Strategy That Works!", "strategy", "V", "Session-Range Judas (Forex)", "CODE-CANONICAL", "", "forex_session_judas", "Asian/London session range; sweep in 2-3AM or 7-8AM window; 5M MSS entry", "Asian/London range", "Session Judas + 5M MSS", "Session", "5M", "2-3AM / 7-8AM", "EURUSD, GBPUSD", "Distinct from Gold Judas M"),
    (79, "video_79_SMC_Doesnt_Work_Anymore_Use_This_Instead.md", "SMC Doesn't Work - Use This Instead", "SMC Doesn't Work Anymore..? Use This Instead!", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "4H obvious trend; dealing range; invert extreme FVG after liquidity sweep", "4H dealing range", "4H IFVG", "4H", "4H", "", "Forex, Gold", "4H-only IFVG variant of K"),
    (80, "video_80_Easy_ICT_Trading_Strategy_for_2025.md", "Easy ICT Strategy for 2025", "Easy ICT Trading Strategy for 2025", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "Weekly/daily 2-candle PO3 bias; manipulation to Fib -2/-2.5; MSS + OB", "Weekly/Daily PO3", "2-candle bias + Fib + OB", "W/D", "15M/1H", "", "Futures", "HTF PO3 not 10AM-specific; hyperparam on H"),
    (81, "video_81_ICT_Power_of_3_1-Minute_Scalpin.md", "ICT Power of 3 1-Minute Scalping (OSOK)", "ICT Power of 3 1-Minute Scalping", "strategy", "W", "OSOK 1H PO3", "CODE-CANONICAL", "", "osok_1h_po3", "Last two 1H candles set bias for third; 1M Judas sweep of equal H/L; enter at OB of sweep candle", "1H x3 OSOK", "1H 2-candle bias + 1M Judas", "1H", "1M", "Third 1H candle", "NQ", "Unique from 10AM 4H PO3"),
    (82, "video_82_ICT_Liquidity_Sweep_Strategy_20.md", "ICT Liquidity Sweep Strategy (2025)", "Best ICT Liquidity Trading Strategy To Use In 2025!", "strategy", "N", "Daily Bias + 15M Judas", "DUPLICATE-SKIP", "39", "daily_bias_judas", "3-candle daily bias; day-3 15M sweep of pre-open liquidity; MSS at OB/FVG", "Daily 3-candle", "Daily bias + 15M sweep + MSS", "Daily", "15M", "Post 9:30", "Multi", "Duplicate of N (39)"),
    (83, "video_83_Day_Trading_for_Profit.md", "Day Trading for Profit", "How I Made $2,600 In 10 Minutes Day Trading", "non_strategy_demo", "", "", "SKIP", "", "", "Live trade story-building on D/1H -> 2M execution", "", "Liquidity narrative", "Daily/1H", "2M", "Live", "", "Demo only"),
    (84, "video_84_1-Minute_Scalping_Inverse_FVG.md", "1-Minute Scalping (Inverse FVG)", "1-Minute Scalping Inverse FVG", "strategy", "K", "Post-9:30 IFVG Ladder", "DUPLICATE-SKIP", "28", "ifvg_inversion_ladder", "External->internal bias; post-9:30 opposite sweep; invert all FVGs in leg", "ERL->IRL bias", "1M IFVG stack", "D/4H/1H/15M", "1M", "Post 9:30", "Multi", "Duplicate IFVG ladder"),
    (85, "video_85_1-Minute_Scalping_Live_Trade.md", "1-Minute Scalping Live Trade", "How I Made $2,130 In 3 Minutes Day Trading", "non_strategy_demo", "K", "Post-9:30 IFVG Ladder", "SKIP", "28", "ifvg_inversion_ladder", "Short live recap: story + SMT — not full mechanical spec", "", "SMT + story", "", "1M", "Live", "", "Demo only"),
    (86, "video_86_1_Best_ICT_Trading_Strategy_Quit_Your_Job_In_60_Da.md", "Best ICT Strategy Quit Job 60 Days", "Best ICT Trading Strategy! (Quit Your Job In 60 Days!)", "strategy", "H", "10AM 4H PO3 / AMD", "DUPLICATE-SKIP", "31", "po3_10am_4h", "Weekly/daily 2-candle PO3; third candle open; sweep left liquidity; LTF MSS+OB", "W/D PO3", "2-candle bias + judas + OB", "W/D", "4H/1H -> 15M/5M", "", "EURUSD etc.", "Duplicate of H (80/86)"),
    (87, "video_87_2_How_I_Made_3270_In_5_Minutes_Trading_ICT_Concept.md", "$3,270 in 5 Minutes Breakdown", "How I Made $3,270 In 5 Minutes Trading ICT Concepts", "non_strategy_demo", "", "", "SKIP", "", "", "Discretionary 1H liquidity reaction — experience-based", "1H liquidity", "Discretionary", "1H", "LTF", "", "NQ", "Demo / discretionary"),
    (88, "video_88_3_Structure_Liquidity_Easy_Profit.md", "Structure + Liquidity Easy Profit", "Structure + Liquidity = Easy Profit", "strategy", "I", "HTF Trend + SMT + CISD", "DUPLICATE-SKIP", "13", "htf_trend_smt_cisd", "Trend + IRL/ERL; 4H structure, 15M MSS, optional 1M refine; SMT", "4H structure", "ERL/IRL + MSS", "4H", "15M -> 1M", "", "Forex", "Generic framework variant of I"),
    (89, "video_89_4_Easy_ICT_1_Minute_Gold_Trading_Strategy_That_Wor.md", "Easy 1M Gold Strategy", "Easy ICT 1 Minute Gold Trading Strategy That Works!", "strategy", "Q", "Range Sweep + MSS", "DUPLICATE-SKIP", "54", "range_sweep_mss", "Build 1M range; sweep H/L; MSS + close inside; auto block", "1M fractal range", "Range sweep + MSS + auto block", "1M", "1M", "Asia/London/NY", "Gold, indices", "1M variant of Q"),
    (90, "video_90_5_How_I_Make_1000Day_with_ONE_Simple_Crypto_Strate.md", "$1,000/Day Crypto Strategy", "How I Make $1,000/Day with ONE Simple Crypto Strategy", "strategy", "Q", "Range Sweep + MSS", "DUPLICATE-SKIP", "54", "range_sweep_mss", "15M+ range via MSS; sweep H/L; MSS + close inside; auto block", "15M+ range", "Range sweep + MSS + auto block", "15M+", "15M+", "", "Crypto", "15M+ crypto variant of Q"),
]
# fmt: on

CSV_COLUMNS = [
    "video_number",
    "filename",
    "title",
    "youtube_source_title",
    "content_type",
    "is_backtestable",
    "action",
    "cluster_id",
    "cluster_name",
    "is_duplicate",
    "duplicate_of_video",
    "module_to_code",
    "core_concept",
    "reference_range_candle",
    "entry_model",
    "htf_timeframes",
    "ltf_timeframes",
    "session_time_filter",
    "asset_focus",
    "notes",
]


def row_to_dict(row: tuple) -> dict:
    keys = [
        "video_number", "filename", "title", "youtube_source_title", "content_type",
        "cluster_id", "cluster_name", "action", "duplicate_of_video", "module_to_code",
        "core_concept", "reference_range_candle", "entry_model", "htf_timeframes",
        "ltf_timeframes", "session_time_filter", "asset_focus", "notes",
    ]
    d = dict(zip(keys, row))
    d["is_backtestable"] = "yes" if d["content_type"] == "strategy" else "no"
    d["is_duplicate"] = "yes" if d["action"] in ("DUPLICATE-SKIP",) else "no"
    if d["action"] == "CODE-CANONICAL":
        d["is_duplicate"] = "no"
    return d


def write_csv() -> None:
    rows = [row_to_dict(v) for v in VIDEOS]
    assert len(rows) == 90, f"Expected 90 rows, got {len(rows)}"
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {CSV_PATH} ({len(rows)} rows)")


def build_largest_families_section() -> str:
    """Build duplicate-family summary from VIDEOS so counts stay in sync."""
    cluster_info: dict[str, dict] = {}
    for r in VIDEOS:
        cid = r[5]
        if not cid or r[4] != "strategy":
            continue
        info = cluster_info.setdefault(
            cid, {"name": r[6], "videos": [], "canonical": None}
        )
        info["videos"].append(r[0])
        if r[7] == "CODE-CANONICAL":
            info["canonical"] = r[0]

    ranked = sorted(cluster_info.items(), key=lambda x: -len(x[1]["videos"]))
    notes = {
        "H": "Hyperparams: entry TF (1M vs 5M), Silver Bullet -1.0 vs -2/-2.5, daily bias gate.",
        "K": "Hyperparams: HTF bias framing, SMT filter, session window.",
        "F": "Hyperparams: IFVG vs breaker vs 2M CISD, 9:30 filter.",
        "M": "Videos 58-60 are teaching repeats only.",
        "C": "Videos **04** and **10** are exact duplicates — code once.",
    }
    lines = ["## Largest duplicate families\n"]
    n = 0
    for cid, info in ranked:
        count = len(info["videos"])
        if count < 2:
            continue
        n += 1
        canon = info["canonical"] if info["canonical"] is not None else "?"
        note = notes.get(cid, "")
        suffix = f" {note}" if note else ""
        lines.append(
            f"{n}. **{cid} — {info['name']}** ({count} videos): "
            f"Use video **{canon}** as canonical.{suffix}\n"
        )
        if n >= 5:
            break
    return "\n".join(lines)


def write_findings() -> None:
  canonical = [r for r in VIDEOS if r[7] == "CODE-CANONICAL"]
  skip = [r for r in VIDEOS if r[7] in ("SKIP", "DUPLICATE-SKIP")]
  clusters: dict[str, list] = {}
  for r in VIDEOS:
    cid = r[5] or "NON_STRATEGY"
    clusters.setdefault(cid, []).append(r[0])

  md = f"""# Strategy Deduplication Findings (90 Videos)

Generated from Faiz SMC individual video docs in `individual/`.

## Summary

| Metric | Count |
|--------|-------|
| Total videos | 90 |
| Backtestable strategies | {sum(1 for r in VIDEOS if r[4] == 'strategy')} |
| Non-strategy (skip) | {sum(1 for r in VIDEOS if r[4] != 'strategy')} |
| **Unique modules to code** | **{len(canonical)}** |
| Duplicate / skip for coding | {len(skip)} |

## Action legend

| Action | Meaning |
|--------|---------|
| `CODE-CANONICAL` | Implement this module; use this video as the spec |
| `DUPLICATE-SKIP` | Same concept as canonical video; do not code separately |
| `SKIP` | Not backtestable (mindset, tutorial, live demo) |

## Unique modules to implement ({len(canonical)})

| Module | Cluster | Canonical video(s) | Videos covered |
|--------|---------|-------------------|----------------|
"""
  module_map: dict[str, tuple] = {}
  for r in canonical:
    if r[9] in module_map:
      continue
    module_map[r[9]] = (r[5], r[0], r[10][:80])

  for mod, (cid, vid, concept) in sorted(module_map.items(), key=lambda x: x[1][1]):
    members = [str(v) for v in clusters.get(cid, [])]
    md += f"| `{mod}` | {cid} | **{vid}** | {', '.join(members)} |\n"

  md += build_largest_families_section()

  md += """
## Non-strategy videos (do not code)

| Video | Title | Reason |
|-------|-------|--------|
"""
  for r in VIDEOS:
    if r[4] != "strategy":
      md += f"| {r[0]} | {r[2]} | {r[4].replace('_', ' ')} |\n"

  md += """
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
"""
  FINDINGS_PATH.write_text(md, encoding="utf-8")
  print(f"Wrote {FINDINGS_PATH}")


if __name__ == "__main__":
  write_csv()
  write_findings()
