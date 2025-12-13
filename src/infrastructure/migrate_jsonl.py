"""
Migration Utility: Import existing JSONL data into SQLite database.

This utility supports:
- Importing positions_futures.json (trade history)
- Importing signal_outcomes.jsonl (signal tracking)
- Dual-write mode for gradual migration
"""

import asyncio
import json
import os
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.infrastructure.database import get_db, init_database

logger = logging.getLogger(__name__)

POSITIONS_FILE = "logs/positions_futures.json"
SIGNAL_OUTCOMES_FILE = "logs/signal_outcomes.jsonl"


def parse_timestamp(ts_value) -> Optional[int]:
    """Convert various timestamp formats to Unix timestamp."""
    if ts_value is None:
        return None
    if isinstance(ts_value, (int, float)):
        if ts_value > 1e12:
            return int(ts_value / 1000)
        return int(ts_value)
    if isinstance(ts_value, str):
        try:
            dt = datetime.fromisoformat(ts_value.replace('Z', '+00:00'))
            return int(dt.timestamp())
        except:
            pass
    return None


async def import_positions(batch_size: int = 500, limit: int = None) -> Dict[str, int]:
    """
    Import positions from positions_futures.json into the trades table.
    Returns stats about imported records.
    """
    db = get_db()
    await db.initialize()
    
    stats = {'imported': 0, 'skipped': 0, 'errors': 0}
    
    if not os.path.exists(POSITIONS_FILE):
        logger.warning(f"Positions file not found: {POSITIONS_FILE}")
        return stats
    
    try:
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load positions file: {e}")
        return stats
    
    positions = []
    if isinstance(data, dict):
        for pos in data.get('open_positions', []):
            pos['closed'] = False
            positions.append(pos)
        for pos in data.get('closed_positions', []):
            pos['closed'] = True
            positions.append(pos)
    elif isinstance(data, list):
        positions = data
    else:
        positions = [data]
    
    if limit:
        positions = positions[:limit]
    
    batch = []
    
    for pos in positions:
        try:
            trade_id = pos.get('order_id') or pos.get('id') or f"legacy_{stats['imported']}"
            
            entry_ts = parse_timestamp(pos.get('entry_time') or pos.get('timestamp') or pos.get('entry_ts'))
            exit_ts = parse_timestamp(pos.get('exit_time') or pos.get('exit_ts'))
            
            side = pos.get('side', '').lower()
            direction = pos.get('direction', side.upper())
            
            trade = {
                'trade_id': trade_id,
                'symbol': pos.get('symbol'),
                'side': side,
                'direction': direction,
                'entry_price': pos.get('entry_price'),
                'exit_price': pos.get('exit_price'),
                'quantity': pos.get('quantity') or pos.get('size'),
                'margin_usd': pos.get('margin_usd') or pos.get('margin'),
                'leverage': pos.get('leverage', 1),
                'profit_usd': pos.get('profit_usd') or pos.get('profit') or pos.get('pnl'),
                'fees_usd': pos.get('fees_usd') or pos.get('fee') or pos.get('fees'),
                'unrealized_usd': pos.get('unrealized_usd') or pos.get('unrealized_pnl'),
                'strategy': pos.get('strategy'),
                'regime': pos.get('regime'),
                'entry_ts': entry_ts,
                'exit_ts': exit_ts,
                'closed': 1 if pos.get('closed', False) or exit_ts else 0,
                'paper_trade': 1 if pos.get('paper_trade', True) else 0,
                'metadata': json.dumps({k: v for k, v in pos.items() 
                                       if k not in ['symbol', 'side', 'direction', 'entry_price', 
                                                   'exit_price', 'quantity', 'margin_usd', 'leverage',
                                                   'profit_usd', 'fees_usd', 'strategy', 'regime']})
            }
            
            batch.append(trade)
            
            if len(batch) >= batch_size:
                imported = await _insert_trade_batch(db, batch)
                stats['imported'] += imported
                stats['skipped'] += len(batch) - imported
                batch = []
                
        except Exception as e:
            logger.error(f"Error processing position: {e}")
            stats['errors'] += 1
    
    if batch:
        imported = await _insert_trade_batch(db, batch)
        stats['imported'] += imported
        stats['skipped'] += len(batch) - imported
    
    logger.info(f"Position import complete: {stats}")
    return stats


