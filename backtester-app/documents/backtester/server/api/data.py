"""
API endpoints for MT5 data (symbols, timeframes).
"""

from fastapi import APIRouter
from backtester.connectors import get_data_client, default_history_path
from backtester.core.timeframes import ALL_TIMEFRAMES

router = APIRouter()
_client = get_data_client()


@router.get("/symbols")
async def get_symbols():
    """Get list of available symbols from local history (or configured data source)."""
    symbols = _client.get_symbols()
    return {
        "symbols": symbols,
        "data_source": "local_history",
        "history_path": default_history_path(),
    }


@router.get("/timeframes")
async def get_timeframes():
    """Get list of supported timeframes."""
    return {"timeframes": ALL_TIMEFRAMES}
