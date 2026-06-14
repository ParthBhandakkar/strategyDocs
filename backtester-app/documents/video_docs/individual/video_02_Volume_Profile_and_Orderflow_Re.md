Strategy/Topic Name: Volume Profile and Orderflow Reversal Strategy

Source: Faiz SMC ("Volume Profile + Orderflow = Profit")
Video URL: https://www.youtube.com/watch?v=eap7vH0zOQ8

Overview

This video provides an in-depth operational guide on combining the Overnight Volume Profile with 1-minute orderflow analytics. It outlines how to identify Level 1 and Level 2 institutional absorption at session value extremes (Value Area High and Value Area Low) to execute highly mechanical failed auction reversals and catch major intraday breakouts.

Step-by-Step Breakdown (Chronological)
Step 1: Establish the Overnight Volume Profile Boundaries

Timeframe: Plot the profile across macro sessions, then transition to the 1-minute timeframe for execution monitoring.

Timezone Settings: Ensure your TradingView chart platform clock is set to New York time.

Session Timings: The overnight session runs from 18:00 (6:00 PM) until 09:30 AM New York time. Note: On Deep Charts, the clock displays 1 hour behind, meaning you map from 17:00 to 08:30 to outline the identical data block.

Key Levels to Watch: Value Area High (VAH), Value Area Low (VAL), Point of Control (POC), and VWAP. Ensure profile settings are locked to "manual" so reference lines remain fixed when zooming.

Step 2: Configure Orderflow Indicator Thresholds

Indicators: Add the "Deep Trades" or "Big Trades" indicator to the chart layout.

Settings: Set the contract size filter to a minimum of 50 or 60 contracts during high-volume New York sessions. For lower-volume afternoon (PM) sessions, reduce the filter to 30 contracts. Set the text minimum/maximum plot opacity to 80% for clarity.

Visual Mapping: Purple boxes represent aggressive market sellers; green boxes represent aggressive market buyers.

Step 3: Differentiate Level 1 and Level 2 Absorption

Level 1 Absorption (Intra-Candle): Orders printing within the physical body of a candle represent normal follow-through. Orders printing strictly within the candle wicks indicate absorption (e.g., green buyer blocks at the upper wick of a bearish bar mean buyers are trapped; purple seller blocks at a lower wick mean sellers are trapped).

Level 2 Absorption (Session Edge): Occurs when price breaks past the overnight VAL or VAH boundaries. Large market orders attempt to force a breakout, but a massive institutional participant with a large limit order absorbs all incoming market orders, causing price to instantly reclaim back inside the session value range.

Step 4: Map Close Proximity Orders and Execute Trades

Long Execution Rule: Below the overnight VAL, locate the final chunk of aggressive sell orders that drove price out of value. Draw a horizontal box across them. Wait for a 1-minute candle to reclaim and close above this box. High probability is confirmed if aggressive green buyer blocks print inside the candle bodies supporting the move. Enter long, stop below the low, and target the POC or VAH.

Short Execution Rule: Above the overnight VAH or after sweeping a major high, identify the cluster of aggressive buy orders at close proximity. Draw a box around them (acting as local support). Wait for a 1-minute candle to print a solid close below this box, converting it into resistance. Enter short on the close or on a touch retest of the box boundary, stop above the sweep high, and target the POC or VAL.

Key Rules & Conditions

Value Area Logic: Maintain a structural bias to buy underneath the overnight VAL (discount) and sell above the overnight VAH (premium), using orderflow to confirm that the breakout momentum has expired.

The POC Invalidation Rule: If the price trades into and hits the central overnight Point of Control (POC) line before your entry trigger executes, the entire trade setup is immediately canceled.

Inversion of Big Orders: Treat massive orderflow numbers as localized support/resistance lines. A confirmed trade requires price to cross over and invert these blocks.

Trade Examples From The Video
Example 1:

Asset/Pair: NQ (Nasdaq Futures)

Date/Session: Intraday New York Session

