#!/usr/bin/env python3
"""
MT5 Data Server - Run this on your Windows PC with MT5 terminal open.
This script connects to MetaTrader 5 and exposes historical OHLCV data via HTTP.
Use NGROK to expose this server to your Mac for remote access.

Usage:
    1. On Windows: python mt5_server.py
    2. On Mac: ngrok http 8005
    3. Update the NGROK URL in your .env file (MT5_SERVER_HOST)
"""

import asyncio
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Try to import MT5 - will only work on Windows
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("WARNING: MetaTrader5 package not installed. Run: pip install MetaTrader5")

app = FastAPI(title="MT5 Data Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Check if MT5 connection is alive."""
    if not MT5_AVAILABLE:
        return {"status": "error", "error": "MT5 package not available"}
    
    if not mt5.initialize():
        return {"status": "error", "error": "MT5 not initialized"}
    
    account_info = mt5.account_info()
    if account_info is None:
        return {"status": "error", "error": "No MT5 connection"}
    
    return {
        "status": "ok",
        "connected": True,
        "server": account_info.server,
        "login": account_info.login,
        "balance": account_info.balance,
    }


@app.get("/symbols")
async def get_symbols():
    """Get available trading symbols from MT5."""
    if not MT5_AVAILABLE:
        raise HTTPException(status_code=503, detail="MT5 not available")
    
    if not mt5.initialize():
        mt5.initialize()
    
    symbols = mt5.symbols_get()
    if symbols is None:
        return {"symbols": []}
    
    symbol_names = [s.name for s in symbols if s.visible]
    return {"symbols": sorted(symbol_names)[:100]}


@app.post("/bars")
async def get_bars(request: dict):
    """
    Fetch OHLCV bars from MT5.
    
    Request body:
    {
        "symbol": "XAUUSD",
        "timeframe": 1,  # Minutes (1, 5, 15, 30, 60, 240, etc.)
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-01-02T00:00:00Z"
    }
    """
    if not MT5_AVAILABLE:
        raise HTTPException(status_code=503, detail="MT5 not available")
    
    symbol = request.get("symbol", "XAUUSD")
    timeframe = request.get("timeframe", 1)
    start_str = request.get("start")
    end_str = request.get("end")
    
    if not mt5.initialize():
        raise HTTPException(status_code=500, detail="Failed to initialize MT5")
    
    # Parse timestamps
    try:
        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {e}")
    
    # Convert to MT5 time
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    
    # MT5 timeframe constants
    tf_map = {
        1: mt5.TIMEFRAME_M1,
        5: mt5.TIMEFRAME_M5,
        15: mt5.TIMEFRAME_M15,
        30: mt5.TIMEFRAME_M30,
        60: mt5.TIMEFRAME_H1,
        240: mt5.TIMEFRAME_H4,
        1440: mt5.TIMEFRAME_D1,
    }
    
    mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_M1)
    
    # Fetch rates
    rates = mt5.copy_rates_range(symbol, mt5_tf, start_ts, end_ts)
    
    if rates is None or len(rates) == 0:
        return {"bars": [], "symbol": symbol, "count": 0}
    
    # Convert to list of dicts
    bars = []
    for r in rates:
        bars.append({
            "time": datetime.fromtimestamp(r[0], tz=timezone.utc).isoformat(),
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "tick_volume": r[5],
            "spread": r[6],
        })
    
    return {"bars": bars, "symbol": symbol, "count": len(bars)}


@app.get("/latest")
async def get_latest_bar(symbol: str = "XAUUSD", timeframe: int = 1):
    """Get the most recent bar for a symbol."""
    if not MT5_AVAILABLE:
        raise HTTPException(status_code=503, detail="MT5 not available")
    
    if not mt5.initialize():
        raise HTTPException(status_code=500, detail="Failed to initialize MT5")
    
    tf_map = {
        1: mt5.TIMEFRAME_M1,
        5: mt5.TIMEFRAME_M5,
        15: mt5.TIMEFRAME_M15,
        30: mt5.TIMEFRAME_M30,
        60: mt5.TIMEFRAME_H1,
        240: mt5.TIMEFRAME_H4,
        1440: mt5.TIMEFRAME_D1,
    }
    
    mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_M1)
    
    # Get last 1000 bars
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 1000)
    
    if rates is None or len(rates) == 0:
        raise HTTPException(status_code=404, detail="No data available")
    
    r = rates[-1]
    return {
        "time": datetime.fromtimestamp(r[0], tz=timezone.utc).isoformat(),
        "open": r[1],
        "high": r[2],
        "low": r[3],
        "close": r[4],
        "tick_volume": r[5],
        "spread": r[6],
    }


@app.on_event("shutdown")
async def shutdown_event():
    if MT5_AVAILABLE:
        mt5.shutdown()


if __name__ == "__main__":
    port = int(os.getenv("MT5_SERVER_PORT", "8005"))
    print(f"Starting MT5 Data Server on port {port}")
    print(f"MT5 Available: {MT5_AVAILABLE}")
    if not MT5_AVAILABLE:
        print("ERROR: Install MetaTrader5 package on Windows: pip install MetaTrader5")
    else:
        print("Initializing MT5...")
        if mt5.initialize():
            print("MT5 connected successfully!")
            account = mt5.account_info()
            if account:
                print(f"Server: {account.server}, Login: {account.login}, Balance: {account.balance}")
        else:
            print("Failed to initialize MT5 - make sure MT5 terminal is running")
    
    uvicorn.run(app, host="0.0.0.0", port=port)