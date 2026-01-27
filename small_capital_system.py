"""
$100 Capital Optimized Trading System v2

Enhancements:
1. SQLite storage (no redundant scans)
2. Kelly Criterion position sizing
3. WebSocket real-time monitoring (sub-second detection)
4. Enhanced risk management (trailing stops, limits)
5. Incremental-only blockchain scanning
6. Trade aggregation (filters arbitrage/hedging)
7. Pending position tracking (profit counted on market resolution)
"""

import asyncio
from datetime import datetime, timedelta
import json
import os
import random

from aiohttp import web

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
    3. Simulate/resolve the position when the market closes
    4. Only then update capital and stats

    In dry run mode: Simulates resolution based on whale's historical win rate
    In live mode: Would check actual market resolution via Polymarket API
    """

    def __init__(self, system):
        self.system = system
        self.pending_positions = []  # List of pending position dicts
        self.resolved_positions = []  # History of resolved positions

    def add_position(self, trade_data: dict, position_size: float, confidence: float):
        """
        Add a new pending position

        Args:
            trade_data: Original trade data from whale detection
            position_size: Our position size in USDC
            confidence: Confidence score used for this trade
        """
        market_timeframe = trade_data.get('market_timeframe', '15min')
        resolution_delay = TIMEFRAME_DURATIONS.get(market_timeframe, timedelta(minutes=15))

        position = {
            'id': f"{trade_data.get('whale_address', '')[:10]}_{datetime.now().timestamp()}",
            'opened_at': datetime.now(),
            'expected_resolution': datetime.now() + resolution_delay,
            'market_timeframe': market_timeframe,
            'position_size': position_size,
            'confidence': confidence,
            'whale_address': trade_data.get('whale_address', ''),
            'whale_win_rate': trade_data.get('whale_win_rate', 0.72),
            'side': trade_data.get('side', trade_data.get('net_side', 'BUY')),
            'market': trade_data.get('market_question', trade_data.get('market', 'Unknown')),
            'tier': trade_data.get('tier', 'unknown'),
            'trade_data': trade_data,
            'status': 'pending'
        }

        self.pending_positions.append(position)

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
        Resolve a position (determine win/loss and update stats)

        In dry run: Uses whale win rate to simulate outcome
        In live: Would check actual market resolution
        """
        # Remove from pending
        self.pending_positions = [p for p in self.pending_positions if p['id'] != position['id']]

        # Determine outcome
        # In dry run, simulate based on whale's historical win rate
        whale_win_rate = position['whale_win_rate']
        confidence = position['confidence']

        # Adjust probability based on confidence (higher confidence = slightly better odds)
        adjusted_win_prob = whale_win_rate * (0.9 + (confidence / 1000))  # Small confidence boost
        adjusted_win_prob = min(adjusted_win_prob, 0.95)  # Cap at 95%

        is_win = random.random() < adjusted_win_prob

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
from fifteen_minute_monitor import FifteenMinuteMonitor
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