Entry: Entered short on a 1-minute touch retest of the close proximity order box following a breakdown close.

Stop Loss: Placed tightly above the structural absorption high.

Take Profit: Targeted the overnight VWAP line and a set of structural equal lows.

Outcome: Highly successful trade yielding a 3.5 risk-to-reward ratio (3.5 RR).

Screenshot description of the chart setup: Price expands past the gray dotted line representing the overnight VAH. A cluster of candles prints heavy green blocks of aggressive buyers (43, 40, 44, and 41 contracts) at the highs, but price completely stalls into a consolidation. A purple bearish candle appears with 41 aggressive sellers, breaking down and closing below a horizontal box drawn around the close proximity orders (48, 118, 56, and 43 contracts). Price briefly wicks back up to touch the underside of the box before dropping toward the yellow VWAP line.

Example 2:

Asset/Pair: NQ (Nasdaq Futures)

Date/Session: Intraday New York Session (Second Setup)

Entry: Entered short after a secondary rejection at the VAH zone on a retest of a volume imbalance.

Stop Loss: Placed above the newly formed rejection wick.

Take Profit: Targeted the overnight session's lower structural levels.

Outcome: Completed successfully as price moved rapidly to the downside.

Screenshot description of the chart setup: Price revisits the overnight VAH boundary. A candle prints 45 aggressive buyers at its upper wick, signaling renewed absorption. The next bearish candle displays an additional 45, 60, and 49 buy contracts entirely trapped at the top with zero upward follow-through. A box is dragged across this heavy order area and a volume imbalance; price breaks lower, returns to precisely touch the underside of the box, and expands aggressively downwards.

Example 3:

Asset/Pair: NQ (Nasdaq Futures)

Date/Session: Post-9:30 AM New York Market Open

Entry: Entered short at the close of a candle that broke below a major cluster of buy orders.

Stop Loss: Placed above the local session high.

Take Profit: Targeted the overnight Value Area Low (VAL).

Outcome: Hit target successfully for a 1:1.5 risk-to-reward ratio.

Screenshot description of the chart setup: Following the New York open, price spikes above VAH. It prints massive aggressive buys (50 and 83 contracts), but a sudden large bearish candle prints 193 and 88 sell contracts within its body, pushing back down. A box is drawn around the nearby support orders (62, 127, and 160 contracts). The next candle shows more buyers absorbed at the top and prints 131 sellers, closing below the box to trigger the short entry.

Example 4:

Asset/Pair: NQ (Nasdaq Futures)

Date/Session: Same-Day Intraday Session

Entry: Entered long on a reclaim setup after the second failed auction attempt below the VAL.

Stop Loss: Placed beneath the lowest wick of the second dip.

Take Profit: Targeted the local intraday swing high.

Outcome: Successful trade hitting a 1:2 risk-to-reward ratio.

Screenshot description of the chart setup: Price declines below the overnight VAL line. It prints 74 aggressive sellers at the bottom, but the candle rejects upwards, leaving the sellers absorbed at the wick. Since a previous dip lacked buyer numbers, a tight box is drawn across the final sell orders. A green candle closes cleanly above this box, marking the long execution before accelerating upward toward the upper targets.

Risk Management

Defensive Trade Management: Protect capital diligently. Move your stop loss to break-even or lock in partial profits at a 1:1 risk-to-reward ratio, or when price reaches the heavy volume magnet of the overnight POC.

Anchored Stop Losses: Stop losses must always be anchored safely behind the active institutional footprint (the exact blocks of absorbed buyers or sellers).

Summary / Key Takeaways

Volume profile defines the structural macro boundaries (VAH/VAL), while orderflow details the micro battles inside the candles.

Trapped traders at wicks provide the fuel for rapid reversals; when their aggressive market orders fail to move price, they are forced to cover.

You can adapt these concepts beyond the volume profile to other key areas like Fair Value Gaps, support/resistance levels, or liquidity sweeps.
