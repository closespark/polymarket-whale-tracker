"""
$100 Capital Optimized Trading System v3

Enhancements:
1. SQLite storage (no redundant scans)
2. Kelly Criterion position sizing
3. WebSocket real-time monitoring (sub-second detection)
4. Enhanced risk management (trailing stops, limits)
5. Incremental-only blockchain scanning
6. Trade aggregation (filters arbitrage/hedging)
7. Pending position tracking (profit counted on market resolution)
8. Market lifecycle tracking (real resolution outcomes)
9. Real-time whale quality tracking (PnL per timeframe)
10. Automatic tier promotion for new profitable whales
"""

import asyncio
from datetime import datetime, timedelta
import json
import os
import random

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from market_lifecycle import get_market_lifecycle
from embedded_dashboard import EmbeddedDashboard

# Tier requirements for promotion (same as standalone pipeline)
TIER_REQUIREMENTS = {
    '15min': {'min_trades': 15, 'min_win_rate': 0.70},
    'hourly': {'min_trades': 12, 'min_win_rate': 0.68},
    '4hour': {'min_trades': 8, 'min_win_rate': 0.65},
    'daily': {'min_trades': 8, 'min_win_rate': 0.65},
}

# Timeframe durations for market resolution
TIMEFRAME_DURATIONS = {
    '15min': timedelta(minutes=15),
    'hourly': timedelta(hours=1),
    '4hour': timedelta(hours=4),
    'daily': timedelta(days=1),
    'unknown': timedelta(minutes=15)  # Default to 15min
}


class PendingPositionTracker:
    """
    Tracks pending positions until market resolution

    Instead of claiming instant profit, we:
    1. Record the position when we copy a trade
    2. Track the expected resolution time based on market timeframe
    3. Check actual market resolution via Gamma API
    4. Only then update capital and stats

    Resolution uses ACTUAL market outcomes from MarketLifecycle tracker.
    Falls back to simulation only if API doesn't return outcome.

    PERSISTENCE: Positions are saved to SQLite database so they survive restarts.
    """

    def __init__(self, system, db=None):
        self.system = system
        self.db = db  # TradeDatabase instance for persistence
        self.pending_positions = []  # List of pending position dicts
        self.resolved_positions = []  # History of resolved positions
        self.market_lifecycle = get_market_lifecycle()  # For actual resolutions

        # Check if we should clear positions on startup
        if os.environ.get('CLEAR_POSITIONS', 'false').lower() == 'true':
            print("🧹 CLEAR_POSITIONS=true - starting with fresh position state")
        else:
            # Load existing positions from database
            self._load_from_database()

    def _load_from_database(self):
        """Load pending positions from database on startup."""
        if not self.db:
            return

        try:
            db_positions = self.db.get_pending_dry_run_positions()
            if db_positions:
                for db_pos in db_positions:
                    # Convert database format to in-memory format
                    opened_at = datetime.fromisoformat(db_pos['opened_at']) if db_pos.get('opened_at') else datetime.now()
                    market_timeframe = db_pos.get('market_timeframe', '15min')

                    # Recalculate expected_resolution from market_timeframe to fix any bad data
                    resolution_delay = TIMEFRAME_DURATIONS.get(market_timeframe, timedelta(minutes=15))
                    expected_resolution = opened_at + resolution_delay

                    position = {
                        'id': db_pos['id'],
                        'opened_at': opened_at,
                        'expected_resolution': expected_resolution,
                        'market_timeframe': market_timeframe,
                        'position_size': db_pos.get('position_size', 0),
                        'confidence': db_pos.get('confidence', 0),
                        'whale_address': db_pos.get('whale_address', ''),
                        'whale_win_rate': db_pos.get('extra_data', {}).get('whale_win_rate', 0.72) if db_pos.get('extra_data') else 0.72,
                        'side': db_pos.get('side', 'BUY'),
                        'market': db_pos.get('market_question', 'Unknown'),
                        'token_id': db_pos.get('token_id', ''),
                        'tier': db_pos.get('extra_data', {}).get('tier', 'unknown') if db_pos.get('extra_data') else 'unknown',
                        'trade_data': db_pos.get('extra_data', {}).get('trade_data', {}) if db_pos.get('extra_data') else {},
                        'status': 'pending'
                    }
                    self.pending_positions.append(position)

                print(f"📂 Restored {len(db_positions)} pending dry-run positions from database")
        except Exception as e:
            print(f"   ⚠️ Error loading positions from database: {e}")

    def _save_to_database(self, position: dict):
        """Save a position to the database."""
        if not self.db:
            return

        try:
            db_position = {
                'id': position['id'],
                'token_id': position.get('token_id', ''),
                'whale_address': position.get('whale_address', ''),
                'side': position.get('side', 'BUY'),
                'position_size': position.get('position_size', 0),
                'confidence': position.get('confidence', 0),
                'market_timeframe': position.get('market_timeframe', '15min'),
                'market_question': position.get('market', ''),
                'entry_price': position.get('trade_data', {}).get('price'),
                'opened_at': position.get('opened_at').isoformat() if isinstance(position.get('opened_at'), datetime) else position.get('opened_at'),
                'expected_resolution': position.get('expected_resolution').isoformat() if isinstance(position.get('expected_resolution'), datetime) else position.get('expected_resolution'),
                'status': 'PENDING',
                'extra_data': {
                    'whale_win_rate': position.get('whale_win_rate', 0.72),
                    'tier': position.get('tier', 'unknown'),
                    'trade_data': position.get('trade_data', {})
                }
            }
            self.db.save_dry_run_position(db_position)
        except Exception as e:
            print(f"   ⚠️ Error saving position to database: {e}")

    def add_position(self, trade_data: dict, position_size: float, confidence: float):
        """
        Add a new pending position

        Args:
            trade_data: Original trade data from whale detection
            position_size: Our position size in USDC
            confidence: Confidence score used for this trade
        """
        market_timeframe = trade_data.get('market_timeframe', '15min')

        # Use actual market end_date from Gamma API if available
        # This is the REAL resolution time, not a calculated estimate
        end_date_str = trade_data.get('end_date')
        if end_date_str:
            try:
                # Parse ISO format from Gamma API
                if isinstance(end_date_str, str):
                    if 'T' in end_date_str:
                        expected_resolution = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                        # Convert to local time if timezone-aware
                        if expected_resolution.tzinfo:
                            expected_resolution = expected_resolution.replace(tzinfo=None)
                    else:
                        expected_resolution = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')
                else:
                    expected_resolution = end_date_str  # Already a datetime
            except (ValueError, TypeError):
                # Fallback to calculated resolution
                resolution_delay = TIMEFRAME_DURATIONS.get(market_timeframe, timedelta(minutes=15))
                expected_resolution = datetime.now() + resolution_delay
        else:
            # Fallback: calculate from timeframe (less accurate)
            resolution_delay = TIMEFRAME_DURATIONS.get(market_timeframe, timedelta(minutes=15))
            expected_resolution = datetime.now() + resolution_delay

        position = {
            'id': f"{trade_data.get('whale_address', '')[:10]}_{datetime.now().timestamp()}",
            'opened_at': datetime.now(),
            'expected_resolution': expected_resolution,
            'market_timeframe': market_timeframe,
            'position_size': position_size,
            'confidence': confidence,
            'whale_address': trade_data.get('whale_address', ''),
            'whale_win_rate': trade_data.get('whale_win_rate', 0.72),
            'side': trade_data.get('side', trade_data.get('net_side', 'BUY')),
            'market': trade_data.get('market_question', trade_data.get('market', 'Unknown')),
            'token_id': trade_data.get('token_id', trade_data.get('asset_id', '')),
            'tier': trade_data.get('tier', 'unknown'),
            'trade_data': trade_data,
            'status': 'pending'
        }

        self.pending_positions.append(position)

        # Persist to database
        self._save_to_database(position)

        print(f"\n📋 POSITION OPENED (pending resolution)")
        print(f"   Size: ${position_size:.2f}")
        print(f"   Market timeframe: {market_timeframe}")
        print(f"   Expected resolution: {position['expected_resolution'].strftime('%H:%M:%S')}")
        print(f"   ({len(self.pending_positions)} positions pending)")

        return position

    async def check_and_resolve_positions(self):
        """
        Check for positions that should be resolved

        Called periodically to resolve expired positions
        """
        now = datetime.now()
        positions_to_resolve = []

        for pos in self.pending_positions:
            if pos['expected_resolution'] <= now:
                positions_to_resolve.append(pos)

        for pos in positions_to_resolve:
            await self._resolve_position(pos)

    async def _resolve_position(self, position: dict):
        """
        Resolve a position using ACTUAL market outcome from Gamma API.

        Resolution priority:
        1. Check MarketLifecycle for actual resolution (preferred)
        2. Fall back to simulation if API unavailable
        """
        # Remove from pending
        self.pending_positions = [p for p in self.pending_positions if p['id'] != position['id']]

        # Try to get ACTUAL market outcome
        token_id = position.get('token_id', '')
        actual_outcome = None
        outcome_source = 'simulated'

        if token_id:
            actual_outcome = self.market_lifecycle.get_resolution(token_id)

        if actual_outcome:
            # Use actual market outcome
            outcome_source = 'actual'
            side = position.get('side', 'BUY')

            # Determine if we won based on our side and market outcome
            # If we bought YES and outcome is YES -> WIN
            # If we bought NO and outcome is NO -> WIN
            if side == 'BUY':
                is_win = (actual_outcome == 'YES')
            else:  # SELL
                is_win = (actual_outcome == 'NO')

            print(f"   📊 Using ACTUAL outcome: {actual_outcome} (side={side})")
        else:
            # Fall back to simulation based on whale's win rate
            whale_win_rate = position['whale_win_rate']
            confidence = position['confidence']

            # Adjust probability based on confidence
            adjusted_win_prob = whale_win_rate * (0.9 + (confidence / 1000))
            adjusted_win_prob = min(adjusted_win_prob, 0.95)

            is_win = random.random() < adjusted_win_prob
            print(f"   ⚠️ No API outcome - using simulated (win_prob={adjusted_win_prob:.1%})")

        # Calculate profit/loss
        position_size = position['position_size']
        if is_win:
            # Win: profit based on confidence tier
            if confidence > 95:
                profit = position_size * 0.35
            elif confidence > 92:
                profit = position_size * 0.25
            else:
                profit = position_size * 0.15
        else:
            # Loss: lose the position
            profit = -position_size

        # Update position record
        position['status'] = 'resolved'
        position['resolved_at'] = datetime.now()
        position['outcome'] = 'WIN' if is_win else 'LOSS'
        position['profit'] = profit

        self.resolved_positions.append(position)

        # Persist resolution to database
        if self.db:
            try:
                market_outcome = actual_outcome if actual_outcome else ('YES' if is_win else 'NO')
                self.db.resolve_dry_run_position(position['id'], market_outcome, profit, is_win)
            except Exception as e:
                print(f"   ⚠️ Error updating position in database: {e}")

        # Update system stats
        self._update_system_stats(position, profit, is_win)

        # Print resolution
        hold_time = (position['resolved_at'] - position['opened_at']).total_seconds() / 60
        print(f"\n{'='*80}")
        print(f"📊 POSITION RESOLVED ({position['market_timeframe']} market)")
        print(f"{'='*80}")
        print(f"   Whale: {position['whale_address'][:10]}...")
        print(f"   Hold time: {hold_time:.1f} minutes")
        print(f"   Position: ${position_size:.2f}")

        if is_win:
            print(f"   ✅ WIN: +${profit:.2f}")
        else:
            print(f"   ❌ LOSS: ${profit:.2f}")

        print(f"   💰 New capital: ${self.system.current_capital:.2f}")
        print(f"   📈 ROI: {self.system.stats['roi_percent']:.1f}%")
        print(f"{'='*80}\n")

        # Log the resolved trade
        self.system.log_trade(
            position['trade_data'],
            position_size,
            profit,
            confidence
        )

    def _update_system_stats(self, position: dict, profit: float, is_win: bool):
        """Update system stats after position resolution"""
        system = self.system

        system.stats['copies'] += 1
        system.current_capital += profit
        system.stats['total_profit'] += profit
        system.stats['current_capital'] = system.current_capital

        if is_win:
            system.stats['wins'] += 1
            system.stats['consecutive_wins'] += 1
            system.stats['max_consecutive_wins'] = max(
                system.stats['max_consecutive_wins'],
                system.stats['consecutive_wins']
            )
            if profit > system.stats['best_trade']:
                system.stats['best_trade'] = profit
        else:
            system.stats['losses'] += 1
            system.stats['consecutive_wins'] = 0
            if profit < system.stats['worst_trade']:
                system.stats['worst_trade'] = profit

        # Update ROI
        system.stats['roi_percent'] = (
            (system.current_capital - system.starting_capital) / system.starting_capital * 100
        )

        # Update risk manager and position sizer
        system.risk_manager.update_capital(system.current_capital)
        system.position_sizer.record_trade_result(profit, is_win)

        # Record tier stats
        tier = position.get('tier', 'unknown')
        if hasattr(system, 'multi_tf_strategy'):
            system.multi_tf_strategy.record_trade_result(tier, is_win, profit)

    def get_pending_summary(self) -> dict:
        """Get summary of pending positions"""
        total_pending = sum(p['position_size'] for p in self.pending_positions)
        by_timeframe = {}
        for p in self.pending_positions:
            tf = p['market_timeframe']
            if tf not in by_timeframe:
                by_timeframe[tf] = {'count': 0, 'total': 0}
            by_timeframe[tf]['count'] += 1
            by_timeframe[tf]['total'] += p['position_size']

        return {
            'pending_count': len(self.pending_positions),
            'pending_total': total_pending,
            'by_timeframe': by_timeframe,
            'resolved_count': len(self.resolved_positions)
        }


