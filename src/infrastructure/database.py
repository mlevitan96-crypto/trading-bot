"""
Tri-Layer Architecture: Database Infrastructure
High-performance async SQLite with WAL mode for Replit Reserved VM.

This module provides the foundation for concurrent read/write operations
across all three architectural layers:
- Layer 1 (Intelligence): Reads historical data for analysis
- Layer 2 (Governance): Writes reconciliation and audit logs
- Layer 3 (Execution): High-frequency trade logging
"""

import asyncio
import aiosqlite
import logging
import os
import time
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

DB_PATH = "data/trading_system.db"

INIT_SCRIPT = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;
PRAGMA temp_store=MEMORY;
PRAGMA busy_timeout=5000;
PRAGMA wal_autocheckpoint=1000;
PRAGMA mmap_size=268435456;
"""

SCHEMA_SCRIPT = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    direction TEXT,
    entry_price REAL,
    exit_price REAL,
    quantity REAL,
    margin_usd REAL,
    leverage REAL,
    profit_usd REAL,
    fees_usd REAL,
    unrealized_usd REAL,
    strategy TEXT,
    regime TEXT,
    entry_ts INTEGER,
    exit_ts INTEGER,
    closed INTEGER DEFAULT 0,
    paper_trade INTEGER DEFAULT 1,
    metadata TEXT,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_closed ON trades(closed);
CREATE INDEX IF NOT EXISTS idx_trades_entry_ts ON trades(entry_ts);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT UNIQUE,
    symbol TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL,
    ev_contribution REAL,
    price_at_signal REAL,
    resolved_price REAL,
    resolved INTEGER DEFAULT 0,
    outcome TEXT,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    resolved_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_resolved ON signals(resolved);
CREATE INDEX IF NOT EXISTS idx_signals_name ON signals(signal_name);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    inverted INTEGER DEFAULT 0,
    sizing_usd REAL,
    status TEXT DEFAULT 'PENDING',
    order_id TEXT,
    error_msg TEXT,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_execution_ts ON execution_log(ts);
CREATE INDEX IF NOT EXISTS idx_execution_symbol ON execution_log(symbol);
CREATE INDEX IF NOT EXISTS idx_execution_status ON execution_log(status);

CREATE TABLE IF NOT EXISTS governance_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    audit_type TEXT NOT NULL,
    expected_value REAL,
    actual_value REAL,
    discrepancy REAL,
    action_taken TEXT,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON governance_audit(ts);
CREATE INDEX IF NOT EXISTS idx_audit_type ON governance_audit(audit_type);

CREATE TABLE IF NOT EXISTS strategy_elo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    symbol TEXT,
    elo_score REAL DEFAULT 1500,
    win_rate REAL,
    profit_factor REAL,
    trade_count INTEGER DEFAULT 0,
    is_champion INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT (strftime('%s', 'now')),
    UNIQUE(strategy_name, symbol)
);

CREATE INDEX IF NOT EXISTS idx_elo_strategy ON strategy_elo(strategy_name);
CREATE INDEX IF NOT EXISTS idx_elo_champion ON strategy_elo(is_champion);

CREATE TABLE IF NOT EXISTS bandit_arms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    arm_id TEXT NOT NULL,
    alpha REAL DEFAULT 1.0,
    beta REAL DEFAULT 1.0,
    pulls INTEGER DEFAULT 0,
    cumulative_reward REAL DEFAULT 0,
    updated_at INTEGER DEFAULT (strftime('%s', 'now')),
    UNIQUE(strategy_name, arm_id)
);

CREATE TABLE IF NOT EXISTS direction_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    signal_name TEXT,
    original_direction TEXT,
    inverted_direction TEXT,
    reason TEXT,
    win_rate_original REAL,
    win_rate_inverted REAL,
    active INTEGER DEFAULT 1,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    expires_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_overrides_symbol ON direction_overrides(symbol);
CREATE INDEX IF NOT EXISTS idx_overrides_active ON direction_overrides(active);
"""

logger = logging.getLogger(__name__)