async def _insert_trade_batch(db, batch: List[Dict]) -> int:
    """Insert a batch of trades, handling duplicates."""
    imported = 0
    async with db.get_connection() as conn:
        for trade in batch:
            try:
                await conn.execute(
                    """INSERT OR IGNORE INTO trades 
                       (trade_id, symbol, side, direction, entry_price, exit_price,
                        quantity, margin_usd, leverage, profit_usd, fees_usd,
                        unrealized_usd, strategy, regime, entry_ts, exit_ts,
                        closed, paper_trade, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trade['trade_id'], trade['symbol'], trade['side'],
                        trade['direction'], trade['entry_price'], trade['exit_price'],
                        trade['quantity'], trade['margin_usd'], trade['leverage'],
                        trade['profit_usd'], trade['fees_usd'], trade['unrealized_usd'],
                        trade['strategy'], trade['regime'], trade['entry_ts'],
                        trade['exit_ts'], trade['closed'], trade['paper_trade'],
                        trade['metadata']
                    )
                )
                imported += 1
            except Exception as e:
                logger.debug(f"Skipped duplicate or error: {e}")
        await conn.commit()
    return imported


async def import_signal_outcomes(batch_size: int = 500, limit: int = None) -> Dict[str, int]:
    """
    Import signal outcomes from signal_outcomes.jsonl into the signals table.
    Returns stats about imported records.
    """
    db = get_db()
    await db.initialize()
    
    stats = {'imported': 0, 'skipped': 0, 'errors': 0}
    
    if not os.path.exists(SIGNAL_OUTCOMES_FILE):
        logger.warning(f"Signal outcomes file not found: {SIGNAL_OUTCOMES_FILE}")
        return stats
    
    batch = []
    line_count = 0
    
    try:
        with open(SIGNAL_OUTCOMES_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                    
                line_count += 1
                if limit and line_count > limit:
                    break
                
                try:
                    record = json.loads(line)
                    
                    signal_id = record.get('signal_id') or f"sig_{line_count}"
                    
                    signal = {
                        'signal_id': signal_id,
                        'symbol': record.get('symbol'),
                        'signal_name': record.get('signal_name'),
                        'direction': record.get('direction'),
                        'confidence': record.get('confidence'),
                        'ev_contribution': record.get('ev') or record.get('ev_contribution'),
                        'price_at_signal': record.get('price_at_signal') or record.get('entry_price'),
                        'resolved_price': record.get('resolved_price') or record.get('exit_price'),
                        'resolved': 1 if record.get('resolved', False) or record.get('exit_price') else 0,
                        'outcome': record.get('outcome'),
                        'created_at': parse_timestamp(record.get('timestamp') or record.get('created_at')),
                        'resolved_at': parse_timestamp(record.get('resolved_at'))
                    }
                    
                    batch.append(signal)
                    
                    if len(batch) >= batch_size:
                        imported = await _insert_signal_batch(db, batch)
                        stats['imported'] += imported
                        stats['skipped'] += len(batch) - imported
                        batch = []
                        
                except json.JSONDecodeError:
                    stats['errors'] += 1
                except Exception as e:
                    logger.error(f"Error processing signal: {e}")
                    stats['errors'] += 1
    
    except Exception as e:
        logger.error(f"Failed to read signal outcomes file: {e}")
        return stats
    
    if batch:
        imported = await _insert_signal_batch(db, batch)
        stats['imported'] += imported
        stats['skipped'] += len(batch) - imported
    
    logger.info(f"Signal import complete: {stats}")
    return stats


async def _insert_signal_batch(db, batch: List[Dict]) -> int:
    """Insert a batch of signals, handling duplicates."""
    imported = 0
    async with db.get_connection() as conn:
        for signal in batch:
            try:
                await conn.execute(
                    """INSERT OR IGNORE INTO signals 
                       (signal_id, symbol, signal_name, direction, confidence,
                        ev_contribution, price_at_signal, resolved_price, resolved,
                        outcome, created_at, resolved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        signal['signal_id'], signal['symbol'], signal['signal_name'],
                        signal['direction'], signal['confidence'], signal['ev_contribution'],
                        signal['price_at_signal'], signal['resolved_price'], signal['resolved'],
                        signal['outcome'], signal['created_at'], signal['resolved_at']
                    )
                )
                imported += 1
            except Exception as e:
                logger.debug(f"Skipped duplicate or error: {e}")
        await conn.commit()
    return imported


