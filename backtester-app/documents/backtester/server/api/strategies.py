"""
API endpoints for listing and getting strategy details.
"""

from fastapi import APIRouter, HTTPException
from backtester.strategies.registry import get_all_strategies, get_strategy
from backtester.core.timeframes import tf_short

router = APIRouter()


@router.get("")
async def list_strategies():
    """List all available strategies with their basic metadata."""
    strategies = get_all_strategies()
    result = []
    
    for StratClass in strategies:
        result.append({
            "id": StratClass.id,
            "name": StratClass.name,
            "description": StratClass.description,
            "timeframes": [tf_short(tf) for tf in StratClass.timeframes],
            "video_url": StratClass.source_video,
        })
        
    return {"strategies": result}


@router.get("/{strategy_id}")
async def get_strategy_details(strategy_id: str):
    """Get full details and playbook for a specific strategy."""
    StratClass = get_strategy(strategy_id)
    if not StratClass:
        raise HTTPException(status_code=404, detail="Strategy not found")
        
    playbook_steps = []
    for step in StratClass.playbook:
        playbook_steps.append({
            "step_number": step.step_number,
            "title": step.title,
            "description": step.description,
            "timeframe": step.timeframe,
            "conditions": step.conditions,
        })
        
    return {
        "id": StratClass.id,
        "name": StratClass.name,
        "description": StratClass.description,
        "timeframes": [tf_short(tf) for tf in StratClass.timeframes],
        "video_url": StratClass.source_video,
        "playbook": playbook_steps,
    }
