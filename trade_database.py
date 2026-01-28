"""
Trade Database Module v2 (Token-Centric)

SQLite storage for:
- Market metadata (token → timeframe mapping)
- Whale timeframe stats (tier assignments)
- Whale incremental stats (running totals from resolution)
- Whale pending trades (awaiting resolution)
- Token resolution cache (outcomes)

No longer stores raw blockchain trades - whale data comes from
token-level analysis (standalone script) and resolution tracking.
"""

import sqlite3
import json
import os
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict
from contextlib import contextmanager

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def get_db_path() -> str:
    """Get database path from environment or use default"""
    return os.environ.get('DB_PATH', 'trades.db')


class TradeDatabase:
    """
    SQLite-based storage for whale tracking:
    - Whale tiers by timeframe
    - Incremental stats from resolution
    - Pending trades awaiting resolution
    - Token resolution cache
    """

    def __init__(self, db_path: str = "trades.db"):
        self.db_path = db_path
        self.conn = None
        self._lock = threading.Lock()  # Thread-safe access
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with optimized schema"""
        # Ensure directory exists before connecting
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            print(f"📁 Created database directory: {db_dir}")

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrent access
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        # Create metadata table for tracking state
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # =======================================================================
        # TOKEN_TIMEFRAMES: Master table for all market tokens
        # Updated as: new tokens discovered, markets resolve
        # =======================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS token_timeframes (
                token_id TEXT PRIMARY KEY,
                timeframe TEXT DEFAULT 'unknown',
                question TEXT,
                resolved INTEGER DEFAULT 0,
                outcome TEXT,
                token_side TEXT,
                whale_net TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_token_tf_timeframe ON token_timeframes(timeframe)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_token_tf_resolved ON token_timeframes(resolved)")

        # =======================================================================
        # WHALE_TIMEFRAME_STATS: Master table for all whales by tier
        # Source of truth for who we monitor
        # =======================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS whale_timeframe_stats (
                address TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                trade_count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                volume REAL DEFAULT 0,
                profit REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (address, timeframe)
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_whale_stats_timeframe ON whale_timeframe_stats(timeframe)")

        # =======================================================================
        # WHALE_INCREMENTAL_STATS: Running totals from live resolution
        # Used to discover/promote new whales
        # =======================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS whale_incremental_stats (
                address TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                net_pnl REAL DEFAULT 0,
                volume REAL DEFAULT 0,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (address, timeframe)
            )
        """)

        # =======================================================================
        # WHALE_PENDING_TRADES: Trades awaiting resolution
        # =======================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS whale_pending_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id TEXT NOT NULL,
                whale_address TEXT NOT NULL,
                is_maker INTEGER NOT NULL,
                maker_amount INTEGER NOT NULL,
                taker_amount INTEGER NOT NULL,
                token_side TEXT,
                timeframe TEXT NOT NULL,
                expected_resolution TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_resolution ON whale_pending_trades(expected_resolution)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_token ON whale_pending_trades(token_id)")

        # =======================================================================
        # DRY_RUN_POSITIONS: Simulated positions for paper trading
        # Persists across restarts so we can track resolution
        # =======================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS dry_run_positions (
                id TEXT PRIMARY KEY,
                token_id TEXT NOT NULL,
                whale_address TEXT,
                side TEXT NOT NULL,
                position_size REAL NOT NULL,
                confidence REAL NOT NULL,
                market_timeframe TEXT,
                market_question TEXT,
                entry_price REAL,
                opened_at TEXT NOT NULL,
                expected_resolution TEXT,
                status TEXT DEFAULT 'PENDING',
                resolved_at TEXT,
                market_outcome TEXT,
                is_win INTEGER,
                pnl REAL,
                extra_data TEXT
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_dryrun_status ON dry_run_positions(status)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_dryrun_token ON dry_run_positions(token_id)")

        self.conn.commit()
        print(f"Trade database initialized: {self.db_path}")

    @contextmanager
    def transaction(self):
        """
        Context manager for transaction isolation.
        Uses BEGIN IMMEDIATE to prevent concurrent writes.

        Usage:
            with db.transaction():
                db.conn.execute(...)
                db.conn.execute(...)
            # Auto-commits on success, rollbacks on error
        """
        with self._lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                yield
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    # =========================================================================
    # METADATA
    # =========================================================================

    def get_metadata(self, key: str) -> Optional[str]:
        """Get a metadata value"""
        cursor = self.conn.execute(
            "SELECT value FROM scan_metadata WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row['value'] if row else None

    def set_metadata(self, key: str, value: str):
        """Set a metadata value"""
        with self._lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO scan_metadata (key, value)
                VALUES (?, ?)
            """, (key, value))
            self.conn.commit()

    # =========================================================================
    # TOKEN_TIMEFRAMES: Master table for market tokens
    # =========================================================================

    def get_cached_timeframe(self, token_id: str) -> Optional[str]:
        """Get cached timeframe for a token"""
        cursor = self.conn.execute(
            "SELECT timeframe FROM token_timeframes WHERE token_id = ?",
            (token_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_cached_market_info(self, token_id: str) -> Optional[Dict]:
        """Get cached market info (timeframe and question) for a token"""
        cursor = self.conn.execute(
            "SELECT timeframe, question FROM token_timeframes WHERE token_id = ?",
            (token_id,)
        )
        row = cursor.fetchone()
        if row:
            return {'timeframe': row[0], 'question': row[1]}
        return None

    def get_token_timeframe(self, token_id: str) -> Optional[Dict]:
        """Get full token_timeframes record"""
        cursor = self.conn.execute("""
            SELECT token_id, timeframe, question, resolved, outcome, token_side, whale_net
            FROM token_timeframes WHERE token_id = ?
        """, (token_id,))
        row = cursor.fetchone()
        if row:
            return {
                'token_id': row[0],
                'timeframe': row[1],
                'question': row[2],
                'resolved': bool(row[3]),
                'outcome': row[4],
                'token_side': row[5],
                'whale_net': row[6]
            }
        return None

    def add_token_timeframe(self, token_id: str, timeframe: str, question: str = '',
                            resolved: bool = False, outcome: str = None,
                            token_side: str = None, whale_net: str = None):
        """Add or update a token in token_timeframes"""
        with self._lock:
            self.conn.execute("""
                INSERT INTO token_timeframes (token_id, timeframe, question, resolved, outcome, token_side, whale_net)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_id) DO UPDATE SET
                    timeframe = COALESCE(excluded.timeframe, timeframe),
                    question = COALESCE(excluded.question, question),
                    resolved = COALESCE(excluded.resolved, resolved),
                    outcome = COALESCE(excluded.outcome, outcome),
                    token_side = COALESCE(excluded.token_side, token_side),
                    whale_net = COALESCE(excluded.whale_net, whale_net),
                    resolved_at = CASE WHEN excluded.resolved = 1 THEN CURRENT_TIMESTAMP ELSE resolved_at END
            """, (token_id, timeframe, question, 1 if resolved else 0, outcome, token_side, whale_net))
            self.conn.commit()

    def cache_token_timeframe(self, token_id: str, timeframe: str, question: str = ''):
        """Cache a token's timeframe (alias for add_token_timeframe)"""
        self.add_token_timeframe(token_id, timeframe, question)

    def update_token_resolution(self, token_id: str, resolved: bool, outcome: str = None,
                                 token_side: str = None, whale_net: str = None):
        """Update resolution status for a token"""
        with self._lock:
            self.conn.execute("""
                UPDATE token_timeframes
                SET resolved = ?, outcome = ?, token_side = ?, whale_net = ?,
                    resolved_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE resolved_at END
                WHERE token_id = ?
            """, (1 if resolved else 0, outcome, token_side, whale_net, 1 if resolved else 0, token_id))
            self.conn.commit()

    def get_token_timeframes_stats(self) -> dict:
        """Get stats about token_timeframes table"""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN timeframe = 'unknown' THEN 1 ELSE 0 END) as unknown,
                SUM(CASE WHEN timeframe = '15min' THEN 1 ELSE 0 END) as min15,
                SUM(CASE WHEN timeframe = 'hourly' THEN 1 ELSE 0 END) as hourly,
                SUM(CASE WHEN timeframe = '4hour' THEN 1 ELSE 0 END) as hour4,
                SUM(CASE WHEN timeframe = 'daily' THEN 1 ELSE 0 END) as daily,
                SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved_count
            FROM token_timeframes
        """)
        row = cursor.fetchone()
        return {
            'total': row[0] or 0,
            'unknown': row[1] or 0,
            'known': (row[0] or 0) - (row[1] or 0),
            '15min': row[2] or 0,
            'hourly': row[3] or 0,
            '4hour': row[4] or 0,
            'daily': row[5] or 0,
            'resolved': row[6] or 0
        }

    def get_winning_whales_for_token(self, token_id: str, min_pnl: float = 500.0) -> list:
        """
        Get addresses that won > min_pnl on a token from whale_net.

        Parses the whale_net string: "0xADDR:+123.45|0xADDR2:-67.89"
        Returns only addresses with PnL >= min_pnl.
        """
        cursor = self.conn.execute(
            "SELECT whale_net FROM token_timeframes WHERE token_id = ?",
            (token_id,)
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return []

        winners = []
        whale_net = row[0].strip('[]')
        for entry in whale_net.split('|'):
            if ':' in entry:
                addr, pnl_str = entry.split(':', 1)
                try:
                    pnl = float(pnl_str.replace('+', ''))
                    if pnl >= min_pnl:
                        winners.append({'address': addr.strip().lower(), 'pnl': pnl})
                except ValueError:
                    continue

        return sorted(winners, key=lambda x: x['pnl'], reverse=True)

    # =========================================================================
    # WHALE TIMEFRAME STATS (tier assignments)
    # =========================================================================

    def get_timeframe_tiers(self) -> Dict[str, List[Dict]]:
        """Get cached timeframe tier assignments"""
        tiers = {'15min': [], 'hourly': [], '4hour': [], 'daily': []}

        cursor = self.conn.execute("""
            SELECT address, timeframe, trade_count, wins, volume, profit, win_rate
            FROM whale_timeframe_stats
            ORDER BY profit DESC
        """)

        for row in cursor:
            tf = row[1]
            if tf in tiers:
                tiers[tf].append({
                    'address': row[0],
                    'specialty': tf,
                    'trades': row[2],
                    'wins': row[3],
                    'win_rate': row[6],
                    'volume': row[4],
                    'profit': row[5]
                })

        return tiers

    def get_all_tier_whales(self) -> set:
        """Get set of all whale addresses in any tier"""
        cursor = self.conn.execute("SELECT DISTINCT address FROM whale_timeframe_stats")
        return {row[0].lower() for row in cursor}

    def is_whale_in_tier(self, address: str) -> bool:
        """Check if an address is in any tier"""
        cursor = self.conn.execute(
            "SELECT 1 FROM whale_timeframe_stats WHERE address = ? LIMIT 1",
            (address.lower(),)
        )
        return cursor.fetchone() is not None

    def promote_whale_to_tier(self, address: str, timeframe: str, trades: int, wins: int,
                               losses: int, volume: float, profit: float, win_rate: float):
        """
        Add or update a whale in whale_timeframe_stats (tier promotion).
        """
        with self._lock:
            self.conn.execute("""
                INSERT INTO whale_timeframe_stats
                (address, timeframe, trade_count, wins, losses, volume, profit, win_rate, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(address, timeframe) DO UPDATE SET
                    trade_count = excluded.trade_count,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    volume = excluded.volume,
                    profit = excluded.profit,
                    win_rate = excluded.win_rate,
                    updated_at = CURRENT_TIMESTAMP
            """, (address.lower(), timeframe, trades, wins, losses, volume, profit, win_rate))
            self.conn.commit()

    def clear_timeframe_cache(self):
        """Clear cached tier assignments to force re-analysis"""
        with self._lock:
            self.conn.execute("DELETE FROM whale_timeframe_stats")
            self.conn.commit()
        print("   Cleared timeframe cache")

    # =========================================================================
    # WHALE INCREMENTAL STATS (running totals from resolution)
    # =========================================================================

    def update_whale_incremental_stats(self, address: str, timeframe: str, pnl: float, volume: float = 0):
        """
        Incrementally update whale stats from a single trade.
        Called when a resolved trade is processed.
        """
        is_win = 1 if pnl > 0 else 0
        is_loss = 1 if pnl < 0 else 0

        with self._lock:
            self.conn.execute("""
                INSERT INTO whale_incremental_stats (address, timeframe, trades, wins, losses, net_pnl, volume, last_updated)
                VALUES (?, ?, 1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(address, timeframe) DO UPDATE SET
                    trades = trades + 1,
                    wins = wins + excluded.wins,
                    losses = losses + excluded.losses,
                    net_pnl = net_pnl + excluded.net_pnl,
                    volume = volume + excluded.volume,
                    last_updated = CURRENT_TIMESTAMP
            """, (address.lower(), timeframe, is_win, is_loss, pnl, volume))
            self.conn.commit()

    def get_whale_incremental_stats(self, address: str) -> Dict[str, Dict]:
        """Get incremental stats for a whale across all timeframes"""
        cursor = self.conn.execute("""
            SELECT timeframe, trades, wins, losses, net_pnl, volume
            FROM whale_incremental_stats
            WHERE address = ?
        """, (address.lower(),))

        stats = {}
        for row in cursor:
            stats[row[0]] = {
                'trades': row[1],
                'wins': row[2],
                'losses': row[3],
                'net_pnl': row[4],
                'volume': row[5],
                'win_rate': row[2] / row[1] if row[1] > 0 else 0
            }
        return stats

    def get_tier_candidates_from_incremental(self, min_trades: int = 10) -> list:
        """
        Get whales from incremental stats who might qualify for tier promotion.
        Returns: [(address, timeframe, trades, net_pnl, win_rate), ...]
        """
        cursor = self.conn.execute("""
            SELECT
                address,
                timeframe,
                trades,
                net_pnl,
                CASE WHEN trades > 0 THEN CAST(wins AS REAL) / trades ELSE 0 END as win_rate
            FROM whale_incremental_stats
            WHERE trades >= ?
            ORDER BY net_pnl DESC
        """, (min_trades,))
        return cursor.fetchall()

    def get_top_performers_from_observations(self, min_trades: int = 3, min_win_rate: float = 0.80, limit: int = 20) -> list:
        """
        Get top performing whales from observations analytics (trades we didn't copy).
        These are candidates to be added to our whale tracking list.

        Args:
            min_trades: Minimum number of resolved trades required
            min_win_rate: Minimum win rate (0.80 = 80%)
            limit: Maximum number of whales to return

        Returns: List of dicts with whale performance data
        """
        cursor = self.conn.execute("""
            SELECT
                address,
                timeframe,
                trades,
                wins,
                losses,
                net_pnl,
                volume,
                CASE WHEN trades > 0 THEN CAST(wins AS REAL) / trades ELSE 0 END as win_rate
            FROM whale_incremental_stats
            WHERE trades >= ?
            AND CASE WHEN trades > 0 THEN CAST(wins AS REAL) / trades ELSE 0 END >= ?
            ORDER BY net_pnl DESC
            LIMIT ?
        """, (min_trades, min_win_rate, limit))

        performers = []
        for row in cursor:
            performers.append({
                'address': row[0],
                'timeframe': row[1],
                'trades': row[2],
                'wins': row[3],
                'losses': row[4],
                'net_pnl': row[5] or 0,
                'volume': row[6] or 0,
                'win_rate': row[7] or 0
            })
        return performers

    def promote_top_performers_to_tiers(self, min_trades: int = 5, min_win_rate: float = 0.80) -> int:
        """
        Automatically promote top performers from whale observations to the active whale tier list.

        This takes whales from whale_incremental_stats (observations) and promotes them
        to whale_timeframe_stats (active monitoring list) if they meet the criteria.

        Args:
            min_trades: Minimum resolved trades required
            min_win_rate: Minimum win rate (0.80 = 80%)

        Returns: Number of whales promoted
        """
        top_performers = self.get_top_performers_from_observations(min_trades, min_win_rate, limit=50)

        # Get existing tier whales to avoid duplicates
        existing = self.get_all_tier_whales()

        promoted = 0
        for perf in top_performers:
            addr = perf['address'].lower()

            # Skip if already in tier
            if addr in existing:
                continue

            # Promote to tier
            self.promote_whale_to_tier(
                address=addr,
                timeframe=perf['timeframe'],
                trades=perf['trades'],
                wins=perf['wins'],
                losses=perf['losses'],
                volume=perf['volume'],
                profit=perf['net_pnl'],
                win_rate=perf['win_rate']
            )
            promoted += 1

        if promoted > 0:
            print(f"   🐋 Promoted {promoted} top performers from observations to active tier list")

        return promoted

    def prune_underperforming_whales(self, min_win_rate: float = 0.80, min_trades: int = 5) -> int:
        """
        Remove whales from whale_timeframe_stats that have dropped below the minimum win rate.

        Args:
            min_win_rate: Minimum win rate to keep (0.80 = 80%)
            min_trades: Only prune whales with at least this many trades (to avoid pruning new whales)

        Returns: Number of whales pruned
        """
        # Find underperforming whales
        cursor = self.conn.execute("""
            SELECT address, timeframe, win_rate, trade_count
            FROM whale_timeframe_stats
            WHERE trade_count >= ?
            AND win_rate < ?
        """, (min_trades, min_win_rate))

        to_prune = cursor.fetchall()

        if not to_prune:
            return 0

        # Remove them from the tier
        with self._lock:
            for row in to_prune:
                address, timeframe = row[0], row[1]
                self.conn.execute("""
                    DELETE FROM whale_timeframe_stats
                    WHERE address = ? AND timeframe = ?
                """, (address.lower(), timeframe))
            self.conn.commit()

        if len(to_prune) > 0:
            print(f"   🧹 Pruned {len(to_prune)} whales with win rate below {min_win_rate*100:.0f}%")
            for row in to_prune[:5]:  # Show first 5
                print(f"      - {row[0][:12]}... ({row[1]}) - {row[2]*100:.1f}% win rate, {row[3]} trades")

        return len(to_prune)

    def get_incremental_stats_summary(self) -> dict:
        """Get summary of incremental stats for logging"""
        cursor = self.conn.execute("""
            SELECT
                COUNT(DISTINCT address) as unique_addresses,
                SUM(trades) as total_trades,
                SUM(net_pnl) as total_pnl
            FROM whale_incremental_stats
        """)
        row = cursor.fetchone()
        return {
            'unique_addresses': row[0] or 0,
            'total_trades': row[1] or 0,
            'total_pnl': row[2] or 0
        }

    def get_whale_observations_analytics(self) -> dict:
        """
        Get comprehensive analytics on whale observations (trades we watched but didn't copy).
        This shows "what we learned" from watching whale behavior.
        """
        # Overall stats
        cursor = self.conn.execute("""
            SELECT
                COUNT(DISTINCT address) as unique_whales,
                SUM(trades) as total_trades,
                SUM(wins) as total_wins,
                SUM(losses) as total_losses,
                SUM(net_pnl) as total_pnl,
                SUM(volume) as total_volume
            FROM whale_incremental_stats
        """)
        overall = cursor.fetchone()

        # Performance by timeframe
        cursor = self.conn.execute("""
            SELECT
                timeframe,
                COUNT(DISTINCT address) as whale_count,
                SUM(trades) as trades,
                SUM(wins) as wins,
                SUM(losses) as losses,
                SUM(net_pnl) as net_pnl,
                CASE WHEN SUM(trades) > 0
                    THEN CAST(SUM(wins) AS REAL) / SUM(trades) * 100
                    ELSE 0 END as win_rate
            FROM whale_incremental_stats
            GROUP BY timeframe
            ORDER BY net_pnl DESC
        """)
        by_timeframe = {}
        for row in cursor:
            by_timeframe[row[0]] = {
                'whale_count': row[1],
                'trades': row[2],
                'wins': row[3],
                'losses': row[4],
                'net_pnl': row[5] or 0,
                'win_rate': round(row[6] or 0, 1)
            }

        # Top performing whales we could have copied
        cursor = self.conn.execute("""
            SELECT
                address,
                timeframe,
                trades,
                wins,
                losses,
                net_pnl,
                CASE WHEN trades > 0 THEN CAST(wins AS REAL) / trades * 100 ELSE 0 END as win_rate
            FROM whale_incremental_stats
            WHERE trades >= 3
            ORDER BY net_pnl DESC
            LIMIT 10
        """)
        top_performers = []
        for row in cursor:
            top_performers.append({
                'address': row[0],
                'timeframe': row[1],
                'trades': row[2],
                'wins': row[3],
                'losses': row[4],
                'net_pnl': row[5] or 0,
                'win_rate': round(row[6] or 0, 1)
            })

        # Worst performers (whales to avoid)
        cursor = self.conn.execute("""
            SELECT
                address,
                timeframe,
                trades,
                wins,
                losses,
                net_pnl,
                CASE WHEN trades > 0 THEN CAST(wins AS REAL) / trades * 100 ELSE 0 END as win_rate
            FROM whale_incremental_stats
            WHERE trades >= 3
            ORDER BY net_pnl ASC
            LIMIT 10
        """)
        worst_performers = []
        for row in cursor:
            worst_performers.append({
                'address': row[0],
                'timeframe': row[1],
                'trades': row[2],
                'wins': row[3],
                'losses': row[4],
                'net_pnl': row[5] or 0,
                'win_rate': round(row[6] or 0, 1)
            })

        # Pending observations count
        pending = self.get_pending_trades_summary()

        total_trades = overall[2] or 0
        total_wins = overall[3] or 0
        overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

        return {
            'summary': {
                'unique_whales_observed': overall[0] or 0,
                'total_resolved_trades': overall[2] or 0,
                'overall_win_rate': round(overall_win_rate, 1),
                'total_pnl_observed': round(overall[4] or 0, 2),
                'pending_observations': pending.get('total', 0)
            },
            'by_timeframe': by_timeframe,
            'top_performers': top_performers,
            'worst_performers': worst_performers,
            'insights': {
                'best_timeframe': max(by_timeframe.items(), key=lambda x: x[1]['net_pnl'])[0] if by_timeframe else None,
                'most_active_timeframe': max(by_timeframe.items(), key=lambda x: x[1]['trades'])[0] if by_timeframe else None,
                'missed_profit': round(sum(w['net_pnl'] for w in top_performers if w['net_pnl'] > 0), 2),
                'avoided_loss': round(abs(sum(w['net_pnl'] for w in worst_performers if w['net_pnl'] < 0)), 2)
            }
        }

    # =========================================================================
    # WHALE PENDING TRADES (for resolution-based quality tracking)
    # =========================================================================

    def add_pending_whale_trade(self, token_id: str, whale_address: str, is_maker: bool,
                                 maker_amount: int, taker_amount: int, token_side: str,
                                 timeframe: str, expected_resolution: str):
        """
        Add a whale trade to pending queue for resolution tracking.

        Args:
            token_id: The CLOB token ID
            whale_address: Whale's address
            is_maker: True if whale is maker, False if taker
            maker_amount: Maker amount in wei (outcome tokens)
            taker_amount: Taker amount in wei (USDC * 1e6)
            token_side: Which side this token represents (YES/NO or outcome name)
            timeframe: Market timeframe (15min/hourly/4hour/daily)
            expected_resolution: ISO timestamp when market should resolve
        """
        with self._lock:
            self.conn.execute("""
                INSERT INTO whale_pending_trades
                (token_id, whale_address, is_maker, maker_amount, taker_amount, token_side, timeframe, expected_resolution)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (token_id, whale_address.lower(), 1 if is_maker else 0,
                  maker_amount, taker_amount, token_side, timeframe, expected_resolution))
            self.conn.commit()

    def get_pending_trades_to_resolve(self, current_time: str = None) -> list:
        """
        Get pending trades where expected resolution time has passed.
        Returns list of dicts with trade info.

        Args:
            current_time: ISO format timestamp to compare against (defaults to now)
        """
        from datetime import datetime
        if current_time is None:
            current_time = datetime.now().isoformat()

        cursor = self.conn.execute("""
            SELECT id, token_id, whale_address, is_maker, maker_amount, taker_amount,
                   token_side, timeframe, expected_resolution, created_at
            FROM whale_pending_trades
            WHERE expected_resolution <= ?
            ORDER BY expected_resolution ASC
            LIMIT 100
        """, (current_time,))
        trades = []
        for row in cursor:
            trades.append({
                'id': row[0],
                'token_id': row[1],
                'whale_address': row[2],
                'is_maker': bool(row[3]),
                'maker_amount': row[4],
                'taker_amount': row[5],
                'token_side': row[6],
                'timeframe': row[7],
                'expected_resolution': row[8],
                'created_at': row[9]
            })
        return trades

    def get_pending_trades_by_token(self, token_id: str) -> list:
        """Get all pending trades for a specific token."""
        cursor = self.conn.execute("""
            SELECT id, token_id, whale_address, is_maker, maker_amount, taker_amount,
                   token_side, timeframe, expected_resolution, created_at
            FROM whale_pending_trades
            WHERE token_id = ?
        """, (token_id,))
        trades = []
        for row in cursor:
            trades.append({
                'id': row[0],
                'token_id': row[1],
                'whale_address': row[2],
                'is_maker': bool(row[3]),
                'maker_amount': row[4],
                'taker_amount': row[5],
                'token_side': row[6],
                'timeframe': row[7],
                'expected_resolution': row[8],
                'created_at': row[9]
            })
        return trades

    def delete_pending_trade(self, trade_id: int):
        """Delete a pending trade after it's been resolved."""
        with self._lock:
            self.conn.execute("DELETE FROM whale_pending_trades WHERE id = ?", (trade_id,))
            self.conn.commit()

    def delete_pending_trades_by_token(self, token_id: str):
        """Delete all pending trades for a token after resolution."""
        with self._lock:
            self.conn.execute("DELETE FROM whale_pending_trades WHERE token_id = ?", (token_id,))
            self.conn.commit()

    def get_pending_trades_count(self) -> int:
        """Get count of pending trades waiting for resolution."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM whale_pending_trades")
        row = cursor.fetchone()
        return row[0] if row else 0

    def get_pending_trades_summary(self, current_time: str = None) -> dict:
        """Get summary of pending trades for logging.

        Args:
            current_time: ISO format timestamp to compare against (defaults to now)
        """
        from datetime import datetime
        if current_time is None:
            current_time = datetime.now().isoformat()

        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(DISTINCT token_id) as unique_tokens,
                COUNT(DISTINCT whale_address) as unique_whales,
                SUM(CASE WHEN expected_resolution <= ? THEN 1 ELSE 0 END) as ready_to_resolve
            FROM whale_pending_trades
        """, (current_time,))
        row = cursor.fetchone()
        return {
            'total': row[0] or 0,
            'unique_tokens': row[1] or 0,
            'unique_whales': row[2] or 0,
            'ready_to_resolve': row[3] or 0
        }

    # =========================================================================
    # DRY RUN POSITIONS (Paper Trading Persistence)
    # =========================================================================

    def save_dry_run_position(self, position: dict):
        """Save a dry run position to the database."""
        import json
        with self._lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO dry_run_positions (
                    id, token_id, whale_address, side, position_size, confidence,
                    market_timeframe, market_question, entry_price, opened_at,
                    expected_resolution, status, resolved_at, market_outcome,
                    is_win, pnl, extra_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.get('id'),
                position.get('token_id'),
                position.get('whale_address'),
                position.get('side'),
                position.get('position_size'),
                position.get('confidence'),
                position.get('market_timeframe'),
                position.get('market_question'),
                position.get('entry_price'),
                position.get('opened_at'),
                position.get('expected_resolution'),
                position.get('status', 'PENDING'),
                position.get('resolved_at'),
                position.get('market_outcome'),
                1 if position.get('is_win') else 0 if position.get('is_win') is False else None,
                position.get('pnl'),
                json.dumps(position.get('extra_data', {})) if position.get('extra_data') else None
            ))
            self.conn.commit()

    def get_pending_dry_run_positions(self) -> list:
        """Get all pending (unresolved) dry run positions."""
        import json
        cursor = self.conn.execute("""
            SELECT id, token_id, whale_address, side, position_size, confidence,
                   market_timeframe, market_question, entry_price, opened_at,
                   expected_resolution, status, extra_data
            FROM dry_run_positions
            WHERE status = 'PENDING'
            ORDER BY opened_at ASC
        """)
        positions = []
        for row in cursor:
            pos = {
                'id': row[0],
                'token_id': row[1],
                'whale_address': row[2],
                'side': row[3],
                'position_size': row[4],
                'confidence': row[5],
                'market_timeframe': row[6],
                'market_question': row[7],
                'entry_price': row[8],
                'opened_at': row[9],
                'expected_resolution': row[10],
                'status': row[11]
            }
            if row[12]:
                try:
                    pos['extra_data'] = json.loads(row[12])
                except:
                    pass
            positions.append(pos)
        return positions

    def resolve_dry_run_position(self, position_id: str, market_outcome: str, pnl: float, is_win: bool):
        """Mark a dry run position as resolved."""
        from datetime import datetime
        with self._lock:
            self.conn.execute("""
                UPDATE dry_run_positions SET
                    status = 'RESOLVED',
                    resolved_at = ?,
                    market_outcome = ?,
                    is_win = ?,
                    pnl = ?
                WHERE id = ?
            """, (
                datetime.now().isoformat(),
                market_outcome,
                1 if is_win else 0,
                pnl,
                position_id
            ))
            self.conn.commit()

    def get_dry_run_summary(self) -> dict:
        """Get summary statistics for dry run positions."""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'RESOLVED' THEN 1 ELSE 0 END) as resolved,
                SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN is_win = 0 AND status = 'RESOLVED' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN status = 'PENDING' THEN position_size ELSE 0 END) as pending_exposure,
                SUM(CASE WHEN status = 'RESOLVED' THEN pnl ELSE 0 END) as realized_pnl
            FROM dry_run_positions
        """)
        row = cursor.fetchone()
        return {
            'total': row[0] or 0,
            'pending': row[1] or 0,
            'resolved': row[2] or 0,
            'wins': row[3] or 0,
            'losses': row[4] or 0,
            'pending_exposure': row[5] or 0.0,
            'realized_pnl': row[6] or 0.0,
            'win_rate': (row[3] / row[2] * 100) if row[2] and row[2] > 0 else 0.0
        }

    def get_best_trade_pnl(self) -> float:
        """Get the maximum PnL from all resolved dry run positions (all-time best)."""
        cursor = self.conn.execute("""
            SELECT MAX(pnl) FROM dry_run_positions
            WHERE status = 'RESOLVED' AND pnl IS NOT NULL
        """)
        row = cursor.fetchone()
        return row[0] if row[0] is not None else 0.0

    def get_worst_trade_pnl(self) -> float:
        """Get the minimum PnL from all resolved dry run positions (all-time worst)."""
        cursor = self.conn.execute("""
            SELECT MIN(pnl) FROM dry_run_positions
            WHERE status = 'RESOLVED' AND pnl IS NOT NULL
        """)
        row = cursor.fetchone()
        return row[0] if row[0] is not None else 0.0

    def get_24h_committed_capital(self) -> dict:
        """
        Get the total capital committed in the last 24 hours for dry run mode.

        This is more meaningful than the static $100 starting capital since
        in dry run mode we're not bound by actual capital constraints.

        Returns:
            Dict with committed capital stats for last 24 hours
        """
        from datetime import datetime, timedelta

        # Calculate 24 hours ago
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()

        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as positions_24h,
                SUM(position_size) as total_committed_24h,
                SUM(CASE WHEN status = 'PENDING' THEN position_size ELSE 0 END) as pending_24h,
                SUM(CASE WHEN status = 'RESOLVED' THEN position_size ELSE 0 END) as resolved_24h,
                SUM(CASE WHEN status = 'RESOLVED' THEN pnl ELSE 0 END) as pnl_24h,
                SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins_24h,
                SUM(CASE WHEN is_win = 0 AND status = 'RESOLVED' THEN 1 ELSE 0 END) as losses_24h
            FROM dry_run_positions
            WHERE opened_at >= ?
        """, (cutoff,))
        row = cursor.fetchone()

        positions_24h = row[0] or 0
        total_committed = row[1] or 0.0
        resolved_24h = row[4] or 0  # This is actually pnl_24h, resolved count is row[3]
        wins_24h = row[5] or 0
        losses_24h = row[6] or 0
        resolved_count = wins_24h + losses_24h

        return {
            'positions_24h': positions_24h,
            'total_committed_24h': total_committed,
            'pending_24h': row[2] or 0.0,
            'resolved_value_24h': row[3] or 0.0,
            'pnl_24h': row[4] or 0.0,
            'wins_24h': wins_24h,
            'losses_24h': losses_24h,
            'win_rate_24h': (wins_24h / resolved_count * 100) if resolved_count > 0 else 0.0
        }

    def get_resolved_dry_run_positions(self) -> list:
        """Get all resolved dry run positions for analytics."""
        import json
        cursor = self.conn.execute("""
            SELECT id, token_id, whale_address, side, position_size, confidence,
                   market_timeframe, market_question, entry_price, opened_at,
                   expected_resolution, status, resolved_at, market_outcome,
                   is_win, pnl, extra_data
            FROM dry_run_positions
            WHERE status = 'RESOLVED'
            ORDER BY resolved_at DESC
        """)
        positions = []
        for row in cursor:
            pos = {
                'id': row[0],
                'token_id': row[1],
                'whale_address': row[2],
                'side': row[3],
                'position_size': row[4],
                'confidence': row[5],
                'market_timeframe': row[6],
                'market_question': row[7],
                'entry_price': row[8],
                'opened_at': row[9],
                'expected_resolution': row[10],
                'status': row[11],
                'resolved_at': row[12],
                'market_outcome': row[13],
                'is_win': bool(row[14]) if row[14] is not None else None,
                'pnl': row[15]
            }
            if row[16]:
                try:
                    pos['extra_data'] = json.loads(row[16])
                except:
                    pass
            positions.append(pos)
        return positions

    # =========================================================================
    # CSV LOADING
    # =========================================================================

    def load_token_timeframes_csv(self, filepath: str) -> int:
        """
        Load token_timeframes.csv into the unified token_timeframes table.

        Expected CSV format:
            token_id,timeframe,resolved,outcome,token_side,question,whale_net

        whale_net format: "0xADDR1:+123.45|0xADDR2:-67.89|..."

        Returns:
            Number of tokens loaded
        """
        import csv

        tokens_loaded = 0
        batch = []

        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                token_id = row.get('token_id', row.get('token', ''))
                if not token_id:
                    continue

                timeframe = row.get('timeframe', row.get('tf', 'unknown'))
                question = row.get('question', '')
                resolved = row.get('resolved', '0') == '1'
                outcome = row.get('outcome', None)
                token_side = row.get('token_side', None)
                whale_net = row.get('whale_net', row.get('whale_net_pnl_by_address', ''))

                batch.append((
                    token_id, timeframe, question,
                    1 if resolved else 0, outcome, token_side, whale_net
                ))
                tokens_loaded += 1

                # Batch insert every 1000 records
                if len(batch) >= 1000:
                    with self._lock:
                        self.conn.executemany("""
                            INSERT OR REPLACE INTO token_timeframes
                            (token_id, timeframe, question, resolved, outcome, token_side, whale_net)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        self.conn.commit()
                    batch = []

        # Insert remaining records
        if batch:
            with self._lock:
                self.conn.executemany("""
                    INSERT OR REPLACE INTO token_timeframes
                    (token_id, timeframe, question, resolved, outcome, token_side, whale_net)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, batch)
                self.conn.commit()

        stats = self.get_token_timeframes_stats()
        print(f"   Loaded {tokens_loaded} tokens ({stats['resolved']} resolved, {stats['known']} with known timeframe)")
        return tokens_loaded

    def load_trader_tier_stats_csv(self, filepath: str) -> int:
        """
        Load trader_tier_stats.csv into whale_timeframe_stats table.

        Expected CSV format:
            address,timeframe,trade_count,wins,losses,wins_usd,losses_usd,volume,profit,win_rate,in_tier,resolved_trades

        Returns:
            Number of whales loaded
        """
        import csv

        whales_loaded = 0
        batch = []

        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                address = row.get('address', '')
                if not address:
                    continue

                # Only load whales marked as in_tier=1
                in_tier = row.get('in_tier', '0')
                if in_tier != '1':
                    continue

                timeframe = row.get('timeframe', 'unknown')
                trade_count = int(row.get('trade_count', 0) or 0)
                wins = int(row.get('wins', 0) or 0)
                losses = int(row.get('losses', 0) or 0)
                volume = float(row.get('volume', 0) or 0)
                profit = float(row.get('profit', 0) or 0)
                win_rate = float(row.get('win_rate', 0) or 0)

                batch.append((
                    address.lower(), timeframe, trade_count, wins, losses,
                    volume, profit, win_rate
                ))
                whales_loaded += 1

                # Batch insert every 500 records
                if len(batch) >= 500:
                    with self._lock:
                        self.conn.executemany("""
                            INSERT OR REPLACE INTO whale_timeframe_stats
                            (address, timeframe, trade_count, wins, losses, volume, profit, win_rate, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """, batch)
                        self.conn.commit()
                    batch = []

        # Insert remaining records
        if batch:
            with self._lock:
                self.conn.executemany("""
                    INSERT OR REPLACE INTO whale_timeframe_stats
                    (address, timeframe, trade_count, wins, losses, volume, profit, win_rate, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, batch)
                self.conn.commit()

        print(f"   Loaded {whales_loaded} tier whales from trader_tier_stats.csv")
        return whales_loaded

    def load_whale_quality_csv(self, filepath: str) -> int:
        """
        Load whale_quality.csv into whale_timeframe_stats table.

        Uses best_timeframe as the whale's specialty tier.

        Expected CSV format:
            address,total_net_pnl_usd,num_tokens,win_tokens,loss_tokens,win_rate,best_timeframe,tf_win_rate

        Returns:
            Number of whales loaded
        """
        import csv

        whales_loaded = 0
        batch = []

        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                address = row.get('address', '')
                if not address:
                    continue

                best_timeframe = row.get('best_timeframe', '')
                # Skip if no valid timeframe
                if not best_timeframe or best_timeframe == '-':
                    continue

                # Parse total_net_pnl_usd (handles comma formatting like "+9,929,288.16")
                pnl_str = row.get('total_net_pnl_usd', '0')
                pnl_str = pnl_str.replace(',', '').replace('+', '')
                try:
                    total_pnl = float(pnl_str)
                except ValueError:
                    total_pnl = 0

                # Only load profitable whales
                if total_pnl <= 0:
                    continue

                num_tokens = int(row.get('num_tokens', 0) or 0)
                win_tokens = int(row.get('win_tokens', 0) or 0)
                loss_tokens = int(row.get('loss_tokens', 0) or 0)
                win_rate = float(row.get('win_rate', 0) or 0)
                tf_win_rate = float(row.get('tf_win_rate', 0) or 0) if row.get('tf_win_rate', '-') != '-' else win_rate

                batch.append((
                    address.lower(), best_timeframe, num_tokens, win_tokens, loss_tokens,
                    0, total_pnl, tf_win_rate  # volume=0 (not in CSV), profit=total_pnl
                ))
                whales_loaded += 1

                # Batch insert every 500 records
                if len(batch) >= 500:
                    with self._lock:
                        self.conn.executemany("""
                            INSERT OR REPLACE INTO whale_timeframe_stats
                            (address, timeframe, trade_count, wins, losses, volume, profit, win_rate, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """, batch)
                        self.conn.commit()
                    batch = []

        # Insert remaining records
        if batch:
            with self._lock:
                self.conn.executemany("""
                    INSERT OR REPLACE INTO whale_timeframe_stats
                    (address, timeframe, trade_count, wins, losses, volume, profit, win_rate, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, batch)
                self.conn.commit()

        print(f"   Loaded {whales_loaded} quality whales from whale_quality.csv")
        return whales_loaded

    # =========================================================================
    # DATABASE STATS
    # =========================================================================

    def get_database_stats(self) -> Dict:
        """Get summary statistics about the database"""
        # Whale timeframe stats
        cursor = self.conn.execute("""
            SELECT COUNT(DISTINCT address) as whale_count
            FROM whale_timeframe_stats
        """)
        whale_count = cursor.fetchone()[0] or 0

        # Pending trades
        pending = self.get_pending_trades_summary()

        # Incremental stats
        incremental = self.get_incremental_stats_summary()

        # Token timeframes stats
        token_stats = self.get_token_timeframes_stats()

        return {
            'whale_count': whale_count,
            'pending_trades': pending['total'],
            'pending_tokens': pending['unique_tokens'],
            'incremental_addresses': incremental['unique_addresses'],
            'incremental_trades': incremental['total_trades'],
            'market_metadata': token_stats['total']
        }

    def export_to_csv(self, filepath: str = "whale_specialists.csv"):
        """Export whale timeframe stats to CSV"""
        import csv

        cursor = self.conn.execute("""
            SELECT address, timeframe, trade_count, wins, losses, volume, profit, win_rate
            FROM whale_timeframe_stats
            ORDER BY profit DESC
        """)
        rows = cursor.fetchall()

        if not rows:
            print("No whale data to export")
            return

        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['address', 'timeframe', 'trade_count', 'wins', 'losses', 'volume', 'profit', 'win_rate'])
            for row in rows:
                writer.writerow(row)

        print(f"Exported {len(rows)} whale records to {filepath}")

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


# Standalone test
if __name__ == "__main__":
    db = TradeDatabase("test_trades.db")

    # Test pending trades
    db.add_pending_whale_trade(
        token_id="test_token_123",
        whale_address="0xAAA",
        is_maker=False,
        maker_amount=1000000,
        taker_amount=500000,
        token_side="YES",
        timeframe="15min",
        expected_resolution="2024-01-01T00:00:00"
    )

    print(f"Database stats: {db.get_database_stats()}")
    print(f"Pending trades: {db.get_pending_trades_summary()}")

    db.close()
