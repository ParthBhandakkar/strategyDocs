"""
Timeframe definitions and utilities.
Maps between MT5 timeframe constants, minute values, and human-readable labels.
"""

from enum import IntEnum


class TF(IntEnum):
    """MT5-compatible timeframe constants."""
    M1 = 1
    M2 = 2
    M3 = 3
    M5 = 5
    M10 = 10
    M15 = 15
    M30 = 30
    H1 = 16385
    H2 = 16386
    H4 = 16388
    H6 = 16390
    H8 = 16392
    H12 = 16396
    D1 = 16408
    W1 = 32769
    MN1 = 49153


# Mapping from TF to minutes per bar
_TF_MINUTES = {
    TF.M1: 1,
    TF.M2: 2,
    TF.M3: 3,
    TF.M5: 5,
    TF.M10: 10,
    TF.M15: 15,
    TF.M30: 30,
    TF.H1: 60,
    TF.H2: 120,
    TF.H4: 240,
    TF.H6: 360,
    TF.H8: 480,
    TF.H12: 720,
    TF.D1: 1440,
    TF.W1: 10080,
    TF.MN1: 43200,
}

# Human-readable labels
_TF_LABELS = {
    TF.M1: "1 Minute",
    TF.M2: "2 Minutes",
    TF.M3: "3 Minutes",
    TF.M5: "5 Minutes",
    TF.M10: "10 Minutes",
    TF.M15: "15 Minutes",
    TF.M30: "30 Minutes",
    TF.H1: "1 Hour",
    TF.H2: "2 Hours",
    TF.H4: "4 Hours",
    TF.H6: "6 Hours",
    TF.H8: "8 Hours",
    TF.H12: "12 Hours",
    TF.D1: "Daily",
    TF.W1: "Weekly",
    TF.MN1: "Monthly",
}

# Short labels for badges
_TF_SHORT = {
    TF.M1: "M1",
    TF.M2: "M2",
    TF.M3: "M3",
    TF.M5: "M5",
    TF.M10: "M10",
    TF.M15: "M15",
    TF.M30: "M30",
    TF.H1: "H1",
    TF.H2: "H2",
    TF.H4: "H4",
    TF.H6: "H6",
    TF.H8: "H8",
    TF.H12: "H12",
    TF.D1: "D1",
    TF.W1: "W1",
    TF.MN1: "MN1",
}


def tf_to_minutes(tf: TF) -> int:
    """Get the number of minutes per bar for a timeframe."""
    return _TF_MINUTES.get(tf, 60)


def tf_label(tf: TF) -> str:
    """Get human-readable label for a timeframe."""
    return _TF_LABELS.get(tf, str(tf))


def tf_short(tf: TF) -> str:
    """Get short label for a timeframe (e.g., 'M15', 'H4')."""
    return _TF_SHORT.get(tf, str(tf))


def tf_from_string(s: str) -> TF:
    """Parse a timeframe string like 'M1', 'H4', 'D1' into a TF enum."""
    s = s.upper().strip()
    for tf in TF:
        if _TF_SHORT.get(tf) == s:
            return tf
    raise ValueError(f"Unknown timeframe string: {s}")


def tf_from_minutes(minutes: int) -> TF:
    """Get the TF enum for a given minute value."""
    for tf, mins in _TF_MINUTES.items():
        if mins == minutes:
            return tf
    raise ValueError(f"No timeframe for {minutes} minutes")


def is_higher_tf(a: TF, b: TF) -> bool:
    """Check if timeframe 'a' is higher (slower) than timeframe 'b'."""
    return tf_to_minutes(a) > tf_to_minutes(b)


def sort_timeframes(tfs: list[TF]) -> list[TF]:
    """Sort timeframes from lowest (fastest) to highest (slowest)."""
    return sorted(tfs, key=lambda t: tf_to_minutes(t))


# Exness CSV folder names
_TF_FOLDER = {
    TF.M1: "1m",
    TF.M2: "2m",
    TF.M3: "3m",
    TF.M5: "5m",
    TF.M10: "10m",
    TF.M15: "15m",
    TF.M30: "30m",
    TF.H1: "1h",
    TF.H2: "2h",
    TF.H4: "4h",
    TF.H6: "6h",
    TF.H8: "8h",
    TF.H12: "12h",
    TF.D1: "1d",
    TF.W1: "1w",
    TF.MN1: "1mo",
}


def tf_to_folder(tf: TF) -> str:
    """Map TF enum to Exness structured history folder name."""
    folder = _TF_FOLDER.get(tf)
    if folder is None:
        raise ValueError(f"No Exness folder mapping for timeframe {tf}")
    return folder


def tf_from_folder(folder: str) -> TF:
    """Parse Exness folder name into TF enum."""
    folder = folder.strip().lower()
    for tf, name in _TF_FOLDER.items():
        if name == folder:
            return tf
    raise ValueError(f"Unknown Exness timeframe folder: {folder}")


# All common forex timeframes for the API
ALL_TIMEFRAMES = [
    {"value": tf.value, "label": tf_label(tf), "short": tf_short(tf), "minutes": tf_to_minutes(tf)}
    for tf in [TF.M1, TF.M5, TF.M15, TF.M30, TF.H1, TF.H4, TF.D1, TF.W1]
]
