"""
Trade Database Module
Persistent SQLite storage for blockchain trades with rolling window support.
Eliminates redundant deep scans by storing and querying historical data.
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict


def get_db_path() -> str:
    """Get database path from environment or use default"""
    return os.environ.get('DB_PATH', 'trades.db')


class TradeDatabase:
    """
    SQLite-based trade storage with:
    - Persistent storage across restarts
    - Rolling window (keeps last N blocks)
    - Fast querying for whale analysis
    - Incremental updates (only new blocks)
    """

    def __init__(self, db_path: str = "trades.db", max_blocks: int = 50000):
        self.db_path = db_path
        self.max_blocks = max_blocks
        self.conn = None
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with optimized schema"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrent access
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        # Create trades table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_number INTEGER NOT NULL,
                tx_hash TEXT,
                maker TEXT NOT NULL,
                taker TEXT NOT NULL,
                maker_amount INTEGER NOT NULL,
                taker_amount INTEGER NOT NULL,
                fee INTEGER DEFAULT 0,
                asset_id TEXT,
                timestamp INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for fast queries
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_block ON trades(block_number)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_maker ON trades(maker)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_taker ON trades(taker)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_block_maker ON trades(block_number, maker)")

        # Create metadata table for tracking scan state
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Create whale stats cache table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS whale_stats (
                address TEXT PRIMARY KEY,
                trade_count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_volume REAL DEFAULT 0,
                estimated_profit REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                first_block INTEGER,
                last_block INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()
        print(f"Trade database initialized: {self.db_path}")

    def get_last_scanned_block(self) -> Optional[int]:
        """Get the last block number that was scanned"""
        cursor = self.conn.execute(
            "SELECT value FROM scan_metadata WHERE key = 'last_scanned_block'"
        )
        row = cursor.fetchone()
        return int(row['value']) if row else None

    def set_last_scanned_block(self, block: int):
        """Update the last scanned block"""
        self.conn.execute("""
            INSERT OR REPLACE INTO scan_metadata (key, value)
            VALUES ('last_scanned_block', ?)
        """, (str(block),))
        self.conn.commit()

    def get_oldest_block(self) -> Optional[int]:
        """Get the oldest block in the database"""
        cursor = self.conn.execute("SELECT MIN(block_number) as min_block FROM trades")
        row = cursor.fetchone()
        return row['min_block'] if row and row['min_block'] else None

    def get_trade_count(self) -> int:
        """Get total number of trades in database"""
        cursor = self.conn.execute("SELECT COUNT(*) as count FROM trades")
        return cursor.fetchone()['count']

    def add_trades(self, trades: List[Dict]):
        """
        Bulk insert trades into database

        Args:
            trades: List of trade dicts with keys:
                - block_number, tx_hash, maker, taker
                - maker_amount, taker_amount, fee, asset_id
        """
        if not trades:
            return

        self.conn.executemany("""
            INSERT INTO trades (
                block_number, tx_hash, maker, taker,
                maker_amount, taker_amount, fee, asset_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                t['block_number'],
                t.get('tx_hash', ''),
                t['maker'],
                t['taker'],
                t['maker_amount'],
                t['taker_amount'],
                t.get('fee', 0),
                t.get('asset_id', '')
            )
            for t in trades
        ])
        self.conn.commit()

    def add_trades_from_events(self, events: List):
        """
        Add trades directly from web3 event objects

        Args:
            events: List of web3 event log objects from OrderFilled
        """
        trades = []
        for event in events:
            try:
                trades.append({
                    'block_number': event['blockNumber'],
                    'tx_hash': event.get('transactionHash', b'').hex() if isinstance(event.get('transactionHash'), bytes) else str(event.get('transactionHash', '')),
                    'maker': event['args']['maker'],
                    'taker': event['args']['taker'],
                    'maker_amount': event['args']['makerAmountFilled'],
                    'taker_amount': event['args']['takerAmountFilled'],
                    'fee': event['args'].get('fee', 0),
                    'asset_id': str(event['args'].get('makerAssetId', ''))
                })
            except Exception as e:
                print(f"Error parsing event: {e}")
                continue

        if trades:
            self.add_trades(trades)

        return len(trades)

    def prune_old_blocks(self, keep_blocks: int = None):
        """
        Remove trades older than the rolling window

        Args:
            keep_blocks: Number of recent blocks to keep (default: self.max_blocks)
        """
        keep_blocks = keep_blocks or self.max_blocks

        cursor = self.conn.execute("SELECT MAX(block_number) as max_block FROM trades")
        row = cursor.fetchone()
        if not row or not row['max_block']:
            return 0

        max_block = row['max_block']
        cutoff_block = max_block - keep_blocks

        cursor = self.conn.execute(
            "DELETE FROM trades WHERE block_number < ?",
            (cutoff_block,)
        )
        deleted = cursor.rowcount
        self.conn.commit()

        if deleted > 0:
            # Vacuum to reclaim space
            self.conn.execute("VACUUM")
            print(f"Pruned {deleted:,} old trades (blocks < {cutoff_block:,})")

        return deleted

    def get_all_trades(self, min_block: int = None, max_block: int = None) -> List[Dict]:
        """
        Get all trades, optionally filtered by block range

        Returns list of dicts for analysis
        """
        query = "SELECT * FROM trades WHERE 1=1"
        params = []

        if min_block:
            query += " AND block_number >= ?"
            params.append(min_block)
        if max_block:
            query += " AND block_number <= ?"
            params.append(max_block)

        query += " ORDER BY block_number ASC"

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_trader_stats(self, address: str) -> Dict:
        """Get cached stats for a specific trader"""
        cursor = self.conn.execute(
            "SELECT * FROM whale_stats WHERE address = ?",
            (address,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def analyze_and_cache_traders(self) -> List[Dict]:
        """
        Analyze all traders from stored trades and cache results

        This replaces the deep scan - runs against stored data, not blockchain
        Returns list of whale stats sorted by estimated profit
        """
        print("Analyzing traders from database...")

        # Get all trades
        cursor = self.conn.execute("""
            SELECT maker, taker, maker_amount, taker_amount, block_number
            FROM trades
        """)

        # Build trader stats in memory
        trader_stats = defaultdict(lambda: {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_volume': 0,
            'first_block': None,
            'last_block': None
        })

        trade_count = 0
        for row in cursor:
            trade_count += 1

            maker = row[0]
            taker = row[1]
            maker_amount = row[2]
            taker_amount = row[3]
            block = row[4]

            # Update maker stats (SELL side)
            self._update_stats(trader_stats[maker], 'SELL', maker_amount, taker_amount, block)

            # Update taker stats (BUY side)
            self._update_stats(trader_stats[taker], 'BUY', taker_amount, maker_amount, block)

        print(f"Processed {trade_count:,} trades for {len(trader_stats):,} unique addresses")

        # Calculate final metrics and filter
        specialists = []
        for address, stats in trader_stats.items():
            if stats['trades'] < 10:
                continue

            total = stats['wins'] + stats['losses']
            win_rate = stats['wins'] / total if total > 0 else 0.5
            estimated_profit = stats['total_volume'] * (win_rate - 0.5) * 0.3

            specialists.append({
                'address': address,
                'trade_count': stats['trades'],
                'wins': stats['wins'],
                'losses': stats['losses'],
                'total_volume': stats['total_volume'],
                'estimated_profit': estimated_profit,
                'win_rate': win_rate,
                'first_block': stats['first_block'],
                'last_block': stats['last_block']
            })

        # Sort by profit
        specialists.sort(key=lambda x: x['estimated_profit'], reverse=True)

        # Cache to database
        self._cache_whale_stats(specialists)

        print(f"Found {len(specialists):,} traders with 10+ trades")
        return specialists

    def _update_stats(self, stats: Dict, trade_type: str, token_amount: int, usdc_amount: int, block: int):
        """Update stats for a single trade"""
        stats['trades'] += 1
        stats['total_volume'] += usdc_amount / 1e6  # Convert to USDC

        if stats['first_block'] is None or block < stats['first_block']:
            stats['first_block'] = block
        if stats['last_block'] is None or block > stats['last_block']:
            stats['last_block'] = block

        # Simple win estimation
        price = usdc_amount / token_amount if token_amount > 0 else 0.5
        if trade_type == 'BUY' and price < 0.45:
            stats['wins'] += 1
        elif trade_type == 'SELL' and price > 0.55:
            stats['wins'] += 1
        elif trade_type == 'BUY' and price > 0.75:
            stats['losses'] += 1
        elif trade_type == 'SELL' and price < 0.25:
            stats['losses'] += 1

    def _cache_whale_stats(self, specialists: List[Dict]):
        """Cache whale stats to database for fast lookup"""
        self.conn.execute("DELETE FROM whale_stats")

        self.conn.executemany("""
            INSERT INTO whale_stats (
                address, trade_count, wins, losses, total_volume,
                estimated_profit, win_rate, first_block, last_block
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                s['address'], s['trade_count'], s['wins'], s['losses'],
                s['total_volume'], s['estimated_profit'], s['win_rate'],
                s['first_block'], s['last_block']
            )
            for s in specialists[:1000]  # Cache top 1000
        ])
        self.conn.commit()

    def get_top_whales(self, limit: int = 25) -> List[Dict]:
        """Get top whales from cache (instant, no analysis needed)"""
        cursor = self.conn.execute("""
            SELECT * FROM whale_stats
            ORDER BY estimated_profit DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_database_stats(self) -> Dict:
        """Get summary statistics about the database"""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as trade_count,
                MIN(block_number) as oldest_block,
                MAX(block_number) as newest_block,
                COUNT(DISTINCT maker) + COUNT(DISTINCT taker) as unique_addresses
            FROM trades
        """)
        row = cursor.fetchone()

        return {
            'trade_count': row['trade_count'],
            'oldest_block': row['oldest_block'],
            'newest_block': row['newest_block'],
            'block_range': (row['newest_block'] - row['oldest_block']) if row['oldest_block'] and row['newest_block'] else 0,
            'unique_addresses': row['unique_addresses'],
            'last_scanned': self.get_last_scanned_block()
        }

    def export_to_csv(self, filepath: str = "whale_specialists.csv"):
        """Export whale stats to CSV"""
        import csv

        whales = self.get_top_whales(limit=1000)
        if not whales:
            print("No whale data to export")
            return

        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=whales[0].keys())
            writer.writeheader()
            writer.writerows(whales)

        print(f"Exported {len(whales)} whales to {filepath}")

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


# Standalone test
if __name__ == "__main__":
    db = TradeDatabase("test_trades.db", max_blocks=50000)

    # Add some test trades
    test_trades = [
        {
            'block_number': 100,
            'maker': '0xAAA',
            'taker': '0xBBB',
            'maker_amount': 1000000,
            'taker_amount': 500000
        },
        {
            'block_number': 101,
            'maker': '0xAAA',
            'taker': '0xCCC',
            'maker_amount': 2000000,
            'taker_amount': 900000
        }
    ]

    db.add_trades(test_trades)
    print(f"Database stats: {db.get_database_stats()}")

    db.close()
