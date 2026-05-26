"""FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import structlog

from data.repository import get_repository
from backtest import BacktestEngine, BacktestConfig, BacktestResult

logger = structlog.get_logger(__name__)

# Global state for background tasks
task_status: Dict[str, Dict[str, Any]] = {}


def normalize_pair(pair: str) -> str:
    """Convert URL-safe pair format (BTC-USDT) to database format (BTC/USDT)."""
    return pair.replace("-", "/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("api_startup")
    yield
    logger.info("api_shutdown")


app = FastAPI(
    title="CryptoQuant API",
    description="Backend API for CryptoQuant trading platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Request/Response Models
# ============================================================================

class CandleResponse(BaseModel):
    """OHLCV candle data."""
    timestamp: int
    iso_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class StatsResponse(BaseModel):
    """Data statistics."""
    pair: str
    timeframe: str
    count: int
    earliest: Optional[int]
    latest: Optional[int]
    earliest_iso: Optional[str]
    latest_iso: Optional[str]


class BacktestRequest(BaseModel):
    """Backtest parameters."""
    strategy: str
    pair: str
    timeframe: str
    days: Optional[int] = 90
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_cash: float = 10000.0
    commission: float = 0.001
    slippage: float = 0.0005


class BacktestResponse(BaseModel):
    """Backtest result."""
    strategy_name: str
    pair: str
    timeframe: str
    initial_value: float
    final_value: float
    total_return: float
    total_trades: int
    sharpe_ratio: Optional[float]
    max_drawdown: Optional[float]
    trades: List[Dict[str, Any]]
    equity_curve: List[float]
    equity_timestamps: List[int]
    error: Optional[str]


class DownloadRequest(BaseModel):
    """Data download request."""
    pair: str
    timeframe: str
    days: int = 365
    sandbox: bool = True


class DownloadStatus(BaseModel):
    """Download task status."""
    task_id: str
    status: str
    message: str
    progress: Optional[float] = None


class StrategyInfo(BaseModel):
    """Strategy information."""
    name: str
    class_name: str
    params: Dict[str, Any]


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/pairs")
async def list_pairs():
    """List all available trading pairs with data."""
    repo = get_repository()
    pairs_timeframes = repo.list_pairs_timeframes()
    
    result = {}
    for pair, timeframe in pairs_timeframes:
        if pair not in result:
            result[pair] = []
        result[pair].append(timeframe)
    
    return result


@app.get("/api/stats/{pair}/{timeframe}", response_model=StatsResponse)
async def get_stats(pair: str, timeframe: str):
    """Get data statistics for a pair/timeframe."""
    pair_db = normalize_pair(pair)
    repo = get_repository()
    
    count = repo.count(pair_db, timeframe)
    if count == 0:
        raise HTTPException(404, f"No data for {pair_db}/{timeframe}")
    
    earliest = repo.get_earliest_timestamp(pair_db, timeframe)
    latest = repo.get_latest_timestamp(pair_db, timeframe)
    
    def ts_to_iso(ts: Optional[int]) -> Optional[str]:
        if ts is None:
            return None
        return datetime.fromtimestamp(ts / 1000, tz=timezone(timedelta(hours=8))).isoformat()
    
    return StatsResponse(
        pair=pair_db,
        timeframe=timeframe,
        count=count,
        earliest=earliest,
        latest=latest,
        earliest_iso=ts_to_iso(earliest),
        latest_iso=ts_to_iso(latest),
    )


@app.get("/api/candles/{pair}/{timeframe}", response_model=List[CandleResponse])
async def get_candles(
    pair: str,
    timeframe: str,
    since: Optional[int] = None,
    until: Optional[int] = None,
    limit: Optional[int] = 500,
    order: Optional[str] = "asc",
):
    """Get OHLCV candles for a pair/timeframe."""
    pair_db = normalize_pair(pair)
    repo = get_repository()
    candles = repo.load_candles(pair_db, timeframe, since=since, until=until, limit=limit, order=order)
    
    if not candles:
        raise HTTPException(404, f"No candles found for {pair_db}/{timeframe}")
    
    return [
        CandleResponse(
            timestamp=c.timestamp,
            iso_time=c.iso_time,
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
            volume=float(c.volume),
        )
        for c in candles
    ]


@app.get("/api/strategies", response_model=List[StrategyInfo])
async def list_strategies():
    """List available strategies."""
    engine = BacktestEngine()
    
    strategies = []
    for name, cls in engine._strategy_map.items():
        # Get default params from strategy class if available
        default_params = {}
        if hasattr(cls, "DEFAULT_PARAMS"):
            default_params = cls.DEFAULT_PARAMS
        
        strategies.append(StrategyInfo(
            name=name,
            class_name=cls.__name__,
            params=default_params,
        ))
    
    return strategies


@app.post("/api/backtest", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest):
    """Run backtest with given parameters."""
    engine = BacktestEngine(BacktestConfig(
        initial_cash=request.initial_cash,
        commission=request.commission,
        slippage=request.slippage,
        plot_results=False,
    ))
    
    try:
        strategy = engine.load_strategy(request.strategy)
        result = engine.run_backtest(
            strategy=strategy,
            pair=request.pair,
            timeframe=request.timeframe,
            days=request.days,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        
        return BacktestResponse(
            strategy_name=result.strategy_name,
            pair=result.pair,
            timeframe=result.timeframe,
            initial_value=result.initial_value,
            final_value=result.final_value,
            total_return=result.total_return,
            total_trades=len(result.trades),
            sharpe_ratio=result.sharpe_ratio,
            max_drawdown=result.max_drawdown,
            trades=result.trades,
            equity_curve=result.equity_curve,
            equity_timestamps=result.equity_timestamps,
            error=result.error,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("backtest_error", error=str(e))
        raise HTTPException(500, f"Backtest failed: {str(e)}")


@app.post("/api/download", response_model=DownloadStatus)
async def start_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    """Start data download in background."""
    import uuid
    task_id = str(uuid.uuid4())[:8]
    
    task_status[task_id] = {
        "status": "pending",
        "message": "Starting download...",
        "progress": 0.0,
    }
    
    background_tasks.add_task(
        run_download_task,
        task_id,
        request.pair,
        request.timeframe,
        request.days,
        request.sandbox,
    )
    
    return DownloadStatus(
        task_id=task_id,
        status="pending",
        message="Download started",
        progress=0.0,
    )


@app.get("/api/download/{task_id}", response_model=DownloadStatus)
async def get_download_status(task_id: str):
    """Get download task status."""
    if task_id not in task_status:
        raise HTTPException(404, f"Task {task_id} not found")
    
    status = task_status[task_id]
    return DownloadStatus(
        task_id=task_id,
        status=status["status"],
        message=status["message"],
        progress=status.get("progress"),
    )


async def run_download_task(
    task_id: str,
    pair: str,
    timeframe: str,
    days: int,
    sandbox: bool,
):
    """Background task for data download."""
    from data.manager import OKXClient
    from data.models import OHLCVCandle
    
    try:
        task_status[task_id] = {
            "status": "running",
            "message": f"Downloading {pair}/{timeframe}...",
            "progress": 0.0,
        }
        
        client = OKXClient(sandbox=sandbox)
        repo = get_repository()
        
        # Calculate since timestamp
        import pandas as pd
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
        since = int(cutoff.timestamp() * 1000)
        
        # Fetch data
        candles = await asyncio.to_thread(
            client.fetch_ohlcv_history,
            pair,
            timeframe,
            since=since,
        )
        
        if not candles:
            task_status[task_id] = {
                "status": "failed",
                "message": "No data returned from exchange",
                "progress": 0.0,
            }
            return
        
        # Save to repository
        repo.save_candles(candles, pair, timeframe)
        
        task_status[task_id] = {
            "status": "completed",
            "message": f"Downloaded {len(candles)} candles",
            "progress": 100.0,
        }
        
    except Exception as e:
        logger.error("download_error", task_id=task_id, error=str(e))
        task_status[task_id] = {
            "status": "failed",
            "message": str(e),
            "progress": 0.0,
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)