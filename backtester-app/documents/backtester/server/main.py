"""
FastAPI Server Main Entrypoint.
Serves the API and the static dashboard.
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Load environment variables from .env file
load_dotenv()

from .api import strategies, backtest, data

app = FastAPI(title="Faiz SMC Backtester", version="1.0.0")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(strategies.router, prefix="/api/strategies", tags=["Strategies"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["Backtest"])
app.include_router(data.router, prefix="/api/data", tags=["Data"])

# Serve static dashboard files
dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.exists(dashboard_path):
    app.mount("/", StaticFiles(directory=dashboard_path, html=True), name="dashboard")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backtester.server.main:app", host="127.0.0.1", port=8000, reload=True)
