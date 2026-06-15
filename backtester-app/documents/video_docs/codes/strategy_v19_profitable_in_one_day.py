"""
Strategy: Become a Profitable Trader in ONE DAY (Psychology)
Source: Faiz SMC ("Become a Profitable Trader in ONE DAY!")
Video: https://www.youtube.com/watch?v=1Y19QjyLt6M

Note: This video covers trading psychology and identity — no technical strategy.
It argues that profitability comes from behavioral identity, not indicator settings.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ProfitableInOneDay"
SYMBOL = "NQ"
TIMEFRAMES = []


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()
    log.event(0, "Psychology-Only Video - No Technical Strategy",
              "", 0, "",
              "This video does not define a tradeable strategy. "
              "It focuses on trader identity, discipline, and behavioral change.")
    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
