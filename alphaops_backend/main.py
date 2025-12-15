import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from pydantic import BaseModel

LOG_DIR = Path("/root/trading-bot/logs")

app = FastAPI(title="AlphaOps API", version="1.0.0")


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return None


def load_jsonl(path: Path, limit: Optional[int] = None):
    items = []
    if not path.exists():
        return items
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except Exception:
                    continue
    except Exception:
        pass

    if limit is not None:
        return items[-limit:]
    return items


def last_24h(records, ts_key: str = "timestamp"):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    out = []
    for r in records:
        ts_raw = r.get(ts_key)
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except Exception:
            continue
        if ts >= cutoff:
            out.append(r)
    return out


# ---------- Pydantic models ----------

class Position(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: Optional[float] = None
    mark_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    leverage: Optional[float] = None


class Trade(BaseModel):
    timestamp: str
    symbol: str
    side: str
    qty: float
    entry_price: float
    exit_price: float
    pnl: float
    fees: float
    strategy_id: Optional[str] = None


class WalletSummary(BaseModel):
    equity: float
    available_balance: Optional[float] = None
    pnl_24h: Optional[float] = None


class HealthSummary(BaseModel):
    engine_status: str
    learning_status: str
    heartbeat_ok: bool
    last_heartbeat: Optional[str] = None
    supervisor_last: Optional[str] = None


# ---------- API endpoints ----------

@app.get("/positions", response_model=List[Position])
def get_positions():
    path = LOG_DIR / "positions_futures.json"
    data = load_json(path)
    out: List[Position] = []

    if not data:
        return out

    # Case 1: {"open_positions": [...]}
    if isinstance(data, dict) and "open_positions" in data:
        positions_list = data.get("open_positions", [])
        for pos in positions_list:
            sym = pos.get("symbol")
            size = pos.get("size", 0.0)
            if not sym or size == 0:
                continue
            side = "LONG" if size > 0 else "SHORT"
            out.append(
                Position(
                    symbol=sym,
                    side=side,
                    size=size,
                    entry_price=pos.get("entry_price"),
                    mark_price=pos.get("mark_price"),
                    unrealized_pnl=pos.get("unrealized_pnl"),
                    leverage=pos.get("leverage"),
                )
            )
        return out

    # Case 2: dict of symbol → position
    if isinstance(data, dict):
        for sym, pos in data.items():
            if not isinstance(pos, dict):
                continue
            size = pos.get("size", 0.0)
            if size == 0:
                continue
            side = "LONG" if size > 0 else "SHORT"
            out.append(
                Position(
                    symbol=sym,
                    side=side,
                    size=size,
                    entry_price=pos.get("entry_price"),
                    mark_price=pos.get("mark_price"),
                    unrealized_pnl=pos.get("unrealized_pnl"),
                    leverage=pos.get("leverage"),
                )
            )
        return out

    # Case 3: list of positions
    if isinstance(data, list):
        for pos in data:
            sym = pos.get("symbol")
            size = pos.get("size", 0.0)
            if not sym or size == 0:
                continue
            side = "LONG" if size > 0 else "SHORT"
            out.append(
                Position(
                    symbol=sym,
                    side=side,
                    size=size,
                    entry_price=pos.get("entry_price"),
                    mark_price=pos.get("mark_price"),
                    unrealized_pnl=pos.get("unrealized_pnl"),
                    leverage=pos.get("leverage"),
                )
            )
        return out

    return out



@app.get("/trades/recent", response_model=List[Trade])
def get_recent_trades(limit: int = 200):
    path = LOG_DIR / "executed_trades.jsonl"
    items = load_jsonl(path, limit=limit)
    out: List[Trade] = []
    for t in items:
        out.append(
            Trade(
                timestamp=t.get("timestamp"),
                symbol=t.get("symbol", "UNKNOWN"),
                side=t.get("side", "UNKNOWN"),
                qty=t.get("qty", 0.0),
                entry_price=t.get("entry_price", 0.0),
                exit_price=t.get("exit_price", t.get("entry_price", 0.0)),
                pnl=t.get("net_pnl", 0.0),
                fees=t.get("fees", 0.0),
                strategy_id=t.get("strategy_id"),
            )
        )
    return out


@app.get("/wallet", response_model=WalletSummary)
def get_wallet():
    portfolio = load_json(LOG_DIR / "portfolio_futures.json")
    pnl_live = load_json(LOG_DIR / "pnl_live.json")

    equity = portfolio.get("equity", 0.0) if portfolio else 0.0
    available = portfolio.get("available_balance", None) if portfolio else None
    pnl_24h = pnl_live.get("pnl_24h", None) if pnl_live else None

    return WalletSummary(
        equity=equity,
        available_balance=available,
        pnl_24h=pnl_24h,
    )


@app.get("/health", response_model=HealthSummary)
def get_health():
    prod_state = load_json(LOG_DIR / "production_health_state.json")
    engine_status = prod_state.get("engine_status", "unknown") if prod_state else "unknown"
    learning_status = prod_state.get("learning_status", "unknown") if prod_state else "unknown"

    # process heartbeat
    heartbeat_path = LOG_DIR / "process_heartbeat.json"
    heartbeat_ts = None
    if heartbeat_path.exists():
        try:
            with heartbeat_path.open() as f:
                last_line = None
                for line in f:
                    if line.strip():
                        last_line = line
                if last_line:
                    hb = json.loads(last_line)
                    heartbeat_ts = hb.get("timestamp")
        except Exception:
            heartbeat_ts = None

    # supervisor heartbeat
    supervisor_path = LOG_DIR / "supervisor_heartbeat.txt"
    supervisor_last = None
    if supervisor_path.exists():
        try:
            with supervisor_path.open() as f:
                last_line = None
                for line in f:
                    if line.strip():
                        last_line = line.strip()
                supervisor_last = last_line
        except Exception:
            supervisor_last = None

    heartbeat_ok = heartbeat_ts is not None

    return HealthSummary(
        engine_status=engine_status,
        learning_status=learning_status,
        heartbeat_ok=heartbeat_ok,
        last_heartbeat=heartbeat_ts,
        supervisor_last=supervisor_last,
    )