class EmbeddedDashboard:
    """
    Embedded aiohttp web server for real-time dashboard

    Access via SSH tunnel from Render:
        ssh -L 8080:localhost:8080 srv-xxx@ssh.render.com
    Then open http://localhost:8080 in browser
    """

    def __init__(self, system):
        self.system = system
        self.app = web.Application()
        self.setup_routes()
        self.recent_trades = []  # Last 50 trades for display
        self.max_recent_trades = 50

    def setup_routes(self):
        """Setup API and dashboard routes"""
        self.app.router.add_get('/', self.dashboard_html)
        self.app.router.add_get('/api/stats', self.api_stats)
        self.app.router.add_get('/api/whales', self.api_whales)
        self.app.router.add_get('/api/tiers', self.api_tiers)
        self.app.router.add_get('/api/trades', self.api_trades)
        self.app.router.add_get('/api/health', self.api_health)

    def record_trade(self, trade_data):
        """Record a trade for display (called from main system)"""
        self.recent_trades.insert(0, {
            'timestamp': datetime.now().isoformat(),
            **trade_data
        })
        # Keep only last N trades
        self.recent_trades = self.recent_trades[:self.max_recent_trades]

    async def api_health(self, request):
        """Health check endpoint"""
        return web.json_response({
            'status': 'running',
            'timestamp': datetime.now().isoformat(),
            'uptime_hours': round((datetime.now() - self.system.stats['start_time']).total_seconds() / 3600, 2)
        })

    async def api_stats(self, request):
        """Return live trading stats"""
        stats = self.system.stats.copy()
        uptime_hours = (datetime.now() - stats['start_time']).total_seconds() / 3600

        return web.json_response({
            'mode': 'LIVE' if config.AUTO_COPY_ENABLED else 'DRY_RUN',
            'starting_capital': stats['starting_capital'],
            'current_capital': round(self.system.current_capital, 2),
            'total_profit': round(stats['total_profit'], 2),
            'roi_percent': round(stats['roi_percent'], 2),
            'total_trades': stats['copies'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': round(stats['wins'] / max(1, stats['copies']) * 100, 1),
            'best_trade': round(stats['best_trade'], 2),
            'worst_trade': round(stats['worst_trade'], 2),
            'current_streak': stats['consecutive_wins'],
            'best_streak': stats['max_consecutive_wins'],
            'opportunities': stats['opportunities'],
            'uptime_hours': round(uptime_hours, 2),
            'profit_per_day': round(stats['total_profit'] / max(0.01, uptime_hours) * 24, 2),
            'start_time': stats['start_time'].isoformat(),
            'timestamp': datetime.now().isoformat()
        })

    async def api_whales(self, request):
        """Return all monitored whales with tier info"""
        whales = []
        for tier_name, tier in self.system.multi_tf_strategy.tiers.items():
            for whale in tier.whales:
                whales.append({
                    'address': whale.get('address', ''),
                    'tier': tier_name,
                    'win_rate': round(whale.get('win_rate', 0) * 100, 1),
                    'trade_count': whale.get('trade_count', 0),
                    'profit': round(whale.get('profit', whale.get('total_profit', 0)), 2),
                    'specialty': whale.get('specialty', tier_name)
                })
        return web.json_response({'whales': whales, 'total': len(whales)})

    async def api_tiers(self, request):
        """Return tier summary"""
        tiers = {}
        for tier_name, tier in self.system.multi_tf_strategy.tiers.items():
            tiers[tier_name] = {
                'name': tier.name,
                'whale_count': len(tier.whales),
                'base_threshold': tier.base_threshold,
                'outside_penalty': tier.outside_specialty_penalty,
                'min_trades': tier.min_trades,
                'min_win_rate': tier.min_win_rate
            }
        return web.json_response(tiers)

    async def api_trades(self, request):
        """Return recent trades"""
        return web.json_response({'trades': self.recent_trades, 'count': len(self.recent_trades)})

    async def dashboard_html(self, request):
        """Serve the dashboard HTML"""
        html = '''<!DOCTYPE html>
<html>
<head>
    <title>Whale Tracker Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117; color: #c9d1d9; padding: 20px;
        }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { color: #58a6ff; font-size: 2em; }
        .mode-badge {
            display: inline-block; padding: 4px 12px; border-radius: 20px;
            font-size: 0.8em; font-weight: bold; margin-top: 10px;
        }
        .mode-live { background: #238636; color: white; }
        .mode-dry { background: #f0883e; color: black; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card {
            background: #161b22; border: 1px solid #30363d; border-radius: 8px;
            padding: 20px;
        }
        .card h2 { color: #58a6ff; font-size: 1.1em; margin-bottom: 15px; border-bottom: 1px solid #30363d; padding-bottom: 10px; }
        .stat-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #21262d; }
        .stat-label { color: #8b949e; }
        .stat-value { font-weight: bold; }
        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        .whale-list { max-height: 300px; overflow-y: auto; }
        .whale-item {
            padding: 10px; border-bottom: 1px solid #21262d;
            display: flex; justify-content: space-between; align-items: center;
        }
        .whale-addr { font-family: monospace; font-size: 0.85em; color: #8b949e; }
        .whale-stats { text-align: right; }
        .tier-badge {
            font-size: 0.7em; padding: 2px 6px; border-radius: 4px;
            background: #30363d; color: #c9d1d9;
        }
        .tier-15min { background: #238636; }
        .tier-hourly { background: #1f6feb; }
        .tier-4hour { background: #8957e5; }
        .tier-daily { background: #f0883e; }
        .trade-item { padding: 12px; border-bottom: 1px solid #21262d; }
        .trade-header { display: flex; justify-content: space-between; margin-bottom: 5px; }
        .trade-time { color: #8b949e; font-size: 0.85em; }
        .trade-market { font-size: 0.9em; color: #c9d1d9; margin-top: 5px; }
        .big-number { font-size: 2em; font-weight: bold; }
        .refresh-info { text-align: center; color: #8b949e; font-size: 0.85em; margin-top: 20px; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .live-indicator { animation: pulse 2s infinite; color: #3fb950; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Polymarket Whale Tracker</h1>
        <div id="mode-badge" class="mode-badge mode-dry">DRY RUN</div>
        <div class="live-indicator" style="margin-top: 10px;">● Live</div>
    </div>

    <div class="grid">
        <div class="card">
            <h2>Capital</h2>
            <div style="text-align: center; padding: 20px 0;">
                <div class="big-number" id="current-capital">$100.00</div>
                <div style="margin-top: 10px;">
                    <span id="roi" class="positive">+0.0%</span> ROI
                </div>
            </div>
            <div class="stat-row">
                <span class="stat-label">Starting</span>
                <span class="stat-value" id="starting-capital">$100.00</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Total Profit</span>
                <span class="stat-value positive" id="total-profit">$0.00</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Profit/Day</span>
                <span class="stat-value" id="profit-per-day">$0.00</span>
            </div>
        </div>

        <div class="card">
            <h2>Trading Performance</h2>
            <div class="stat-row">
                <span class="stat-label">Total Trades</span>
                <span class="stat-value" id="total-trades">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Wins / Losses</span>
                <span class="stat-value"><span id="wins" class="positive">0</span> / <span id="losses" class="negative">0</span></span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Win Rate</span>
                <span class="stat-value" id="win-rate">0%</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Best Trade</span>
                <span class="stat-value positive" id="best-trade">$0.00</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Worst Trade</span>
                <span class="stat-value negative" id="worst-trade">$0.00</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Current Streak</span>
                <span class="stat-value" id="streak">0</span>
            </div>
        </div>

        <div class="card">
            <h2>System Status</h2>
            <div class="stat-row">
                <span class="stat-label">Uptime</span>
                <span class="stat-value" id="uptime">0h</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Opportunities Seen</span>
                <span class="stat-value" id="opportunities">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Whales Monitored</span>
                <span class="stat-value" id="whale-count">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Last Update</span>
                <span class="stat-value" id="last-update">-</span>
            </div>
        </div>

        <div class="card">
            <h2>Tier Breakdown</h2>
            <div id="tier-stats">Loading...</div>
        </div>

        <div class="card" style="grid-column: span 2;">
            <h2>Monitored Whales</h2>
            <div class="whale-list" id="whale-list">Loading...</div>
        </div>

        <div class="card" style="grid-column: span 2;">
            <h2>Recent Trades</h2>
            <div class="whale-list" id="trade-list">No trades yet</div>
        </div>
    </div>

    <div class="refresh-info">Auto-refreshes every 5 seconds</div>

    <script>
        async function fetchData() {
            try {
                const [statsRes, whalesRes, tiersRes, tradesRes] = await Promise.all([
                    fetch('/api/stats'),
                    fetch('/api/whales'),
                    fetch('/api/tiers'),
                    fetch('/api/trades')
                ]);

                const stats = await statsRes.json();
                const whalesData = await whalesRes.json();
                const tiers = await tiersRes.json();
                const tradesData = await tradesRes.json();

                // Update mode badge
                const modeBadge = document.getElementById('mode-badge');
                modeBadge.textContent = stats.mode;
                modeBadge.className = 'mode-badge ' + (stats.mode === 'LIVE' ? 'mode-live' : 'mode-dry');

                // Update capital
                document.getElementById('current-capital').textContent = '$' + stats.current_capital.toFixed(2);
                document.getElementById('starting-capital').textContent = '$' + stats.starting_capital.toFixed(2);
                document.getElementById('total-profit').textContent = '$' + stats.total_profit.toFixed(2);
                document.getElementById('profit-per-day').textContent = '$' + stats.profit_per_day.toFixed(2);

                const roiEl = document.getElementById('roi');
                roiEl.textContent = (stats.roi_percent >= 0 ? '+' : '') + stats.roi_percent.toFixed(1) + '%';
                roiEl.className = stats.roi_percent >= 0 ? 'positive' : 'negative';

                // Update trading stats
                document.getElementById('total-trades').textContent = stats.total_trades;
                document.getElementById('wins').textContent = stats.wins;
                document.getElementById('losses').textContent = stats.losses;
                document.getElementById('win-rate').textContent = stats.win_rate + '%';
                document.getElementById('best-trade').textContent = '$' + stats.best_trade.toFixed(2);
                document.getElementById('worst-trade').textContent = '$' + stats.worst_trade.toFixed(2);
                document.getElementById('streak').textContent = stats.current_streak;

                // Update system status
                document.getElementById('uptime').textContent = stats.uptime_hours.toFixed(1) + 'h';
                document.getElementById('opportunities').textContent = stats.opportunities;
                document.getElementById('whale-count').textContent = whalesData.total;
                document.getElementById('last-update').textContent = new Date().toLocaleTimeString();

                // Update tier stats
                let tierHtml = '';
                for (const [name, tier] of Object.entries(tiers)) {
                    tierHtml += `<div class="stat-row">
                        <span class="stat-label"><span class="tier-badge tier-${name}">${name}</span></span>
                        <span class="stat-value">${tier.whale_count} whales (${tier.base_threshold}% threshold)</span>
                    </div>`;
                }
                document.getElementById('tier-stats').innerHTML = tierHtml;

                // Update whale list
                let whaleHtml = '';
                for (const whale of whalesData.whales.slice(0, 20)) {
                    whaleHtml += `<div class="whale-item">
                        <div>
                            <span class="tier-badge tier-${whale.tier}">${whale.tier}</span>
                            <span class="whale-addr">${whale.address.slice(0, 10)}...</span>
                        </div>
                        <div class="whale-stats">
                            <span class="positive">${whale.win_rate}%</span> win · ${whale.trade_count} trades
                        </div>
                    </div>`;
                }
                document.getElementById('whale-list').innerHTML = whaleHtml || 'No whales loaded';

                // Update trade list
                let tradeHtml = '';
                for (const trade of tradesData.trades.slice(0, 10)) {
                    const profit = trade.profit || 0;
                    const profitClass = profit >= 0 ? 'positive' : 'negative';
                    tradeHtml += `<div class="trade-item">
                        <div class="trade-header">
                            <span class="tier-badge tier-${trade.tier || '15min'}">${trade.tier || '15min'}</span>
                            <span class="${profitClass}">${profit >= 0 ? '+' : ''}$${profit.toFixed(2)}</span>
                        </div>
                        <div class="trade-time">${new Date(trade.timestamp).toLocaleString()}</div>
                        <div class="trade-market">${trade.market || 'Unknown market'}</div>
                    </div>`;
                }
                document.getElementById('trade-list').innerHTML = tradeHtml || 'No trades yet';

            } catch (err) {
                console.error('Fetch error:', err);
            }
        }

        // Initial fetch and refresh every 5 seconds
        fetchData();
        setInterval(fetchData, 5000);
    </script>
</body>
</html>'''
        return web.Response(text=html, content_type='text/html')

    async def start(self, host='0.0.0.0', port=8080):
        """Start the web server"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        print(f"\n🌐 Dashboard running at http://{host}:{port}")
        print(f"   Access via SSH tunnel: ssh -L 8080:localhost:8080 <render-ssh>")
        print(f"   Then open: http://localhost:8080\n")


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
        self.position_tracker = PendingPositionTracker(self)

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

        print(f"💰 SMALL CAPITAL SYSTEM v2")
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
        
        # Initial discovery - refreshes whale data from database
        print("🔍 Analyzing traders from database...")
        await self.discovery.deep_scan()

        # Populate multi-timeframe tiers from database analysis
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
                resolution_task
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

                    # v2: Track trade for correlation detection
                    market = trade_data.get('market', trade_data.get('market_question', ''))
                    side = trade_data.get('side', 'BUY')
                    if self.whale_intel and market:
                        self.whale_intel.correlation_tracker.record_trade(
                            whale_addr, market, side
                        )

                    await self.process_trade_small_capital(trade_data)

                # Start monitoring
                await self.ws_monitor.start(trade_callback)

            except Exception as e:
                print(f"❌ Monitoring error: {e}")
                await asyncio.sleep(60)

    async def update_whale_list_periodically(self):
        """Update WebSocket monitor with new whale list every 15 minutes"""
        while True:
            await asyncio.sleep(900)  # 15 minutes

            if self.ws_monitor:
                whale_addresses = self.discovery.get_monitoring_addresses()
                self.ws_monitor.update_whales(whale_addresses)
                print(f"🔄 Updated WebSocket monitor: {len(whale_addresses)} whales")
    
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

            # Log tier decision
            print(f"\n📊 Multi-Timeframe Strategy:")
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

        # Check if we have capital
        if position_size > self.current_capital * 0.15:  # Max 15% per trade
            position_size = self.current_capital * 0.15
        
        if position_size < 2:  # Minimum $2 to make sense
            print(f"   ⚠️  Capital too low for this trade (${self.current_capital:.2f})")
            return
        
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

    def _populate_multi_timeframe_tiers(self):
        """
        Populate multi-timeframe tiers from database analysis

        Database is the single source of truth - no fallbacks

        IMPORTANT: This method BLOCKS until complete. No other operations
        (monitoring, discovery, etc.) will start until this finishes.
        """
        try:
            # Get database from discovery
            db = getattr(self.discovery, 'db', None)
            if not db:
                print("⚠️ No database available for tier population")
                return

            # Load directly from database - no fallbacks
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

            # PRUNE NON-WHALE TRADES from database to save space
            # This removes trades from addresses we don't care about
            # BLOCKING: All other operations are paused until pruning completes
            if whale_addresses:
                stats_before = db.get_database_stats()
                trade_count = stats_before['trade_count']

                # Always attempt prune - let the database method decide if needed
                print(f"\n🛑 SYSTEM PAUSED FOR DATABASE MAINTENANCE")
                print(f"   All monitoring and discovery tasks will wait...")
                print(f"   Current trade count: {trade_count:,}")

                deleted = db.prune_non_whale_trades(whale_addresses)

                if deleted > 0:
                    stats_after = db.get_database_stats()
                    print(f"   Kept {stats_after['trade_count']:,} whale trades")

                print(f"✅ DATABASE MAINTENANCE COMPLETE - Resuming operations\n")

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
        while True:
            await asyncio.sleep(30)

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