async def run_full_migration(positions_limit: int = None, signals_limit: int = None) -> Dict[str, Any]:
    """
    Run full migration of both positions and signals.
    Returns combined stats.
    """
    logger.info("Starting full JSONL to SQLite migration...")
    
    await init_database()
    
    print("Importing positions...")
    pos_stats = await import_positions(limit=positions_limit)
    print(f"  Positions: {pos_stats}")
    
    print("Importing signal outcomes...")
    sig_stats = await import_signal_outcomes(limit=signals_limit)
    print(f"  Signals: {sig_stats}")
    
    db = get_db()
    await db.run_checkpoint()
    
    final_stats = await db.get_stats()
    print(f"\nFinal database stats: {final_stats}")
    
    return {
        'positions': pos_stats,
        'signals': sig_stats,
        'database': final_stats
    }


class DualWriteAdapter:
    """
    Adapter for writing to both JSONL and SQLite during migration period.
    Ensures data consistency while transitioning storage backends.
    """
    
    def __init__(self, enable_sqlite: bool = True, enable_jsonl: bool = True):
        self.enable_sqlite = enable_sqlite
        self.enable_jsonl = enable_jsonl
        self._db = None
    
    async def _get_db(self):
        if self._db is None:
            self._db = get_db()
            await self._db.initialize()
        return self._db
    
    async def write_trade(self, trade: Dict[str, Any], jsonl_path: str = POSITIONS_FILE) -> bool:
        """Write a trade to SQLite only (JSONL is handled by save_futures_positions)."""
        success = True
        
        if self.enable_sqlite:
            try:
                db = await self._get_db()
                await db.insert_trade(trade)
            except Exception as e:
                logger.error(f"SQLite trade write failed: {e}")
                success = False
        
        return success
    
    async def write_signal(self, signal: Dict[str, Any], jsonl_path: str = SIGNAL_OUTCOMES_FILE) -> bool:
        """Write a signal to SQLite only (JSONL is handled by the caller)."""
        success = True
        
        if self.enable_sqlite:
            try:
                db = await self._get_db()
                await db.insert_signal(signal)
            except Exception as e:
                logger.error(f"SQLite signal write failed: {e}")
                success = False
        
        return success
    
    def write_trade_sync(self, trade: Dict[str, Any]) -> bool:
        """Synchronous wrapper for write_trade - SQLite only.
        
        Uses a dedicated event loop to avoid deadlocks when called from
        within an existing async context. Preserves and restores the
        original event loop to prevent breaking other async code.
        """
        try:
            old_loop = None
            try:
                old_loop = asyncio.get_event_loop()
            except RuntimeError:
                pass
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.write_trade(trade))
            finally:
                loop.close()
                if old_loop is not None and not old_loop.is_closed():
                    asyncio.set_event_loop(old_loop)
                else:
                    asyncio.set_event_loop(None)
        except Exception as e:
            logger.error(f"Sync trade write failed: {e}")
            return False
    
    def write_signal_sync(self, signal: Dict[str, Any]) -> bool:
        """Synchronous wrapper for write_signal - SQLite only.
        
        Uses a dedicated event loop to avoid deadlocks when called from
        within an existing async context. Preserves and restores the
        original event loop to prevent breaking other async code.
        """
        try:
            old_loop = None
            try:
                old_loop = asyncio.get_event_loop()
            except RuntimeError:
                pass
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.write_signal(signal))
            finally:
                loop.close()
                if old_loop is not None and not old_loop.is_closed():
                    asyncio.set_event_loop(old_loop)
                else:
                    asyncio.set_event_loop(None)
        except Exception as e:
            logger.error(f"Sync signal write failed: {e}")
            return False


