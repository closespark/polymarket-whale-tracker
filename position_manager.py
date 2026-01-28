"""
Position Manager - Tracks open and resolved positions

This module is responsible for:
1. Recording new positions after order fills
2. Tracking pending positions awaiting resolution
3. Updating positions when markets resolve
4. Calculating P&L
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os

import config


class PositionManager:
    """
    Manages trading positions with SQLite persistence

    Stores:
    - Position details (token, quantity, cost)
    - Market info (condition_id, end_date)
    - Resolution status and P&L
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            # Use same path logic as trade_database
            db_path = os.environ.get('DB_PATH', 'positions.db')
            if db_path.endswith('trades.db'):
                db_path = db_path.replace('trades.db', 'positions.db')

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_tables()

        print(f"📊 PositionManager initialized")
        print(f"   Database: {db_path}")

    def _create_tables(self):
        """Create positions table if not exists"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                order_id TEXT,

                -- Market info
                token_id TEXT NOT NULL,
                condition_id TEXT,
                market_slug TEXT,
                market_question TEXT,
                expected_resolution TEXT,

                -- Position details
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                total_cost REAL NOT NULL,

                -- Whale info
                whale_address TEXT,
                whale_trade_block INTEGER,
                confidence REAL,
                tier TEXT,

                -- Timestamps
                opened_at TEXT NOT NULL,
                resolved_at TEXT,

                -- Resolution
                status TEXT DEFAULT 'PENDING',
                market_outcome TEXT,
                is_win INTEGER,
                pnl REAL,

                -- Extra data as JSON
                extra_data TEXT
            )
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_status
            ON positions(status)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_token
            ON positions(token_id)
        """)

        self.conn.commit()

    def record_position(
        self,
        order_result: Dict,
        trade_data: Dict,
        market_info: Dict = None
    ) -> str:
        """
        Record a new position after order placement

        Args:
            order_result: Result from OrderExecutor.place_order()
            trade_data: Original trade data from whale detection
            market_info: Market metadata from Gamma API

        Returns:
            Position ID
        """
        position_id = f"pos_{datetime.now().strftime('%Y%m%d%H%M%S')}_{order_result.get('order_id', 'unknown')[:8]}"

        # Calculate expected resolution from market info or trade data
        if market_info and market_info.get('end_date_iso'):
            expected_resolution = market_info['end_date_iso']
        else:
            # Fall back to timeframe estimation
            timeframe = trade_data.get('market_timeframe', '15min')
            durations = {
                '15min': timedelta(minutes=15),
                'hourly': timedelta(hours=1),
                '4hour': timedelta(hours=4),
                'daily': timedelta(days=1)
            }
            expected_resolution = (
                datetime.now() + durations.get(timeframe, timedelta(minutes=15))
            ).isoformat()

        self.conn.execute("""
            INSERT INTO positions (
                id, order_id, token_id, condition_id, market_slug,
                market_question, expected_resolution, side, quantity,
                entry_price, total_cost, whale_address, whale_trade_block,
                confidence, tier, opened_at, status, extra_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position_id,
            order_result.get('order_id'),
            order_result.get('token_id'),
            market_info.get('conditionId') if market_info else None,
            market_info.get('slug') if market_info else None,
            market_info.get('question') if market_info else trade_data.get('market_question'),
            expected_resolution,
            order_result.get('side'),
            order_result.get('quantity'),
            order_result.get('price'),
            order_result.get('total_cost'),
            trade_data.get('whale_address'),
            trade_data.get('block_number'),
            trade_data.get('confidence'),
            trade_data.get('tier'),
            datetime.now().isoformat(),
            'PENDING',
            json.dumps({
                'fill_status': order_result.get('fill_status'),
                'whale_win_rate': trade_data.get('whale_win_rate'),
                'market_timeframe': trade_data.get('market_timeframe')
            })
        ))

        self.conn.commit()

        print(f"\n📋 Position recorded: {position_id}")
        print(f"   Token: {order_result.get('token_id', '')[:16]}...")
        print(f"   Side: {order_result.get('side')}")
        print(f"   Quantity: {order_result.get('quantity', 0):.2f}")
        print(f"   Cost: ${order_result.get('total_cost', 0):.2f}")
        print(f"   Expected resolution: {expected_resolution}")

        return position_id

    def get_pending_positions(self) -> List[Dict]:
        """Get all pending (unresolved) positions"""
        cursor = self.conn.execute("""
            SELECT * FROM positions WHERE status = 'PENDING'
            ORDER BY expected_resolution ASC
        """)

        columns = [desc[0] for desc in cursor.description]
        positions = []

        for row in cursor:
            pos = dict(zip(columns, row))
            if pos.get('extra_data'):
                pos['extra_data'] = json.loads(pos['extra_data'])
            positions.append(pos)

        return positions

    def get_positions_to_resolve(self) -> List[Dict]:
        """Get positions past their expected resolution time"""
        now = datetime.now().isoformat()

        cursor = self.conn.execute("""
            SELECT * FROM positions
            WHERE status = 'PENDING'
              AND expected_resolution <= ?
            ORDER BY expected_resolution ASC
        """, (now,))

        columns = [desc[0] for desc in cursor.description]
        positions = []

        for row in cursor:
            pos = dict(zip(columns, row))
            if pos.get('extra_data'):
                pos['extra_data'] = json.loads(pos['extra_data'])
            positions.append(pos)

        return positions

    def resolve_position(
        self,
        position_id: str,
        market_outcome: str,
        actual_pnl: float = None
    ) -> Dict:
        """
        Mark a position as resolved

        Args:
            position_id: The position to resolve
            market_outcome: 'YES' or 'NO' - what the market resolved to
            actual_pnl: Actual P&L if known (from balance change)

        Returns:
            Updated position dict
        """
        # Get position
        cursor = self.conn.execute(
            "SELECT * FROM positions WHERE id = ?",
            (position_id,)
        )
        row = cursor.fetchone()

        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        position = dict(zip(columns, row))

        # Determine win/loss
        our_side = position['side']
        is_win = (our_side == market_outcome)

        # Calculate P&L
        if actual_pnl is not None:
            pnl = actual_pnl
        else:
            # Calculate theoretical P&L
            quantity = position['quantity']
            total_cost = position['total_cost']

            if is_win:
                # Tokens redeem at $1 each
                pnl = (quantity * 1.0) - total_cost
            else:
                # Tokens worth $0
                pnl = -total_cost

        # Update position
        self.conn.execute("""
            UPDATE positions SET
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

        # Return updated position
        position['status'] = 'RESOLVED'
        position['resolved_at'] = datetime.now().isoformat()
        position['market_outcome'] = market_outcome
        position['is_win'] = is_win
        position['pnl'] = pnl

        print(f"\n{'='*60}")
        print(f"📊 POSITION RESOLVED")
        print(f"{'='*60}")
        print(f"   Position: {position_id}")
        print(f"   Our side: {our_side}")
        print(f"   Market outcome: {market_outcome}")
        print(f"   Result: {'✅ WIN' if is_win else '❌ LOSS'}")
        print(f"   P&L: ${pnl:+.2f}")
        print(f"{'='*60}\n")

        return position

    def get_position_summary(self) -> Dict:
        """Get summary statistics of all positions"""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'RESOLVED' THEN 1 ELSE 0 END) as resolved,
                SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN is_win = 0 AND status = 'RESOLVED' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN status = 'PENDING' THEN total_cost ELSE 0 END) as pending_exposure,
                SUM(CASE WHEN status = 'RESOLVED' THEN pnl ELSE 0 END) as realized_pnl
            FROM positions
        """)

        row = cursor.fetchone()

        return {
            'total_positions': row[0] or 0,
            'pending': row[1] or 0,
            'resolved': row[2] or 0,
            'wins': row[3] or 0,
            'losses': row[4] or 0,
            'pending_exposure': row[5] or 0.0,
            'realized_pnl': row[6] or 0.0,
            'win_rate': (row[3] / row[2] * 100) if row[2] and row[2] > 0 else 0.0
        }

    def get_position(self, position_id: str) -> Optional[Dict]:
        """Get a specific position by ID"""
        cursor = self.conn.execute(
            "SELECT * FROM positions WHERE id = ?",
            (position_id,)
        )
        row = cursor.fetchone()

        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        position = dict(zip(columns, row))

        if position.get('extra_data'):
            position['extra_data'] = json.loads(position['extra_data'])

        return position

    def get_positions_by_token(self, token_id: str) -> List[Dict]:
        """Get all positions for a specific token"""
        cursor = self.conn.execute(
            "SELECT * FROM positions WHERE token_id = ? ORDER BY opened_at DESC",
            (token_id,)
        )

        columns = [desc[0] for desc in cursor.description]
        positions = []

        for row in cursor:
            pos = dict(zip(columns, row))
            if pos.get('extra_data'):
                pos['extra_data'] = json.loads(pos['extra_data'])
            positions.append(pos)

        return positions

    def close(self):
        """Close database connection"""
        self.conn.close()


# Singleton instance
_manager = None


def get_position_manager() -> PositionManager:
    """Get or create the PositionManager singleton"""
    global _manager
    if _manager is None:
        _manager = PositionManager()
    return _manager
