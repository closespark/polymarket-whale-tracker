"""
Market Resolver - Monitors markets for resolution and updates positions

This module is responsible for:
1. Polling markets for resolution status
2. Detecting when a market has resolved
3. Determining the outcome (YES/NO won)
4. Triggering position resolution and P&L calculation
"""

import asyncio
import requests
from datetime import datetime
from typing import Dict, List, Optional

from position_manager import get_position_manager, PositionManager
from order_executor import get_order_executor, OrderExecutor
import config


class MarketResolver:
    """
    Monitors pending positions and resolves them when markets close

    Resolution detection methods:
    1. Poll Gamma API for market resolution status
    2. Check conditional token balance (if 0 after resolution)
    3. Check USDC balance change
    """

    def __init__(self):
        self.gamma_api = "https://gamma-api.polymarket.com"
        self.position_manager = get_position_manager()
        self.order_executor = get_order_executor()

        # Resolution check interval
        self.check_interval = 30  # seconds

        # Cache for market resolution status
        self.resolution_cache = {}  # condition_id -> {'outcome': str, 'checked_at': datetime}
        self.cache_ttl = 60  # seconds

        print(f"🔍 MarketResolver initialized")
        print(f"   Check interval: {self.check_interval}s")

    async def start_resolution_loop(self, system_callback=None):
        """
        Start the continuous resolution checking loop

        Args:
            system_callback: Optional callback to update system stats after resolution
        """
        print(f"\n🔄 Starting market resolution loop...")

        while True:
            try:
                await self.check_and_resolve_positions(system_callback)
                await asyncio.sleep(self.check_interval)

            except Exception as e:
                print(f"   ⚠️ Resolution loop error: {e}")
                await asyncio.sleep(60)

    async def check_and_resolve_positions(self, system_callback=None):
        """
        Check pending positions and resolve those past their resolution time
        """
        # Get positions that should be resolved
        positions_to_check = self.position_manager.get_positions_to_resolve()

        if not positions_to_check:
            return

        print(f"\n⏰ Checking {len(positions_to_check)} positions for resolution...")

        for position in positions_to_check:
            try:
                await self._resolve_single_position(position, system_callback)
            except Exception as e:
                print(f"   ⚠️ Error resolving {position['id']}: {e}")

    async def _resolve_single_position(self, position: Dict, system_callback=None):
        """
        Attempt to resolve a single position

        Tries multiple methods to detect resolution:
        1. Query Gamma API for market outcome
        2. Check token balance (if 0, market resolved)
        3. Compare USDC balance before/after
        """
        position_id = position['id']
        token_id = position['token_id']
        condition_id = position.get('condition_id')

        print(f"\n🔍 Checking resolution for {position_id[:20]}...")

        # Method 1: Check Gamma API for market resolution
        market_outcome = await self._check_market_resolution_api(token_id, condition_id)

        if market_outcome:
            print(f"   📊 Market resolved: {market_outcome}")
            resolved = self.position_manager.resolve_position(
                position_id,
                market_outcome
            )

            if resolved and system_callback:
                await system_callback(resolved)
            return

        # Method 2: Check token balance
        # If our token balance is 0 but we had tokens, market has resolved
        current_balance = self.order_executor.get_token_balance(token_id)

        if current_balance == 0 and position['quantity'] > 0:
            # Market resolved - determine if we won by checking USDC balance change
            # This is a fallback method

            # Get expected P&L based on whether we won
            # If USDC increased by ~quantity, we won
            # If USDC stayed same or decreased, we lost

            # For now, we can't determine outcome without API
            # Mark as needing manual check
            print(f"   ⚠️ Token balance is 0 but can't determine outcome")
            print(f"   Position may need manual resolution")
            return

        # Method 3: Check if market is still active
        market_info = await self._get_market_info(token_id)
        if market_info:
            active = market_info.get('active', True)
            closed = market_info.get('closed', False)

            if closed or not active:
                # Market closed but outcome not yet available
                # May need to wait for settlement
                print(f"   ⏳ Market closed, waiting for settlement...")
                return

        # Market not yet resolved
        print(f"   ⏳ Market not yet resolved")

    async def _check_market_resolution_api(
        self,
        token_id: str,
        condition_id: str = None
    ) -> Optional[str]:
        """
        Check Gamma API for market resolution

        Returns:
            'YES' or 'NO' if resolved, None if still active
        """
        try:
            # Check cache first
            cache_key = condition_id or token_id
            if cache_key in self.resolution_cache:
                cached = self.resolution_cache[cache_key]
                age = (datetime.now() - cached['checked_at']).total_seconds()
                if age < self.cache_ttl:
                    return cached['outcome']

            # Query API
            url = f"{self.gamma_api}/markets?clob_token_ids={token_id}"
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                return None

            markets = response.json()
            if not markets or len(markets) == 0:
                return None

            market = markets[0]

            # Check resolution status
            # Different API versions may use different field names
            resolved = (
                market.get('resolved', False) or
                market.get('closed', False) or
                market.get('resolution_source') is not None
            )

            if not resolved:
                return None

            # Get outcome
            # The API may return outcome in different formats
            outcome = (
                market.get('outcome') or
                market.get('resolution') or
                market.get('winning_outcome')
            )

            if outcome:
                # Normalize outcome
                if outcome.lower() in ['yes', 'true', '1']:
                    outcome = 'YES'
                elif outcome.lower() in ['no', 'false', '0']:
                    outcome = 'NO'

                # Cache result
                self.resolution_cache[cache_key] = {
                    'outcome': outcome,
                    'checked_at': datetime.now()
                }

                return outcome

            return None

        except Exception as e:
            print(f"   ⚠️ API check failed: {e}")
            return None

    async def _get_market_info(self, token_id: str) -> Optional[Dict]:
        """Get market info from Gamma API"""
        try:
            url = f"{self.gamma_api}/markets?clob_token_ids={token_id}"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                markets = response.json()
                if markets and len(markets) > 0:
                    return markets[0]

            return None

        except Exception as e:
            return None

    def get_pending_summary(self) -> Dict:
        """Get summary of pending positions"""
        return self.position_manager.get_position_summary()


# Singleton instance
_resolver = None


def get_market_resolver() -> MarketResolver:
    """Get or create the MarketResolver singleton"""
    global _resolver
    if _resolver is None:
        _resolver = MarketResolver()
    return _resolver
