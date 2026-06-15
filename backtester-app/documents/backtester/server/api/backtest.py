"""
API endpoints for running backtests and fetching results.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backtester.strategies.registry import get_strategy
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.connectors import get_data_client

router = APIRouter()

# In-memory store for recent backtest results
# In a real app, this would be a database (Supabase)
_RESULTS = {}


class BacktestRequest(BaseModel):
    strategy_id: str
    symbol: str
    start_date: str  # ISO format
    end_date: str    # ISO format
    initial_balance: float = 10000.0
    risk_per_trade: float = 0.01


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    """Run a backtest for a strategy and return the full results."""
    StratClass = get_strategy(req.strategy_id)
    if not StratClass:
        raise HTTPException(status_code=404, detail="Strategy not found")
        
    try:
        start_dt = datetime.fromisoformat(req.start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(req.end_date.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO format.")
        
    config = BacktestConfig(
        strategy_id=req.strategy_id,
        symbol=req.symbol,
        start_date=start_dt,
        end_date=end_dt,
        initial_balance=req.initial_balance,
        risk_per_trade=req.risk_per_trade,
    )
    
    client = get_data_client()
    strategy = StratClass()
    engine = BacktestEngine(config, strategy, client)
    
    try:
        result = engine.run()
        
        # Generate a simple run ID
        run_id = f"run_{int(datetime.now().timestamp())}"
        
        # Store in memory
        _RESULTS[run_id] = result.to_dict()
        
        return {
            "run_id": run_id,
            "status": "success",
            "stats": _RESULTS[run_id]["stats"]
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Backtest error: {str(e)}")


@router.get("/{run_id}/results")
async def get_backtest_results(run_id: str):
    """Get the full results (equity curve, trades) for a run ID."""
    if run_id not in _RESULTS:
        raise HTTPException(status_code=404, detail="Result not found")
    return _RESULTS[run_id]