class DatabaseEngine:
    """
    Singleton Database Engine managing async SQLite connections
    with Replit-optimized WAL settings.
    """
    _instance: Optional['DatabaseEngine'] = None
    _lock = asyncio.Lock()
    
    def __init__(self):
        self.db_path = DB_PATH
        self._initialized = False
        self._init_lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls) -> 'DatabaseEngine':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def initialize(self) -> bool:
        """
        Idempotent initialization: Enables WAL mode, applies pragmas,
        and creates schema. Must be called at application startup.
        """
        if self._initialized:
            return True
        
        async with self._init_lock:
            if self._initialized:
                return True
            
            try:
                os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
                
                async with aiosqlite.connect(self.db_path) as db:
                    await db.executescript(INIT_SCRIPT)
                    await db.commit()
                    
                    cursor = await db.execute("PRAGMA journal_mode;")
                    mode = await cursor.fetchone()
                    if mode and mode[0].upper() != 'WAL':
                        logger.warning(f"Failed to set WAL mode. Current: {mode[0]}")
                        return False
                    
                    await db.executescript(SCHEMA_SCRIPT)
                    await db.commit()
                    
                    logger.info("Database initialized: WAL mode enabled, schema created")
                
                self._initialized = True
                return True
                
            except Exception as e:
                logger.error(f"Database initialization failed: {e}")
                return False
    
    @asynccontextmanager
    async def get_connection(self):
        """
        Async context manager for obtaining a configured connection.
        Usage: async with db.get_connection() as conn: ...
        """
        if not self._initialized:
            await self.initialize()
        
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()
    
    async def execute(self, sql: str, params: tuple = ()) -> Optional[aiosqlite.Cursor]:
        """Execute a single SQL statement."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(sql, params)
            await conn.commit()
            return cursor
    
    async def execute_many(self, sql: str, params_list: List[tuple]) -> int:
        """Execute SQL for multiple parameter sets. Returns affected row count."""
        async with self.get_connection() as conn:
            await conn.executemany(sql, params_list)
            await conn.commit()
            return conn.total_changes
    
    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetch a single row as a dictionary."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(sql, params)
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Fetch all rows as a list of dictionaries."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def run_checkpoint(self) -> bool:
        """
        Manually trigger a WAL checkpoint.
        Schedule periodically (e.g., every 5 minutes) via Layer 2.
        """
        try:
            async with self.get_connection() as conn:
                await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                logger.info("WAL checkpoint complete (TRUNCATE)")
            return True
        except Exception as e:
            logger.error(f"WAL checkpoint failed: {e}")
            return False
    
    async def get_state(self, key: str) -> Optional[str]:
        """Get a system state value."""
        row = await self.fetch_one(
            "SELECT value FROM system_state WHERE key = ?", (key,)
        )
        return row['value'] if row else None
    
    async def set_state(self, key: str, value: str) -> bool:
        """Set a system state value (upsert)."""
        try:
            async with self.get_connection() as conn:
                await conn.execute(
                    """INSERT INTO system_state (key, value, updated_at) 
                       VALUES (?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                    (key, value, int(time.time()))
                )
                await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to set state {key}: {e}")
            return False
    
    async def insert_trade(self, trade: Dict[str, Any]) -> Optional[int]:
        """Insert a trade record. Returns the row ID."""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """INSERT INTO trades 
                       (trade_id, symbol, side, direction, entry_price, exit_price,
                        quantity, margin_usd, leverage, profit_usd, fees_usd,
                        unrealized_usd, strategy, regime, entry_ts, exit_ts,
                        closed, paper_trade, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trade.get('trade_id'),
                        trade.get('symbol'),
                        trade.get('side'),
                        trade.get('direction'),
                        trade.get('entry_price'),
                        trade.get('exit_price'),
                        trade.get('quantity'),
                        trade.get('margin_usd'),
                        trade.get('leverage'),
                        trade.get('profit_usd'),
                        trade.get('fees_usd'),
                        trade.get('unrealized_usd'),
                        trade.get('strategy'),
                        trade.get('regime'),
                        trade.get('entry_ts'),
                        trade.get('exit_ts'),
                        1 if trade.get('closed') else 0,
                        1 if trade.get('paper_trade', True) else 0,
                        trade.get('metadata')
                    )
                )
                await conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to insert trade: {e}")
            return None
    
    async def insert_signal(self, signal: Dict[str, Any]) -> Optional[int]:
        """Insert a signal record. Returns the row ID."""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """INSERT INTO signals 
                       (signal_id, symbol, signal_name, direction, confidence,
                        ev_contribution, price_at_signal)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        signal.get('signal_id'),
                        signal.get('symbol'),
                        signal.get('signal_name'),
                        signal.get('direction'),
                        signal.get('confidence'),
                        signal.get('ev_contribution'),
                        signal.get('price_at_signal')
                    )
                )
                await conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to insert signal: {e}")
            return None
    
    async def log_execution(self, symbol: str, direction: str, 
                           inverted: bool = False, sizing_usd: float = None,
                           status: str = "PENDING") -> Optional[int]:
        """Log an execution intent."""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """INSERT INTO execution_log 
                       (ts, symbol, direction, inverted, sizing_usd, status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (int(time.time()), symbol, direction, 
                     1 if inverted else 0, sizing_usd, status)
                )
                await conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to log execution: {e}")
            return None
    
    async def log_audit(self, audit_type: str, expected: float, actual: float,
                       action: str = None, details: str = None) -> Optional[int]:
        """Log a governance audit entry."""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """INSERT INTO governance_audit 
                       (ts, audit_type, expected_value, actual_value, 
                        discrepancy, action_taken, details)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (int(time.time()), audit_type, expected, actual,
                     abs(expected - actual), action, details)
                )
                await conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to log audit: {e}")
            return None
    
    async def get_open_trades(self, symbol: str = None) -> List[Dict[str, Any]]:
        """Get all open trades, optionally filtered by symbol."""
        if symbol:
            return await self.fetch_all(
                "SELECT * FROM trades WHERE closed = 0 AND symbol = ? ORDER BY entry_ts DESC",
                (symbol,)
            )
        return await self.fetch_all(
            "SELECT * FROM trades WHERE closed = 0 ORDER BY entry_ts DESC"
        )
    
    async def get_recent_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent closed trades for analysis."""
        return await self.fetch_all(
            "SELECT * FROM trades WHERE closed = 1 ORDER BY exit_ts DESC LIMIT ?",
            (limit,)
        )
    
    async def get_closed_trades(self, limit: int = None, symbol: str = None) -> List[Dict[str, Any]]:
        """Fetch closed trades from SQLite with optional filters."""
        sql = "SELECT * FROM trades WHERE closed = 1"
        params = []
        
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        
        sql += " ORDER BY exit_ts DESC"
        
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        
        return await self.fetch_all(sql, tuple(params))
    
    async def get_signals(self, limit: int = None, signal_name: str = None) -> List[Dict[str, Any]]:
        """Fetch signals from SQLite with optional filters."""
        sql = "SELECT * FROM signals"
        params = []
        
        if signal_name:
            sql += " WHERE signal_name = ?"
            params.append(signal_name)
        
        sql += " ORDER BY created_at DESC"
        
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        
        return await self.fetch_all(sql, tuple(params))
    
    async def get_recent_signals(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Fetch signals from the last N hours."""
        cutoff = int(time.time()) - (hours * 3600)
        return await self.fetch_all(
            "SELECT * FROM signals WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,)
        )
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get database statistics for monitoring."""
        try:
            async with self.get_connection() as conn:
                stats = {}
                
                cursor = await conn.execute("SELECT COUNT(*) FROM trades WHERE closed = 0")
                row = await cursor.fetchone()
                stats['open_trades'] = row[0] if row else 0
                
                cursor = await conn.execute("SELECT COUNT(*) FROM trades WHERE closed = 1")
                row = await cursor.fetchone()
                stats['closed_trades'] = row[0] if row else 0
                
                cursor = await conn.execute("SELECT COUNT(*) FROM signals WHERE resolved = 0")
                row = await cursor.fetchone()
                stats['pending_signals'] = row[0] if row else 0
                
                cursor = await conn.execute("PRAGMA page_count;")
                row = await cursor.fetchone()
                page_count = row[0] if row else 0
                
                cursor = await conn.execute("PRAGMA page_size;")
                row = await cursor.fetchone()
                page_size = row[0] if row else 0
                
                stats['db_size_mb'] = round((page_count * page_size) / (1024 * 1024), 2)
                
                return stats
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}


def get_db() -> DatabaseEngine:
    """Convenience function to get the database singleton."""
    return DatabaseEngine.get_instance()


async def init_database() -> bool:
    """Initialize the database (call at startup)."""
    db = get_db()
    return await db.initialize()


def _run_async(coro, timeout=10.0):
    """
    Run an async coroutine from sync context using a dedicated event loop.
    Uses event-loop-safe pattern to avoid deadlocks when called from
    within an existing async context.
    
    Args:
        coro: Async coroutine to run
        timeout: Maximum time to wait (seconds). Default 10s.
    """
    old_loop = None
    try:
        old_loop = asyncio.get_event_loop()
    except RuntimeError:
        pass
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
    except asyncio.TimeoutError:
        logger.error(f"Async operation timed out after {timeout}s")
        return None
    finally:
        loop.close()
        if old_loop is not None and not old_loop.is_closed():
            asyncio.set_event_loop(old_loop)
        else:
            asyncio.set_event_loop(None)


def get_closed_trades_sync(limit: int = None, symbol: str = None) -> List[Dict[str, Any]]:
    """Synchronous wrapper for get_closed_trades with 5s timeout to prevent dashboard hang."""
    try:
        db = get_db()
        result = _run_async(db.get_closed_trades(limit=limit, symbol=symbol), timeout=5.0)
        return result if result is not None else []
    except Exception as e:
        logger.error(f"Sync get_closed_trades failed: {e}")
        return []


def get_open_trades_sync(symbol: str = None) -> List[Dict[str, Any]]:
    """Synchronous wrapper for get_open_trades."""
    try:
        db = get_db()
        return _run_async(db.get_open_trades(symbol=symbol))
    except Exception as e:
        logger.error(f"Sync get_open_trades failed: {e}")
        return []


def get_signals_sync(limit: int = None, signal_name: str = None) -> List[Dict[str, Any]]:
    """Synchronous wrapper for get_signals."""
    try:
        db = get_db()
        return _run_async(db.get_signals(limit=limit, signal_name=signal_name))
    except Exception as e:
        logger.error(f"Sync get_signals failed: {e}")
        return []


def get_recent_signals_sync(hours: int = 24) -> List[Dict[str, Any]]:
    """Synchronous wrapper for get_recent_signals."""
    try:
        db = get_db()
        return _run_async(db.get_recent_signals(hours=hours))
    except Exception as e:
        logger.error(f"Sync get_recent_signals failed: {e}")
        return []


def init_database_sync() -> bool:
    """Synchronous wrapper for init_database."""
    try:
        return _run_async(init_database())
    except Exception as e:
        logger.error(f"Sync init_database failed: {e}")
        return False


if __name__ == "__main__":
    async def test_db():
        print("Testing Database Engine...")
        db = get_db()
        
        success = await db.initialize()
        print(f"Initialization: {'OK' if success else 'FAILED'}")
        
        await db.set_state("test_key", "test_value")
        value = await db.get_state("test_key")
        print(f"State test: {value}")
        
        stats = await db.get_stats()
        print(f"Stats: {stats}")
        
        test_trade = {
            'trade_id': 'test_001',
            'symbol': 'BTCUSDT',
            'side': 'long',
            'direction': 'LONG',
            'entry_price': 90000.0,
            'margin_usd': 500.0,
            'leverage': 6.0,
            'strategy': 'Trend-Conservative',
            'entry_ts': int(time.time()),
            'paper_trade': True
        }
        row_id = await db.insert_trade(test_trade)
        print(f"Trade insert: row_id={row_id}")
        
        await db.run_checkpoint()
        print("Checkpoint: OK")
        
        print("\nDatabase test complete!")
    
    asyncio.run(test_db())