_dual_writer: Optional[DualWriteAdapter] = None


def get_dual_writer() -> DualWriteAdapter:
    """Get or create the singleton DualWriteAdapter instance.
    
    Phase 4 SQLite Cutover: JSONL writes are now DISABLED.
    SQLite is the primary data store. JSONL files remain as read-only backups.
    To rollback, change enable_jsonl=True.
    """
    global _dual_writer
    if _dual_writer is None:
        _dual_writer = DualWriteAdapter(enable_sqlite=True, enable_jsonl=True)
    return _dual_writer


def count_jsonl_trades() -> Dict[str, int]:
    """Count trades in the JSONL positions file."""
    counts = {'open': 0, 'closed': 0, 'total': 0}
    if not os.path.exists(POSITIONS_FILE):
        return counts
    try:
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            counts['open'] = len(data.get('open_positions', []))
            counts['closed'] = len(data.get('closed_positions', []))
            counts['total'] = counts['open'] + counts['closed']
    except Exception as e:
        logger.error(f"Error counting JSONL trades: {e}")
    return counts


def count_jsonl_signals() -> int:
    """Count signals in the signal_outcomes.jsonl file."""
    count = 0
    if not os.path.exists(SIGNAL_OUTCOMES_FILE):
        return count
    try:
        with open(SIGNAL_OUTCOMES_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    count += 1
    except Exception as e:
        logger.error(f"Error counting JSONL signals: {e}")
    return count


async def check_parity() -> Dict[str, Any]:
    """
    Verify JSONL and SQLite data are in sync.
    Returns comparison stats and any discrepancies.
    """
    db = get_db()
    await db.initialize()
    
    jsonl_trades = count_jsonl_trades()
    jsonl_signal_count = count_jsonl_signals()
    
    sqlite_stats = await db.get_stats()
    sqlite_trade_count = sqlite_stats.get('open_trades', 0) + sqlite_stats.get('closed_trades', 0)
    
    sqlite_signal_count = 0
    try:
        result = await db.fetch_one("SELECT COUNT(*) as cnt FROM signals")
        if result:
            sqlite_signal_count = result['cnt']
    except Exception as e:
        logger.error(f"Error counting SQLite signals: {e}")
    
    trades_in_sync = jsonl_trades['total'] == sqlite_trade_count
    signals_in_sync = jsonl_signal_count == sqlite_signal_count
    
    return {
        'trades': {
            'jsonl': jsonl_trades,
            'sqlite': {
                'open': sqlite_stats.get('open_trades', 0),
                'closed': sqlite_stats.get('closed_trades', 0),
                'total': sqlite_trade_count
            }
        },
        'signals': {
            'jsonl': jsonl_signal_count,
            'sqlite': sqlite_signal_count
        },
        'in_sync': trades_in_sync and signals_in_sync,
        'trades_in_sync': trades_in_sync,
        'signals_in_sync': signals_in_sync
    }


def check_parity_sync() -> Dict[str, Any]:
    """Synchronous wrapper for check_parity.
    
    Uses a dedicated event loop to avoid deadlocks when called from
    within an existing async context. Preserves and restores the
    original event loop to prevent breaking other async code.
    """
    try:
        old_loop = None
        try:
            old_loop = asyncio.get_event_loop()
        except RuntimeError:
            pass
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(check_parity())
        finally:
            loop.close()
            if old_loop is not None and not old_loop.is_closed():
                asyncio.set_event_loop(old_loop)
            else:
                asyncio.set_event_loop(None)
    except Exception as e:
        logger.error(f"Sync parity check failed: {e}")
        return {'error': str(e), 'in_sync': False}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        print("=" * 60)
        print("JSONL to SQLite Migration Utility")
        print("=" * 60)
        
        results = await run_full_migration(
            positions_limit=1000,
            signals_limit=5000
        )
        
        print("\n" + "=" * 60)
        print("Migration Summary:")
        print(f"  Trades imported: {results['positions']['imported']}")
        print(f"  Signals imported: {results['signals']['imported']}")
        print(f"  Database size: {results['database']['db_size_mb']} MB")
        print("=" * 60)
    
    asyncio.run(main())
