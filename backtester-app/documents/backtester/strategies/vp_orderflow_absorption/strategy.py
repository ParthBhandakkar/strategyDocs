"""
VP + Orderflow Absorption — Video #1 canonical (Cluster A).

Fade absorption at developing VP extremes when aggressive orders fail at wicks
and price inverts local order clusters. Post-9:30 NY session on M1.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_in_session
from backtester.strategies.base import BaseStrategy
from .helpers import (
    developing_vp,
    long_inversion_trigger,
    pending_long_absorption,
    pending_short_absorption,
    short_inversion_trigger,
)


def _load_config() -> dict:
    cfg_path = Path(__file__).parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts order clusters. Post-9:30 NY on M1."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1, "Developing VP", "Build daily VP (VWAP/POC/VAH/VAL) from post-9:30 NY bars.", "M1",
            conditions=["Session after 9:30 NY", "Minimum 30 M1 bars in session"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            2, "Absorption Detection", "Identify buyer/seller absorption at VP extremes via wick volume.", "M1",
            conditions=["Heavy volume in wick without follow-through"],
        ),
        PlaybookStep(
            3, "Order Inversion", "Enter on close through close-proximity order cluster.", "M1",
            conditions=["Short: close below support cluster after VAH absorption",
                        "Long: close above resistance cluster after VAL absorption"],
        ),
        PlaybookStep(
            4, "Risk Management", "SL beyond absorption wick; TP at VAL (short) or VWAP (long).", "M1",
        ),
    ]

    def on_start(self):
        cfg = _load_config()
        abs_cfg = cfg.get("absorption", {})
        self._min_wick_ratio = float(abs_cfg.get("min_wick_ratio", 0.45))
        self._cluster_lookback = int(abs_cfg.get("cluster_lookback", 15))
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_session_date = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1:
            return []

        if not is_in_session(current_time, "new_york"):
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        if len(m1_hist) < 50:
            return []

        vp = developing_vp(m1_hist, current_time)
        if vp is None:
            return []

        signals: list[Signal] = []

        # --- Short setup: absorption above VAH, inversion below support cluster ---
        if pending_short_absorption(m1, m1_hist, vp, self._min_wick_ratio):
            self._pending_short = {
                "wick_high": m1.high,
                "wick_low": m1.low,
                "val_target": vp.val,
            }
            if self.step_tracker:
                self.step_tracker.record(
                    "Buyer Absorption", 2, current_time, m1.high, "M1",
                    f"Buyer absorption near VAH/POC at {m1.high:.5f}",
                )

        if self._pending_short:
            triggered, cluster = short_inversion_trigger(m1, m1_hist, self._cluster_lookback)
            if triggered:
                entry = m1.close
                sl = self._pending_short["wick_high"]
                tp = self._pending_short["val_target"]
                if sl > entry and tp < entry:
                    risk = sl - entry
                    reward = entry - tp
                    if reward / risk >= 0.8:
                        signals.append(Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vah_absorption_inversion", "cluster": cluster},
                        ))
                self._pending_short = None

        # --- Long setup: absorption below VAL, inversion above resistance cluster ---
        if pending_long_absorption(m1, m1_hist, vp, self._min_wick_ratio):
            self._pending_long = {
                "wick_low": m1.low,
                "wick_high": m1.high,
                "vwap_target": vp.vwap,
            }
            if self.step_tracker:
                self.step_tracker.record(
                    "Seller Absorption", 2, current_time, m1.low, "M1",
                    f"Seller absorption below VAL at {m1.low:.5f}",
                )

        if self._pending_long:
            triggered, cluster = long_inversion_trigger(m1, m1_hist, self._cluster_lookback)
            if triggered:
                entry = m1.close
                sl = self._pending_long["wick_low"]
                tp = self._pending_long["vwap_target"]
                if sl < entry and tp > entry:
                    risk = entry - sl
                    reward = tp - entry
                    if reward / risk >= 0.8:
                        signals.append(Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "val_absorption_inversion", "cluster": cluster},
                        ))
                self._pending_long = None

        return signals