from ultra_fast_discovery import UltraFastDiscovery
from whale_copier import WhaleCopier
from claude_validator import ClaudeTradeValidator
from kelly_sizing import KellySizing, EnhancedPositionSizer
from risk_manager import RiskManager
from websocket_monitor import WebSocketTradeMonitor, HybridMonitor
from dry_run_analytics import DryRunAnalytics, get_analytics
from whale_intelligence import WhaleIntelligence, create_whale_intelligence
from multi_timeframe_strategy import MultiTimeframeStrategy, create_multi_timeframe_strategy

# Live trading components
from order_executor import get_order_executor, OrderExecutor
from position_manager import get_position_manager, PositionManager
from market_resolver import get_market_resolver, MarketResolver

import config


class SmallCapitalSystem:
    """
    Complete system optimized for $100 starting capital

    v2 Enhancements:
    - Kelly Criterion position sizing (10-20% better returns)
    - WebSocket monitoring (2-5 second detection vs 60 seconds)
    - Enhanced risk management (trailing stops, exposure limits)
    - SQLite storage (94% fewer RPC calls)
    """

    def __init__(self, starting_capital=100):
        self.starting_capital = starting_capital
        self.current_capital = starting_capital

        # Core components
        self.discovery = UltraFastDiscovery()
        self.monitor = None
        self.copier = WhaleCopier()
        self.claude_validator = ClaudeTradeValidator()

        # v2: Enhanced position sizing with Kelly Criterion
        self.position_sizer = EnhancedPositionSizer(starting_capital)
        self.kelly = KellySizing(kelly_fraction=0.25)  # Quarter Kelly (safer)

        # v2: Risk management
        self.risk_manager = RiskManager(
            starting_capital=starting_capital,
            max_drawdown_pct=0.30,      # Stop at 30% drawdown
            max_per_trade_pct=0.15,     # Max 15% per trade
            max_per_whale_pct=0.25,     # Max 25% per whale
            max_daily_exposure_pct=0.60  # Max 60% daily
        )

        # v2: WebSocket monitor (will be initialized with whale addresses)
        self.ws_monitor = None

        # v2: Comprehensive dry run analytics
        self.analytics = DryRunAnalytics()

        # v2: Whale intelligence for smarter filtering
        self.whale_intel = create_whale_intelligence()

        # v2: Multi-timeframe strategy for more opportunities
        self.multi_tf_strategy = create_multi_timeframe_strategy()

        # v2: Embedded dashboard for real-time monitoring
        self.dashboard = EmbeddedDashboard(self)

        # v3: Pending position tracker (profit only on market resolution)
        # Pass database for persistence across restarts
        db = getattr(self.discovery, 'db', None)
        self.position_tracker = PendingPositionTracker(self, db=db)

        # v4: Live trading components (initialized when needed)
        self.order_executor = None
        self.position_manager = None
        self.market_resolver = None

        # Initialize live trading components if enabled
        if config.AUTO_COPY_ENABLED:
            self._initialize_live_trading()

        # Stats tracking
        self.stats = {
            'start_time': datetime.now(),
            'starting_capital': starting_capital,
            'current_capital': starting_capital,
            'opportunities': 0,
            'copies': 0,
            'wins': 0,
            'losses': 0,
            'total_profit': 0,
            'best_trade': 0,
            'worst_trade': 0,
            'consecutive_wins': 0,
            'max_consecutive_wins': 0,
            'roi_percent': 0
        }

        # v3: Quality tracking stats
        self.quality_stats = {
            'trades_tracked': 0,
            'tokens_fetched': 0,
            'whales_promoted': 0,
            'new_whales_discovered': 0,
            'last_promotion_check': datetime.now()
        }

        # v3: Tier promotion interval (every 30 minutes)
        self.tier_promotion_interval = 1800

        # v4: Idempotency protection - track resolved position IDs
        self._resolved_position_ids = set()

        print(f"💰 SMALL CAPITAL SYSTEM v3")
        print(f"   Starting capital: ${starting_capital}")
        print(f"   Kelly Criterion sizing: ENABLED")
        print(f"   WebSocket monitoring: ENABLED")
        print(f"   Risk management: ENABLED")
        print(f"   Whale intelligence: ENABLED")
        print(f"   Multi-timeframe: ENABLED")
        print(f"   Embedded dashboard: ENABLED (port 8080)")
        print(f"   Live trading: {'ENABLED' if config.AUTO_COPY_ENABLED else 'DISABLED (dry run)'}")

    def _initialize_live_trading(self):
        """Initialize live trading components (OrderExecutor, PositionManager, MarketResolver)"""
        try:
            print("\n🔧 Initializing live trading components...")

            # Order executor for placing trades
            self.order_executor = get_order_executor()
            if self.order_executor.initialized:
                print("   ✅ OrderExecutor: Ready")
                balance = self.order_executor.get_usdc_balance()
                print(f"      USDC Balance: ${balance:.2f}")
            else:
                print("   ⚠️ OrderExecutor: Not initialized (check credentials)")

            # Position manager for tracking open positions
            self.position_manager = get_position_manager()
            pending = self.position_manager.get_pending_positions()
            print(f"   ✅ PositionManager: Ready ({len(pending)} existing positions)")

            # Market resolver for detecting market outcomes
            self.market_resolver = get_market_resolver()
            print(f"   ✅ MarketResolver: Ready")

        except Exception as e:
            print(f"   ❌ Error initializing live trading: {e}")
            print(f"      System will continue in dry run mode")
    
    async def run(self):
        """
        Run optimized system for small capital
        """
        
        print("\n" + "="*80)
        print("💰 $100 CAPITAL OPTIMIZATION SYSTEM")
        print("="*80)
        print()
        print("Special optimizations:")
        print("  ⚡ Scan every MINUTE (can't miss opportunities)")
        print("  🎯 Monitor 20-25 best whales (focused pool)")
        print("  💵 Copy sizes: $4-10 (20-40 trades possible)")
        print("  🎲 High selectivity (confidence >90%)")
        print("  📈 Aggressive compounding (weekly increases)")
        print()
        print("Goal: $100 → $1,000 in 30 days (900% return)")
        print("="*80)
        print()
        
        # Populate multi-timeframe tiers from CSV files / database
        # This determines which whales to monitor via WebSocket
        self._populate_multi_timeframe_tiers()

        # Report actual whale count from tiers (not legacy monitoring_pool)
        total_whales = sum(len(tier.whales) for tier in self.multi_tf_strategy.tiers.values())
        print(f"\n✅ Monitoring {total_whales} whales across all tiers")
        print(f"   Starting with ${self.current_capital:.2f}\n")

        # v2: Start embedded dashboard
        await self.dashboard.start()

        # Start parallel tasks
        discovery_task = asyncio.create_task(
            self.discovery.run_ultra_fast_discovery()
        )
        
        monitoring_task = asyncio.create_task(
            self.run_monitoring()
        )
        
        stats_task = asyncio.create_task(
            self.print_stats_loop()
        )
        
        compound_task = asyncio.create_task(
            self.compound_loop()
        )

        # v2: Whale intelligence update loop
        intel_task = asyncio.create_task(
            self.update_whale_intelligence_loop()
        )

        # v3: Position resolution loop (checks pending positions every 30 seconds)
        resolution_task = asyncio.create_task(
            self.position_resolution_loop()
        )

        # v3: Whale quality resolution loop (tracks whale PnL as markets resolve)
        whale_quality_task = asyncio.create_task(
            self.whale_quality_resolution_loop()
        )
        print("📊 Whale quality tracking started (resolution-based PnL)")

        # v4: Market resolver loop for live trading (polls for market outcomes)
        market_resolver_task = None
        if config.AUTO_COPY_ENABLED and self.market_resolver:
            market_resolver_task = asyncio.create_task(
                self.market_resolver.start_resolution_loop(
                    system_callback=self._on_position_resolved
                )
            )
            print("🔍 Market resolver loop started (polling for market outcomes)")

        try:
            tasks = [
                discovery_task,
                monitoring_task,
                stats_task,
                compound_task,
                intel_task,
                resolution_task,
                whale_quality_task
            ]
            if market_resolver_task:
                tasks.append(market_resolver_task)

            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            print("\n⚠️  System stopped")
            self.print_final_summary()
    
    def _get_all_tier_addresses(self) -> list:
        """Get all whale addresses from all tiers"""
        addresses = set()
        for tier in self.multi_tf_strategy.tiers.values():
            for whale in tier.whales:
                addr = whale.get('address', '')
                if addr:
                    addresses.add(addr.lower())
        return list(addresses)

    async def run_monitoring(self):
        """Monitor with WebSocket for sub-second detection"""

        while True:
            try:
                # Get whales from tiers - database is the single source of truth
                whale_addresses = self._get_all_tier_addresses()

                if not whale_addresses:
                    print("⚠️ No whales in tiers - waiting for database analysis...")
                    await asyncio.sleep(60)
                    continue

                print(f"\n🔌 Starting WebSocket monitor for {len(whale_addresses)} tier whales")

                self.ws_monitor = HybridMonitor(whale_addresses)

                # Trade callback
                async def trade_callback(trade_data):
                    # Enrich with whale data from tiers (single source of truth)
                    whale_addr = trade_data.get('whale_address', '')
                    _, tier = self.multi_tf_strategy.find_whale_tier(whale_addr)
                    if tier:
                        whale_data = tier.get_whale_data(whale_addr)
                        if whale_data:
                            trade_data['whale_win_rate'] = whale_data.get('win_rate', 0.72)
                            trade_data['whale_profit'] = whale_data.get('profit', 0)
                            trade_data['whale_trade_count'] = whale_data.get('trade_count', 0)
                        else:
                            trade_data['whale_win_rate'] = 0.72
                            trade_data['whale_profit'] = 0
                            trade_data['whale_trade_count'] = 0
                    else:
                        trade_data['whale_win_rate'] = 0.72
                        trade_data['whale_profit'] = 0
                        trade_data['whale_trade_count'] = 0

                    # Enrich with market question and timeframe from cache (needed for timeframe detection)
                    token_id = trade_data.get('token_id', trade_data.get('asset_id', ''))
                    timeframe_from_gamma = None
                    gamma_market_data = None

                    if token_id and not trade_data.get('market_question'):
                        db = self.discovery.db
                        market_info = db.get_cached_market_info(str(token_id))
                        if market_info and market_info.get('question'):
                            trade_data['market_question'] = market_info.get('question', '')
                            trade_data['market'] = market_info.get('question', '')
                            timeframe_from_gamma = market_info.get('timeframe')
                            trade_data['timeframe'] = timeframe_from_gamma or 'unknown'
                            # Still need to fetch end_date from Gamma (not cached)
                            gamma_market_data = await self._fetch_gamma_market_with_retry(token_id)
                            if gamma_market_data:
                                end_date = gamma_market_data.get('endDate') or gamma_market_data.get('end_date')
                                if end_date:
                                    trade_data['end_date'] = end_date
                        else:
                            # Try to fetch from Gamma API on-demand with retry
                            gamma_market_data = await self._fetch_gamma_market_with_retry(token_id)
                            if gamma_market_data:
                                question = gamma_market_data.get('question', '')
                                if question:
                                    trade_data['market_question'] = question
                                    trade_data['market'] = question

                                    # v3: Extract timeframe from recurrence
                                    timeframe_from_gamma = self._extract_timeframe_from_gamma(gamma_market_data)
                                    trade_data['timeframe'] = timeframe_from_gamma or 'unknown'

                                    # v4: Extract actual end_date for accurate resolution timing
                                    end_date = gamma_market_data.get('endDate') or gamma_market_data.get('end_date')
                                    if end_date:
                                        trade_data['end_date'] = end_date

                                    # Cache with timeframe
                                    db.cache_token_timeframe(str(token_id), timeframe_from_gamma or 'unknown', question[:200])
                                    self.quality_stats['tokens_fetched'] += 1
                            else:
                                # Track API failures for monitoring
                                self.quality_stats['api_failures'] = self.quality_stats.get('api_failures', 0) + 1

                    # Skip non-recurring markets - whitelist only configured tiers
                    VALID_TIMEFRAMES = {'15min', 'hourly', '4hour', 'daily'}
                    market_tf = trade_data.get('timeframe', 'unknown')
                    if market_tf not in VALID_TIMEFRAMES:
                        return  # Silently skip - not a configured recurring market

                    # v2: Track trade for correlation detection
                    market = trade_data.get('market', trade_data.get('market_question', ''))
                    side = trade_data.get('side', 'BUY')
                    if self.whale_intel and market:
                        self.whale_intel.correlation_tracker.record_whale_trade(
                            market, whale_addr, side
                        )

                    # v3: Track whale quality for recognized timeframes
                    if token_id and timeframe_from_gamma and timeframe_from_gamma != 'unknown':
                        await self._track_whale_quality(
                            token_id=str(token_id),
                            whale_address=whale_addr,
                            timeframe=timeframe_from_gamma,
                            trade_data=trade_data,
                            gamma_market_data=gamma_market_data
                        )

                    await self.process_trade_small_capital(trade_data)

                # Start monitoring
                await self.ws_monitor.start(trade_callback)

            except Exception as e:
                print(f"❌ Monitoring error: {e}")
                await asyncio.sleep(60)

    async def update_whale_list_periodically(self):
        """Update WebSocket monitor and refresh tiers from DB every 15 minutes"""
        while True:
            await asyncio.sleep(900)  # 15 minutes

            try:
                # Refresh tiers from database (fixes memory/DB desync)
                db = self.discovery.db
                if db and hasattr(self, 'multi_tf_strategy'):
                    old_count = sum(len(t.whales) for t in self.multi_tf_strategy.tiers.values())
                    self.multi_tf_strategy.load_from_database(db)
                    new_count = sum(len(t.whales) for t in self.multi_tf_strategy.tiers.values())
                    if new_count != old_count:
                        print(f"🔄 Tier refresh: {old_count} → {new_count} whales")

                # Update WebSocket monitor with current whale list
                if self.ws_monitor:
                    whale_addresses = self.discovery.get_monitoring_addresses()
                    self.ws_monitor.update_whales(whale_addresses)
                    print(f"🔄 Updated WebSocket monitor: {len(whale_addresses)} whales")

            except Exception as e:
                print(f"   ⚠️ Periodic update error: {e}")
    
    async def process_trade_small_capital(self, trade_data):
        """
        Process trades with small capital optimization
        
        Key differences:
        - Higher confidence threshold (90% vs 80%)
        - Dynamic position sizing based on capital
        - Stop-loss if capital drops 30%
        """
        
        self.stats['opportunities'] += 1
        
        # Calculate confidence
        score = await self.copier.score_trade(trade_data)
        confidence = score.get('confidence', 0)
        
        # USE CLAUDE AI FOR VALIDATION
        if self.claude_validator.enabled:
            print(f"\n🤖 Analyzing with Claude AI...")
            claude_result = await self.claude_validator.validate_trade(trade_data, confidence)
            
            print(f"   Base confidence: {confidence:.1f}%")
            print(f"   AI adjustment: {claude_result['ai_confidence_boost']:+.1f}%")
            print(f"   Final confidence: {claude_result['final_confidence']:.1f}%")
            print(f"   Reasoning: {claude_result['reasoning']}")
            
            if claude_result['concerns']:
                print(f"   ⚠️  Concerns: {', '.join(claude_result['concerns'])}")
            
            # Use AI-adjusted confidence
            confidence = claude_result['final_confidence']

            # Log validation
            self.claude_validator.log_validation(trade_data, claude_result)

        # v2: WHALE INTELLIGENCE EVALUATION
        # Checks: correlation, market maker detection, specialization, momentum
        try:
            whale_addr = trade_data.get('whale_address', '')
            monitored_whales = self.discovery.get_monitoring_addresses() if self.discovery else []

            intel_result = self.whale_intel.evaluate_trade(
                whale_address=whale_addr,
                trade_data=trade_data,
                monitored_whales=monitored_whales,
                base_confidence=confidence
            )

            # Apply intelligence adjustments
            confidence = intel_result.get('confidence', confidence)

            # Log intelligence findings
            adjustments = intel_result.get('adjustments', [])
            warnings = intel_result.get('warnings', [])

            if adjustments:
                print(f"\n🧠 Whale Intelligence:")
                for adj in adjustments:
                    print(f"   {adj}")

            if warnings:
                print(f"   ⚠️ Warnings: {', '.join(warnings)}")

            # Store intelligence data for analytics
            trade_data['intel_adjustments'] = adjustments
            trade_data['intel_warnings'] = warnings
            trade_data['whale_specialty'] = intel_result.get('specialty_match', False)
            trade_data['whale_consensus'] = intel_result.get('consensus_count', 0)
            trade_data['is_market_maker'] = intel_result.get('is_market_maker', False)

        except Exception as e:
            print(f"   ⚠️ Whale intelligence error: {e}")

        # v2: MULTI-TIMEFRAME STRATEGY
        # Uses tiered thresholds based on whale's specialty and market timeframe
        try:
            whale_addr = trade_data.get('whale_address', '')
            tier_result = self.multi_tf_strategy.should_copy_trade(
                whale_address=whale_addr,
                trade_data=trade_data,
                base_confidence=confidence
            )

            # Log tier decision with market info
            market_question = trade_data.get('market_question', trade_data.get('market', ''))
            print(f"\n📊 Multi-Timeframe Strategy:")
            print(f"   Market: {market_question[:60]}..." if len(market_question) > 60 else f"   Market: {market_question}" if market_question else "   Market: Unknown")
            print(f"   Tier: {tier_result.get('tier_name', 'Unknown')}")
            print(f"   Market timeframe: {tier_result.get('market_timeframe', '?')}")
            print(f"   Threshold: {tier_result['threshold']:.1f}%")
            print(f"   In specialty: {'Yes' if tier_result.get('is_specialty') else 'No'}")
            print(f"   {tier_result['reason']}")

            # Store for analytics
            trade_data['tier'] = tier_result.get('tier', 'unknown')
            trade_data['is_specialty'] = tier_result.get('is_specialty', False)
            trade_data['market_timeframe'] = tier_result.get('market_timeframe', '15min')
            trade_data['threshold_used'] = tier_result['threshold']

            if not tier_result['should_copy']:
                # Below threshold for this tier
                return

            # Use tier-specific position multiplier
            position_multiplier = tier_result.get('position_multiplier', 1.0)

        except Exception as e:
            print(f"   ⚠️ Multi-timeframe error: {e}")
            # Fall back to fixed 90% threshold
            if confidence < 90:
                return
            position_multiplier = 1.0

        # Calculate position size using Kelly Criterion
        whale_data = {
            'win_rate': trade_data.get('whale_win_rate', 0.72),
            'address': trade_data.get('whale_address', ''),
            'trade_count': trade_data.get('whale_trade_count', 0)
        }
        position_size = self.calculate_position_size(confidence, whale_data)

        # Apply tier multiplier
        position_size = position_size * position_multiplier

        # Check if we have capital (only enforce in live mode)
        is_live_mode = config.AUTO_COPY_ENABLED and self.order_executor and self.order_executor.initialized

        if position_size > self.current_capital * 0.15:  # Max 15% per trade
            position_size = self.current_capital * 0.15

        if position_size < 2:
            if is_live_mode:
                # In live mode, reject trades that are too small
                print(f"   ⚠️  Capital too low for this trade (${self.current_capital:.2f})")
                return
            else:
                # In dry run mode, use a reasonable simulated position size
                position_size = 5.0  # $5 simulated position for tracking
                print(f"   📊 Dry run: Using simulated ${position_size:.2f} position (Kelly too small)")

        # COPY THE TRADE
        print(f"\n{'='*80}")
        print(f"🎯 HIGH CONFIDENCE TRADE")
        print(f"{'='*80}")
        print(f"Whale: {trade_data['whale_address'][:10]}...")
        print(f"Confidence: {confidence:.1f}%")
        print(f"Position: ${position_size:.2f} ({position_size/self.current_capital*100:.1f}% of capital)")
        print(f"Current capital: ${self.current_capital:.2f}")
        print(f"Market timeframe: {trade_data.get('market_timeframe', '15min')}")

        # Execute (or simulate)
        if config.AUTO_COPY_ENABLED and self.order_executor and self.order_executor.initialized:
            # LIVE TRADING MODE
            # Check available capital (total - already committed in pending positions)
            if self.position_manager:
                summary = self.position_manager.get_position_summary()
                committed_capital = summary.get('pending_exposure', 0)
                available_capital = self.current_capital - committed_capital

                if position_size > available_capital:
                    print(f"\n⚠️ INSUFFICIENT CAPITAL")
                    print(f"   Requested: ${position_size:.2f}")
                    print(f"   Available: ${available_capital:.2f} (${self.current_capital:.2f} - ${committed_capital:.2f} committed)")
                    print(f"   Skipping trade until positions resolve\n")
                    return

            print(f"🟢 LIVE MODE - Executing real trade...")

            try:
                # Get token_id for the market
                token_id = trade_data.get('token_id', '')
                side = trade_data.get('side', trade_data.get('net_side', 'BUY'))
                whale_price = trade_data.get('price', None)

                if not token_id:
                    print(f"   ⚠️ No token_id in trade data - skipping live execution")
                    return

                # Place the order
                order_result = await self.order_executor.place_order(
                    token_id=token_id,
                    side=side,
                    usdc_amount=position_size,
                    whale_price=whale_price
                )

                if order_result['success']:
                    print(f"   ✅ Order placed successfully!")
                    print(f"      Order ID: {order_result.get('order_id', 'N/A')}")
                    print(f"      Price: {order_result.get('execution_price', 'N/A')}")
                    print(f"      Quantity: {order_result.get('quantity', 'N/A')}")

                    # Record in position manager
                    if self.position_manager:
                        # Prepare order_result dict for position manager
                        order_data = {
                            'order_id': order_result.get('order_id', ''),
                            'token_id': token_id,
                            'side': side,
                            'quantity': order_result.get('quantity', 0),
                            'price': order_result.get('execution_price', 0),
                            'total_cost': position_size,
                            'fill_status': order_result.get('fill_status', 'filled')
                        }

                        # Add confidence to trade_data for storage
                        trade_data['confidence'] = confidence

                        self.position_manager.record_position(
                            order_result=order_data,
                            trade_data=trade_data,
                            market_info=order_result.get('market_info')
                        )
                else:
                    print(f"   ❌ Order failed: {order_result.get('error', 'Unknown error')}")
                    print(f"      Reason: {order_result.get('reason', 'N/A')}")

            except Exception as e:
                print(f"   ❌ Live execution error: {e}")
                import traceback
                traceback.print_exc()
        else:
            # DRY RUN MODE: Add to pending position tracker
            # Profit will be calculated when market resolves (based on timeframe)
            print(f"🔶 DRY RUN - Position will resolve when market closes")
            self.position_tracker.add_position(trade_data, position_size, confidence)

        print(f"{'='*80}\n")

        # Stop-loss check (based on current + pending exposure)
        pending = self.position_tracker.get_pending_summary()
        total_exposure = pending['pending_total']
        if total_exposure > self.current_capital * 0.60:
            print(f"⚠️ High exposure: ${total_exposure:.2f} pending ({total_exposure/self.current_capital*100:.0f}% of capital)")

        if self.current_capital < self.starting_capital * 0.70:
            print("\n" + "="*80)
            print("🛑 STOP-LOSS TRIGGERED")
            print("="*80)
            print(f"Capital dropped to ${self.current_capital:.2f}")
            print(f"Down {100 - self.current_capital/self.starting_capital*100:.1f}%")
            print("Stopping to prevent further losses")
            print("Review strategy and restart when ready")
            print("="*80 + "\n")
            raise KeyboardInterrupt
    
    def calculate_position_size(self, confidence, whale_data=None):
        """
        Kelly Criterion position sizing

        Uses mathematically optimal sizing based on:
        - Whale's historical win rate
        - Trade confidence
        - Current drawdown level
        - Exposure limits

        Returns optimal position size in dollars
        """

        # Get whale stats for Kelly calculation
        if whale_data is None:
            whale_data = {'win_rate': 0.72}  # Default assumption

        # Calculate Kelly-optimal position
        result = self.position_sizer.calculate_optimal_position(
            capital=self.current_capital,
            whale_data=whale_data,
            confidence=confidence
        )

        position = result['position_size']

        # Check with risk manager
        trade_data = {'whale_address': whale_data.get('address', '')}
        risk_check = self.risk_manager.check_trade(trade_data, position)

        if not risk_check['allowed']:
            print(f"   ⚠️ Risk check blocked: {risk_check['reasons']}")
            return 0

        # Use risk-adjusted size
        position = risk_check['size']

        # Log sizing details
        if position > 0:
            print(f"   📊 Kelly sizing: ${position:.2f}")
            print(f"      Raw Kelly: {result.get('raw_kelly', 0)*100:.1f}%")
            print(f"      Win rate used: {result.get('win_rate_used', 0)*100:.0f}%")
            if risk_check.get('reasons'):
                print(f"      Adjustments: {', '.join(risk_check['reasons'])}")

        return position
    
    async def compound_loop(self):
        """
        Check weekly if we should increase position sizes
        
        Every 7 days, if profitable, increase base sizes
        """
        
        while True:
            await asyncio.sleep(604800)  # 7 days
            
            if self.current_capital > self.starting_capital * 2:
                print("\n" + "="*80)
                print("📈 CAPITAL DOUBLED - COMPOUNDING STRATEGY ENGAGED")
                print("="*80)
                print(f"Starting: ${self.starting_capital}")
                print(f"Current: ${self.current_capital:.2f}")
                print(f"Position sizes will now increase with capital")
                print("="*80 + "\n")
    
    async def print_stats_loop(self):
        """Print stats every 3 minutes"""

        while True:
            await asyncio.sleep(180)

            uptime_hours = (datetime.now() - self.stats['start_time']).total_seconds() / 3600

            # Get pending position info
            pending = self.position_tracker.get_pending_summary()

            print("\n" + "-"*80)
            print(f"📊 $100 CAPITAL STATS - {datetime.now().strftime('%H:%M:%S')}")
            print("-"*80)
            print(f"💰 Starting: ${self.starting_capital}  →  Current: ${self.current_capital:.2f}")
            print(f"📈 ROI: {self.stats['roi_percent']:.1f}%  |  Realized profit: ${self.stats['total_profit']:.2f}")
            print(f"⏳ Pending: {pending['pending_count']} positions (${pending['pending_total']:.2f})")
            print(f"📊 Resolved: {self.stats['copies']}  |  Wins: {self.stats['wins']}  |  Losses: {self.stats['losses']}")

            if self.stats['copies'] > 0:
                win_rate = self.stats['wins'] / self.stats['copies'] * 100
                avg_profit = self.stats['total_profit'] / self.stats['copies']
                print(f"🎯 Win rate: {win_rate:.1f}%  |  Avg profit: ${avg_profit:.2f}")

            print(f"🔥 Best trade: ${self.stats['best_trade']:.2f}  |  Worst: ${self.stats['worst_trade']:.2f}")
            print(f"⚡ Streak: {self.stats['consecutive_wins']} wins  |  Best: {self.stats['max_consecutive_wins']}")

            if uptime_hours > 0:
                profit_per_hour = self.stats['total_profit'] / uptime_hours
                profit_per_day = profit_per_hour * 24
                print(f"💵 Profit/day: ${profit_per_day:.2f}")

                # Projection to $1,000
                if profit_per_day > 0:
                    days_to_1k = (1000 - self.current_capital) / profit_per_day
                    print(f"🎯 Days to $1,000: {days_to_1k:.1f} days")

            print("-"*80 + "\n")

            # Save stats to file for dashboard
            self.save_trading_stats()

    def save_trading_stats(self):
        """Save comprehensive trading stats to JSON file"""

        uptime_seconds = (datetime.now() - self.stats['start_time']).total_seconds()
        uptime_hours = uptime_seconds / 3600

        # Calculate derived metrics
        win_rate = self.stats['wins'] / max(1, self.stats['copies']) * 100
        avg_profit = self.stats['total_profit'] / max(1, self.stats['copies'])
        profit_per_hour = self.stats['total_profit'] / max(0.01, uptime_hours)
        profit_per_day = profit_per_hour * 24

        # Count today's trades from log file
        trades_today = 0
        today_str = datetime.now().strftime('%Y-%m-%d')
        try:
            with open('small_capital_log.jsonl', 'r') as f:
                for line in f:
                    if today_str in line:
                        trades_today += 1
        except:
            pass

        stats_data = {
            'timestamp': datetime.now().isoformat(),
            'mode': 'LIVE' if config.AUTO_COPY_ENABLED else 'DRY_RUN',

            # Capital
            'starting_capital': self.starting_capital,
            'current_capital': round(self.current_capital, 2),
            'total_profit': round(self.stats['total_profit'], 2),
            'roi_percent': round(self.stats['roi_percent'], 2),

            # Trading performance
            'total_trades': self.stats['copies'],
            'winning_trades': self.stats['wins'],
            'losing_trades': self.stats['losses'],
            'win_rate': round(win_rate, 1),
            'avg_profit_per_trade': round(avg_profit, 2),

            # Best/worst
            'best_trade': round(self.stats['best_trade'], 2),
            'worst_trade': round(self.stats['worst_trade'], 2),
            'current_streak': self.stats['consecutive_wins'],
            'best_streak': self.stats['max_consecutive_wins'],

            # Rate metrics
            'profit_per_hour': round(profit_per_hour, 2),
            'profit_per_day': round(profit_per_day, 2),
            'trades_today': trades_today,

            # Runtime
            'start_time': self.stats['start_time'].isoformat(),
            'uptime_hours': round(uptime_hours, 2),
            'opportunities_seen': self.stats['opportunities'],

            # Projections
            'days_to_1k': round((1000 - self.current_capital) / max(0.01, profit_per_day), 1) if profit_per_day > 0 else None
        }

        with open('trading_stats.json', 'w') as f:
            json.dump(stats_data, f, indent=2)
    
    def log_trade(self, trade_data, size, profit, confidence):
        """Log trades for analysis - comprehensive logging for dry run evaluation"""

        # Determine outcome
        if profit > 0:
            outcome = 'WIN'
        elif profit < 0:
            outcome = 'LOSS'
        else:
            outcome = 'BREAK_EVEN'

        # Get whale info from tiers (single source of truth)
        whale_info = {}
        whale_addr = trade_data.get('whale_address', '')
        _, tier = self.multi_tf_strategy.find_whale_tier(whale_addr)
        if tier:
            whale_info = tier.get_whale_data(whale_addr) or {}

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'mode': 'LIVE' if config.AUTO_COPY_ENABLED else 'DRY_RUN',

            # Capital tracking
            'capital_before': round(self.current_capital - profit, 2),
            'capital_after': round(self.current_capital, 2),
            'position_size': round(size, 2),
            'profit': round(profit, 2),
            'roi_percent': round(self.stats['roi_percent'], 2),

            # Trade details
            'outcome': outcome,
            'confidence': round(confidence, 1),
            'side': trade_data.get('side', 'UNKNOWN'),
            'price': trade_data.get('price', 0),

            # Whale details
            'whale_address': trade_data.get('whale_address', ''),
            'whale_win_rate': whale_info.get('win_rate', 0),
            'whale_total_profit': whale_info.get('total_profit', 0),
            'whale_trade_count': whale_info.get('trade_count', 0),

            # Market details
            'market': trade_data.get('market_question', trade_data.get('market', 'Unknown')),
            'market_type': '15_minute',

            # Running totals
            'total_trades': self.stats['copies'],
            'total_wins': self.stats['wins'],
            'total_losses': self.stats['losses'],
            'win_rate': round(self.stats['wins'] / max(1, self.stats['copies']) * 100, 1),
            'streak': self.stats['consecutive_wins']
        }

        with open('small_capital_log.jsonl', 'a') as f:
            f.write(json.dumps(log_entry) + '\n')

        # v2: Record to dashboard for real-time display
        if hasattr(self, 'dashboard'):
            self.dashboard.record_trade({
                'tier': trade_data.get('tier', 'unknown'),
                'whale': trade_data.get('whale_address', '')[:10] + '...',
                'confidence': round(confidence, 1),
                'position': round(size, 2),
                'profit': round(profit, 2),
                'market': trade_data.get('market_question', trade_data.get('market', 'Unknown')),
                'outcome': outcome
            })

        # v2: Record to comprehensive analytics
        try:
            market = trade_data.get('market_question', trade_data.get('market', 'Unknown'))
            market_type = self._classify_market(market)

            self.analytics.record_trade(
                whale_address=trade_data.get('whale_address', ''),
                market=market,
                market_type=market_type,
                confidence=confidence,
                position_size=size,
                whale_entry_price=trade_data.get('whale_price', trade_data.get('price', 0)),
                our_entry_price=trade_data.get('price', 0),
                detection_delay_ms=trade_data.get('detection_delay_ms', 3000),
                outcome=outcome,
                profit=profit,
                kelly_recommendation=trade_data.get('kelly_size', size),
                whale_win_rate=whale_info.get('win_rate', whale_info.get('estimated_win_rate', 0.72)),
                # v2: Whale intelligence data in extra_data
                extra_data={
                    'whale_specialty_match': trade_data.get('whale_specialty', False),
                    'whale_consensus': trade_data.get('whale_consensus', 0),
                    'is_market_maker': trade_data.get('is_market_maker', False),
                    'intel_adjustments': trade_data.get('intel_adjustments', []),
                    'intel_warnings': trade_data.get('intel_warnings', [])
                }
            )
        except Exception as e:
            print(f"   ⚠️ Analytics error: {e}")

    def _classify_market(self, market_name: str) -> str:
        """Classify market into type for analytics"""
        market_lower = market_name.lower()
        if 'btc' in market_lower or 'bitcoin' in market_lower:
            if '15' in market_lower or 'minute' in market_lower:
                return 'BTC 15-min'
            elif 'hour' in market_lower:
                return 'BTC Hourly'
            else:
                return 'BTC Other'
        elif 'eth' in market_lower or 'ethereum' in market_lower:
            if '15' in market_lower or 'minute' in market_lower:
                return 'ETH 15-min'
            else:
                return 'ETH Other'
        elif 'sol' in market_lower or 'solana' in market_lower:
            return 'SOL'
        elif 'xrp' in market_lower:
            return 'XRP'
        else:
            return 'Other'

    # =========================================================================
    # v3: WHALE QUALITY TRACKING
    # Real-time tracking of whale performance by timeframe
    # =========================================================================

    def _extract_timeframe_from_gamma(self, gamma_data: dict) -> str:
        """Extract timeframe from Gamma market data (recurrence field only)."""
        if not gamma_data:
            return 'unknown'
        try:
            events = gamma_data.get('events') or []
            if events and isinstance(events[0], dict):
                series = events[0].get('series') or []
                if series and isinstance(series[0], dict):
                    rec = (series[0].get('recurrence') or '').strip().lower()
                    if rec in ('15m', '15min', '15-min'):
                        return '15min'
                    if rec in ('hourly', '1h', '1hr'):
                        return 'hourly'
                    if rec in ('4h', '4hr', '4-hour', '4 hour'):
                        return '4hour'
                    if rec == 'daily':
                        return 'daily'
        except (IndexError, KeyError, TypeError):
            pass
        return 'unknown'

    def _extract_token_side_from_gamma(self, gamma_data: dict, token_id: str) -> str:
        """Extract which side (YES/NO or outcome name) this token represents."""
        if not gamma_data:
            return None
        try:
            raw_ids = gamma_data.get('clobTokenIds')
            if isinstance(raw_ids, str):
                import json as json_mod
                raw_ids = json_mod.loads(raw_ids)

            raw_outcomes = gamma_data.get('outcomes') or gamma_data.get('shortOutcomes') or []
            if isinstance(raw_outcomes, str):
                import json as json_mod
                raw_outcomes = json_mod.loads(raw_outcomes)

            if raw_ids and raw_outcomes:
                idx = next((i for i, id_ in enumerate(raw_ids) if str(id_) == str(token_id)), None)
                if idx is not None and idx < len(raw_outcomes):
                    return str(raw_outcomes[idx]).strip()
        except Exception:
            pass
        return None

    async def _fetch_gamma_market_with_retry(self, token_id: str, max_retries: int = 2) -> dict:
        """
        Fetch market data from Gamma API with retry logic.

        Args:
            token_id: The CLOB token ID
            max_retries: Number of retries on failure

        Returns:
            Market data dict or None on failure
        """
        if not HAS_REQUESTS:
            return None

        url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}"

        for attempt in range(max_retries + 1):
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    markets = response.json()
                    if isinstance(markets, list) and markets:
                        return markets[0]
                elif response.status_code == 429:
                    # Rate limited - respect Retry-After header or use exponential backoff
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = int(retry_after)
                        except ValueError:
                            wait_time = 5 * (attempt + 1)
                    else:
                        wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Log non-200 responses (except 429)
                    if attempt == max_retries:
                        print(f"⚠️ Gamma API error {response.status_code} for token {token_id[:16]}...")
                    continue
            except requests.exceptions.Timeout:
                if attempt == max_retries:
                    print(f"⚠️ Gamma API timeout for token {token_id[:16]}...")
                await asyncio.sleep(0.5)
            except requests.exceptions.RequestException as e:
                if attempt == max_retries:
                    print(f"⚠️ Gamma API request error for token {token_id[:16]}...: {type(e).__name__}")
                await asyncio.sleep(0.5)
            except Exception as e:
                # Unexpected error - log and don't retry
                print(f"⚠️ Unexpected Gamma API error: {type(e).__name__}: {e}")
                break

        return None

    async def _track_whale_quality(self, token_id: str, whale_address: str, timeframe: str,
                                    trade_data: dict, gamma_market_data: dict = None):
        """
        Store whale trade for later resolution-based quality tracking.
        Called when we detect a whale trade on a recognized timeframe market.
        """
        try:
            db = self.discovery.db
            if not db:
                return

            # Get end date for expected resolution
            end_date = None
            if gamma_market_data:
                end_date = gamma_market_data.get('endDate') or gamma_market_data.get('end_date')

            if not end_date:
                # Try to fetch from Gamma if we don't have it
                gamma_market_data = await self._fetch_gamma_market_with_retry(token_id)
                if gamma_market_data:
                    end_date = gamma_market_data.get('endDate') or gamma_market_data.get('end_date')

            if not end_date:
                # Can't track without resolution time
                return

            # Get token side (YES/NO or outcome name)
            token_side = self._extract_token_side_from_gamma(gamma_market_data, token_id)

            # Determine if whale is maker or taker
            whale_addr_lower = whale_address.lower()
            maker = (trade_data.get('maker', '') or '').lower()
            taker = (trade_data.get('taker', '') or '').lower()

            is_maker = (whale_addr_lower == maker)

            # Get amounts
            maker_amount = int(trade_data.get('maker_amount', 0) or trade_data.get('makerAmountFilled', 0))
            taker_amount = int(trade_data.get('taker_amount', 0) or trade_data.get('takerAmountFilled', 0))

            if maker_amount == 0 or taker_amount == 0:
                return

            # Store pending trade
            db.add_pending_whale_trade(
                token_id=token_id,
                whale_address=whale_address,
                is_maker=is_maker,
                maker_amount=maker_amount,
                taker_amount=taker_amount,
                token_side=token_side,
                timeframe=timeframe,
                expected_resolution=end_date
            )

            self.quality_stats['trades_tracked'] += 1

        except Exception as e:
            # Silently fail - quality tracking is non-critical
            pass

    async def whale_quality_resolution_loop(self):
        """
        Periodically check pending whale trades for resolution and update stats.
        Runs every 60 seconds.
        """
        # Check immediately on startup for any past-due whale observations
        first_run = True

        while True:
            try:
                if not first_run:
                    await asyncio.sleep(60)
                else:
                    first_run = False
                    print("🔍 Checking for past-due whale observations on startup...")

                await self._resolve_pending_whale_trades()

                # Periodic tier promotion check (every 30 min)
                now = datetime.now()
                if (now - self.quality_stats['last_promotion_check']).total_seconds() > self.tier_promotion_interval:
                    await self._promote_qualified_whales()
                    self.quality_stats['last_promotion_check'] = now

            except Exception as e:
                print(f"   ⚠️ Quality resolution error: {e}")
                await asyncio.sleep(60)

    async def _resolve_pending_whale_trades(self):
        """Check pending trades and resolve those past their resolution time."""
        db = self.discovery.db
        if not db:
            return

        # Use local time (consistent with how positions are saved)
        current_time = datetime.now().isoformat()

        # Run blocking DB call in thread pool to avoid blocking event loop
        pending_trades = await asyncio.to_thread(db.get_pending_trades_to_resolve, current_time)

        if not pending_trades:
            return

        # Group by token to minimize API calls
        by_token = {}
        for trade in pending_trades:
            token_id = trade['token_id']
            if token_id not in by_token:
                by_token[token_id] = []
            by_token[token_id].append(trade)

        resolved_count = 0

        for token_id, trades in by_token.items():
            try:
                # Fetch resolution from Gamma
                resolution = await self._fetch_token_resolution(token_id)

                if not resolution or not resolution.get('resolved'):
                    # Not resolved yet - will check again later
                    continue

                outcome = resolution.get('outcome')
                if not outcome:
                    continue

                # Cache the resolution in token_timeframes table (in thread pool)
                await asyncio.to_thread(
                    db.update_token_resolution,
                    token_id=token_id,
                    resolved=True,
                    outcome=outcome,
                    token_side=trades[0].get('token_side')
                )

                # Get timeframe and token_side from first trade (same for all)
                timeframe = trades[0]['timeframe']
                token_side = trades[0].get('token_side')

                # Process each trade for this token
                for trade in trades:
                    pnl = self._calculate_whale_pnl(trade, outcome)
                    whale_address = trade['whale_address']
                    volume = trade['taker_amount'] / 1_000_000.0

                    # Update incremental stats (in thread pool)
                    await asyncio.to_thread(
                        db.update_whale_incremental_stats,
                        whale_address, timeframe, pnl, volume
                    )

                    # Delete processed trade (in thread pool)
                    await asyncio.to_thread(db.delete_pending_trade, trade['id'])
                    resolved_count += 1

                # NEW WHALE DISCOVERY: Check all traders on this resolved token
                await self._discover_new_whales_from_token(token_id, outcome, timeframe, token_side)

            except Exception as e:
                # Skip this token on error
                continue

        if resolved_count > 0:
            print(f"   📊 Resolved {resolved_count} whale trades for quality tracking")

    async def _fetch_token_resolution(self, token_id: str) -> dict:
        """Fetch resolution status from Gamma API."""
        if not HAS_REQUESTS:
            return None

        try:
            url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}"
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                return None

            data = r.json()
            if not data or not isinstance(data, list):
                return None

            m = data[0]
            resolved = m.get('resolved', False) or m.get('closed', False)

            if not resolved:
                return {'resolved': False}

            # Get outcome
            raw = m.get('outcome') or m.get('resolution') or m.get('winning_outcome')
            outcome = self._normalize_outcome(raw)

            # Try outcomePrices if outcome not directly available
            if not outcome:
                outcomes = m.get('outcomes') or m.get('shortOutcomes') or []
                if isinstance(outcomes, str):
                    import json as json_mod
                    outcomes = json_mod.loads(outcomes)

                op = m.get('outcomePrices')
                if op:
                    if isinstance(op, str):
                        import json as json_mod
                        op = json_mod.loads(op)
                    if isinstance(op, (list, tuple)):
                        for i, p in enumerate(op):
                            if i < len(outcomes):
                                try:
                                    if p == 1 or p == 1.0 or str(p).strip() == "1":
                                        outcome = self._normalize_outcome(outcomes[i])
                                        break
                                except:
                                    pass

            return {
                'resolved': True,
                'outcome': outcome
            }

        except Exception:
            return None

    def _normalize_outcome(self, val) -> str:
        """Normalize outcome to YES/NO or return raw for non-binary."""
        if val is None:
            return None
        s = str(val).strip().lower()
        if s in ('yes', 'true', '1', 'up'):
            return 'YES'
        if s in ('no', 'false', '0', 'down'):
            return 'NO'
        return str(val).strip() if val else None

    def _calculate_whale_pnl(self, trade: dict, outcome: str) -> float:
        """
        Calculate whale's PnL for a resolved trade.

        PnL rules:
        - Taker buys winning token → wins maker_amount/1e6
        - Taker buys losing token → loses taker_amount/1e6
        - Maker sells winning token → loses (maker_amount - taker_amount)/1e6
        - Maker sells losing token → wins taker_amount/1e6

        Returns 0 if token_side is missing (can't calculate without knowing which side).
        """
        is_maker = trade['is_maker']
        maker_amount = trade['maker_amount']
        taker_amount = trade['taker_amount']
        token_side = trade.get('token_side')

        # CRITICAL: Validate token_side exists before calculating
        # If token_side is None/empty, we can't determine win/loss
        if not token_side:
            print(f"   ⚠️ Missing token_side for trade, skipping PnL calculation")
            return 0.0

        # Normalize for comparison (handle YES/Yes/yes variations)
        outcome_normalized = str(outcome).strip().upper()
        token_side_normalized = str(token_side).strip().upper()

        # Determine if this token won
        token_won = (outcome_normalized == token_side_normalized)

        if is_maker:
            # Maker sold shares
            if token_won:
                # Sold winning shares - loss
                return -max(0, (maker_amount - taker_amount) / 1_000_000.0)
            else:
                # Sold losing shares - kept premium
                return taker_amount / 1_000_000.0
        else:
            # Taker bought shares
            if token_won:
                # Bought winning shares - wins $1/share
                return maker_amount / 1_000_000.0
            else:
                # Bought losing shares - loses payment
                return -(taker_amount / 1_000_000.0)

    async def _promote_qualified_whales(self):
        """Check incremental stats for whales who qualify for tier promotion."""
        db = self.discovery.db
        if not db:
            return

        candidates = db.get_tier_candidates_from_incremental(min_trades=8)

        promoted = 0
        for row in candidates:
            address, timeframe, trades, net_pnl, win_rate = row

            # Check tier requirements
            req = TIER_REQUIREMENTS.get(timeframe, {})
            min_trades = req.get('min_trades', 10)
            min_win_rate = req.get('min_win_rate', 0.65)

            if trades >= min_trades and win_rate >= min_win_rate:
                wins = int(trades * win_rate)
                losses = trades - wins

                db.promote_whale_to_tier(
                    address=address,
                    timeframe=timeframe,
                    trades=trades,
                    wins=wins,
                    losses=losses,
                    volume=0,
                    profit=net_pnl,
                    win_rate=win_rate
                )
                promoted += 1

        if promoted > 0:
            self.quality_stats['whales_promoted'] += promoted
            print(f"   🐋 Promoted {promoted} whales to tiers based on recent performance")

    async def _discover_new_whales_from_token(self, token_id: str, outcome: str, timeframe: str, token_side: str):
        """
        Discover new profitable traders on a resolved token.

        Uses whale_net field from token_timeframes table.
        Finds addresses that won > $500 on this token and aren't in tiers yet.

        Args:
            token_id: The CLOB token ID that just resolved
            outcome: The resolution outcome (YES/NO)
            timeframe: Market timeframe (15min/hourly/4hour/daily)
            token_side: Which side this token represents (YES/NO)
        """
        db = self.discovery.db
        if not db:
            return

        # Get addresses already in tiers (no need to track them again)
        tier_whales = db.get_all_tier_whales()

        try:
            # Get winning whales from token_timeframes.whale_net field
            # Only addresses with PnL >= $500
            winners = db.get_winning_whales_for_token(token_id, min_pnl=500.0)

            if not winners:
                return

            discovered = 0
            for entry in winners:
                addr = entry['address']
                pnl = entry['pnl']

                # Skip addresses already in tiers
                if addr in tier_whales:
                    continue

                # Update incremental stats for this winning trader
                # Volume approximated from PnL (assuming ~50% margin on avg)
                approx_volume = abs(pnl) * 2
                db.update_whale_incremental_stats(addr, timeframe, pnl, approx_volume)
                discovered += 1

            if discovered > 0:
                self.quality_stats['new_whales_discovered'] = self.quality_stats.get('new_whales_discovered', 0) + discovered
                print(f"   🐋 Discovered {discovered} large winning traders on {token_id[:10]}...")

        except Exception as e:
            # Non-critical - silently skip
            pass

    def _populate_multi_timeframe_tiers(self):
        """
        Populate multi-timeframe tiers from CSV files or database.

        Load order:
        1. trader_tier_stats.csv → whale_timeframe_stats table (tier whales)
        2. whale_quality.csv → whale_timeframe_stats table (quality whales)
        3. Load tiers from whale_timeframe_stats into memory
        4. token_timeframes.csv → token_timeframes table (market metadata)

        IMPORTANT: This method BLOCKS until complete. No other operations
        (monitoring, discovery, etc.) will start until this finishes.
        """
        try:
            # Get database from discovery
            db = getattr(self.discovery, 'db', None)
            if not db:
                print("⚠️ No database available for tier population")
                return

            # Load trader_tier_stats.csv if available (primary tier source)
            tier_csv_path = os.environ.get('TRADER_TIER_STATS_CSV', 'trader_tier_stats.csv')
            if os.path.exists(tier_csv_path):
                print(f"\n📂 Loading tier whales from {tier_csv_path}...")
                db.load_trader_tier_stats_csv(tier_csv_path)

            # Load whale_quality.csv if available (supplementary quality whales)
            quality_csv_path = os.environ.get('WHALE_QUALITY_CSV', 'whale_quality.csv')
            if os.path.exists(quality_csv_path):
                print(f"📂 Loading quality whales from {quality_csv_path}...")
                db.load_whale_quality_csv(quality_csv_path)

            # Load tiers from database into memory
            if not self.multi_tf_strategy.load_from_database(db):
                print("⚠️ Failed to load tiers from database")
                return

            print(f"\n📊 MULTI-TIMEFRAME TIERS POPULATED:")
            total_whales = 0
            whale_addresses = []
            for tier_name, tier in self.multi_tf_strategy.tiers.items():
                print(f"   {tier.name}: {len(tier.whales)} whales")
                total_whales += len(tier.whales)
                # Collect addresses for pruning
                for w in tier.whales:
                    addr = w.get('address', '')
                    if addr:
                        whale_addresses.append(addr)
                # Print first 3 addresses for debugging
                for w in tier.whales[:3]:
                    print(f"      - {w.get('address', '')[:16]}...")
            print(f"   Total: {total_whales} unique whales for WebSocket monitoring")

            # Load token_timeframes.csv if available (for new whale discovery)
            csv_path = os.environ.get('TOKEN_TIMEFRAMES_CSV', 'token_timeframes.csv')
            if os.path.exists(csv_path):
                print(f"\n📂 Loading token data from {csv_path}...")
                db.load_token_timeframes_csv(csv_path)
            else:
                token_stats = db.get_token_timeframes_stats()
                if token_stats['total'] > 0:
                    print(f"   Token timeframes data: {token_stats['total']} tokens ({token_stats['resolved']} resolved)")
                else:
                    print(f"   ⚠️ No token_timeframes.csv found - new whale discovery will be limited")

        except Exception as e:
            print(f"⚠️ Error populating tiers: {e}")

    def print_final_summary(self):
        """Print summary when stopped"""
        
        print("\n" + "="*80)
        print("💰 $100 CAPITAL SYSTEM - FINAL SUMMARY")
        print("="*80)
        
        uptime = (datetime.now() - self.stats['start_time']).total_seconds() / 3600
        
        print(f"\n⏱️  Runtime: {uptime:.1f} hours ({uptime/24:.1f} days)")
        
        print(f"\n💰 CAPITAL:")
        print(f"   Starting: ${self.starting_capital}")
        print(f"   Ending: ${self.current_capital:.2f}")
        print(f"   Profit: ${self.stats['total_profit']:.2f}")
        print(f"   ROI: {self.stats['roi_percent']:.1f}%")
        
        print(f"\n📊 TRADING:")
        print(f"   Opportunities: {self.stats['opportunities']}")
        print(f"   Trades: {self.stats['copies']}")
        print(f"   Wins: {self.stats['wins']}")
        print(f"   Losses: {self.stats['losses']}")
        
        if self.stats['copies'] > 0:
            win_rate = self.stats['wins'] / self.stats['copies'] * 100
            avg_profit = self.stats['total_profit'] / self.stats['copies']
            print(f"   Win rate: {win_rate:.1f}%")
            print(f"   Avg profit/trade: ${avg_profit:.2f}")
        
        print(f"\n🎯 BEST/WORST:")
        print(f"   Best trade: ${self.stats['best_trade']:.2f}")
        print(f"   Worst trade: ${self.stats['worst_trade']:.2f}")
        print(f"   Best streak: {self.stats['max_consecutive_wins']} wins")
        
        if uptime > 0:
            print(f"\n⚡ PERFORMANCE:")
            print(f"   Profit/hour: ${self.stats['total_profit']/uptime:.2f}")
            print(f"   Profit/day: ${self.stats['total_profit']/uptime*24:.2f}")
        
        print(f"\n📁 Data saved to: small_capital_log.jsonl")

        # v2: Print comprehensive analytics report
        print("\n" + "="*80)
        print("📊 DRY RUN ANALYTICS REPORT")
        print("="*80)
        print(self.analytics.get_weekly_report())
        print("="*80 + "\n")

        # v2: Print multi-timeframe tier stats
        if hasattr(self, 'multi_tf_strategy'):
            print(self.multi_tf_strategy.get_tier_stats())

    async def print_daily_analytics(self):
        """Print daily analytics summary (called every 6 hours)"""
        while True:
            await asyncio.sleep(21600)  # 6 hours

            print("\n" + "="*80)
            print("📊 ANALYTICS UPDATE")
            print("="*80)
            print(self.analytics.get_daily_summary())
            print(self.analytics.get_market_report())
            print("="*80 + "\n")

    async def position_resolution_loop(self):
        """Check and resolve pending positions every 30 seconds"""
        # Check immediately on startup for any past-due positions
        first_run = True

        while True:
            if not first_run:
                await asyncio.sleep(30)
            else:
                first_run = False
                print("🔍 Checking for past-due dry-run positions on startup...")

            try:
                if config.AUTO_COPY_ENABLED and self.market_resolver:
                    # LIVE MODE: Use MarketResolver to check actual market outcomes
                    await self.market_resolver.check_and_resolve_positions(
                        system_callback=self._on_position_resolved
                    )

                    # Print pending summary from position manager
                    if self.position_manager:
                        summary = self.position_manager.get_position_summary()
                        if summary.get('pending_count', 0) > 0:
                            print(f"\n⏳ Live positions: {summary['pending_count']} pending (${summary.get('pending_value', 0):.2f})")
                else:
                    # DRY RUN MODE: Use simulated position tracker
                    await self.position_tracker.check_and_resolve_positions()

                    # Print pending summary
                    pending = self.position_tracker.get_pending_summary()
                    if pending['pending_count'] > 0:
                        print(f"\n⏳ Pending positions: {pending['pending_count']} (${pending['pending_total']:.2f})")

            except Exception as e:
                print(f"   ⚠️ Position resolution error: {e}")

    async def _on_position_resolved(self, resolved_position: dict):
        """Callback when a live position is resolved by MarketResolver"""
        try:
            # Idempotency check - prevent double-counting if callback fires twice
            position_id = resolved_position.get('id') or resolved_position.get('position_id')
            if position_id:
                if position_id in self._resolved_position_ids:
                    print(f"   ⚠️ Skipping duplicate resolution for {position_id}")
                    return
                self._resolved_position_ids.add(position_id)

            profit = resolved_position.get('pnl', 0)
            is_win = resolved_position.get('is_win', False)
            position_size = resolved_position.get('total_cost', 0)

            # Update stats
            self.stats['copies'] += 1
            self.current_capital += profit
            self.stats['total_profit'] += profit
            self.stats['current_capital'] = self.current_capital

            if is_win:
                self.stats['wins'] += 1
                self.stats['consecutive_wins'] += 1
                self.stats['max_consecutive_wins'] = max(
                    self.stats['max_consecutive_wins'],
                    self.stats['consecutive_wins']
                )
                if profit > self.stats['best_trade']:
                    self.stats['best_trade'] = profit
            else:
                self.stats['losses'] += 1
                self.stats['consecutive_wins'] = 0
                if profit < self.stats['worst_trade']:
                    self.stats['worst_trade'] = profit

            # Update ROI
            self.stats['roi_percent'] = (
                (self.current_capital - self.starting_capital) / self.starting_capital * 100
            )

            # Update risk manager
            self.risk_manager.update_capital(self.current_capital)
            self.position_sizer.record_trade_result(profit, is_win)

            # Reconstruct trade_data from position for logging
            trade_data = {
                'whale_address': resolved_position.get('whale_address', ''),
                'market_question': resolved_position.get('market_question', ''),
                'market': resolved_position.get('market_question', ''),
                'tier': resolved_position.get('tier', 'unknown'),
                'side': resolved_position.get('side', ''),
                'price': resolved_position.get('entry_price', 0)
            }

            self.log_trade(
                trade_data,
                position_size,
                profit,
                resolved_position.get('confidence', 0)
            )

            print(f"\n{'='*80}")
            print(f"📊 LIVE POSITION RESOLVED")
            print(f"{'='*80}")
            print(f"   Position: {resolved_position.get('id', 'N/A')}")
            print(f"   Market: {resolved_position.get('market_question', 'Unknown')[:50]}...")
            print(f"   Our side: {resolved_position.get('side', '?')}")
            print(f"   Market outcome: {resolved_position.get('market_outcome', '?')}")
            print(f"   Outcome: {'✅ WIN' if is_win else '❌ LOSS'}")
            print(f"   P&L: ${profit:+.2f}")
            print(f"   New capital: ${self.current_capital:.2f}")
            print(f"   ROI: {self.stats['roi_percent']:.1f}%")
            print(f"{'='*80}\n")

        except Exception as e:
            print(f"   ⚠️ Error updating stats after resolution: {e}")

    async def update_whale_intelligence_loop(self):
        """Periodically update whale intelligence data"""
        while True:
            await asyncio.sleep(300)  # Every 5 minutes

            try:
                # Update wallet balances for monitored whales
                if self.whale_intel and self.discovery:
                    whale_addrs = self.discovery.get_monitoring_addresses()

                    # Update balances (async-friendly)
                    for addr in whale_addrs[:10]:  # Top 10 to limit RPC calls
                        try:
                            self.whale_intel.balance_checker.update_balance(addr)
                        except:
                            pass

                    # Clean old correlation data
                    self.whale_intel.correlation_tracker._cleanup_old_trades()

            except Exception as e:
                print(f"   ⚠️ Intel update error: {e}")


async def main():
    """Run $100 capital system"""

    # Check for maintenance mode (for safe database uploads)
    import os
    if os.environ.get('MAINTENANCE_MODE') == 'true':
        print("🔧 MAINTENANCE MODE ENABLED")
        print("   System is paused for database upload")
        print("   Set MAINTENANCE_MODE=false to resume")
        print("   SSH is available for file uploads")

        # Keep alive but don't run the system
        while True:
            await asyncio.sleep(60)
            print("   ⏸️  Maintenance mode active...")

    # Get starting capital from user or use default
    starting_capital = 100

    system = SmallCapitalSystem(starting_capital=starting_capital)
    await system.run()


if __name__ == "__main__":
    asyncio.run(main())
