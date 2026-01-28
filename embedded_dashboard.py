"""
Embedded Dashboard for Whale Tracker

Standalone aiohttp web server providing:
- Real-time trading stats
- Whale monitoring overview
- Tier breakdown
- Recent trades history

Access via SSH tunnel from Render:
    ssh -L 8080:localhost:8080 srv-xxx@ssh.render.com
Then open http://localhost:8080 in browser
"""

import asyncio
from datetime import datetime
from aiohttp import web

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
        self.app.router.add_get('/api/pending', self.api_pending_positions)
        self.app.router.add_get('/api/dryrun', self.api_dryrun_summary)
        self.app.router.add_get('/api/observations', self.api_whale_observations)
        self.app.router.add_get('/api/observations/analytics', self.api_observations_analytics)

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
        """Return live trading stats - merge in-memory with database for persistence"""
        stats = self.system.stats.copy()
        uptime_hours = (datetime.now() - stats['start_time']).total_seconds() / 3600

        # Get database stats for dry run mode (these persist across restarts)
        db = getattr(self.system.discovery, 'db', None)
        db_summary = None
        db_error = None
        if db:
            try:
                db_summary = await asyncio.to_thread(db.get_dry_run_summary)
            except Exception as e:
                db_error = str(e)

        # Use database stats if available and more complete than in-memory
        if db_summary and db_summary.get('resolved', 0) > 0:
            total_trades = db_summary.get('resolved', 0)
            wins = db_summary.get('wins', 0)
            losses = db_summary.get('losses', 0)
            total_profit = db_summary.get('realized_pnl', 0)
            win_rate = db_summary.get('win_rate', 0)
        else:
            total_trades = stats['copies']
            wins = stats['wins']
            losses = stats['losses']
            total_profit = stats['total_profit']
            win_rate = round(wins / max(1, total_trades) * 100, 1)

        # Calculate ROI based on actual profit
        starting = stats['starting_capital']
        roi_percent = (total_profit / starting * 100) if starting > 0 else 0

        return web.json_response({
            'mode': 'LIVE' if config.AUTO_COPY_ENABLED else 'DRY_RUN',
            'starting_capital': starting,
            'current_capital': round(starting + total_profit, 2),
            'total_profit': round(total_profit, 2),
            'roi_percent': round(roi_percent, 2),
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'best_trade': round(stats['best_trade'], 2),
            'worst_trade': round(stats['worst_trade'], 2),
            'current_streak': stats['consecutive_wins'],
            'best_streak': stats['max_consecutive_wins'],
            'opportunities': stats['opportunities'],
            'uptime_hours': round(uptime_hours, 2),
            'profit_per_day': round(total_profit / max(0.01, uptime_hours) * 24, 2),
            'start_time': stats['start_time'].isoformat(),
            'timestamp': datetime.now().isoformat(),
            'data_source': 'database' if (db_summary and db_summary.get('resolved', 0) > 0) else 'memory',
            'db_error': db_error
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
                'position_multiplier': tier.position_multiplier,
                'min_win_rate': tier.min_win_rate
            }
        return web.json_response(tiers)

    async def api_trades(self, request):
        """Return recent trades - from database for persistence"""
        db = getattr(self.system.discovery, 'db', None)
        if db:
            try:
                resolved = await asyncio.to_thread(db.get_resolved_dry_run_positions)
                trades = []
                for pos in resolved[:20]:  # Limit to 20 most recent
                    trades.append({
                        'timestamp': pos.get('resolved_at', pos.get('opened_at', '')),
                        'whale': pos.get('whale_address', '')[:10] + '...' if pos.get('whale_address') else '',
                        'market': pos.get('market_question', 'Unknown')[:50],
                        'side': pos.get('side', 'BUY'),
                        'size': round(pos.get('position_size', 0), 2),
                        'outcome': 'WIN' if pos.get('is_win') else 'LOSS',
                        'pnl': round(pos.get('pnl', 0), 2),
                        'timeframe': pos.get('market_timeframe', 'unknown')
                    })
                return web.json_response({'trades': trades, 'count': len(trades)})
            except Exception as e:
                pass
        # Fallback to in-memory
        return web.json_response({'trades': self.recent_trades, 'count': len(self.recent_trades)})

    async def api_pending_positions(self, request):
        """Return pending positions with breakdown by timeframe"""
        pending_summary = self.system.position_tracker.get_pending_summary()
        positions = []

        for pos in self.system.position_tracker.pending_positions:
            positions.append({
                'id': pos.get('id', ''),
                'whale': pos.get('whale_address', '')[:10] + '...' if pos.get('whale_address') else '',
                'size': round(pos.get('position_size', 0), 2),
                'confidence': round(pos.get('confidence', 0), 1),
                'timeframe': pos.get('market_timeframe', ''),
                'market': pos.get('market', '')[:50] + '...' if len(pos.get('market', '')) > 50 else pos.get('market', ''),
                'side': pos.get('side', ''),
                'opened_at': pos.get('opened_at').isoformat() if hasattr(pos.get('opened_at'), 'isoformat') else str(pos.get('opened_at', '')),
                'expected_resolution': pos.get('expected_resolution').strftime('%H:%M:%S') if hasattr(pos.get('expected_resolution'), 'strftime') else str(pos.get('expected_resolution', '')),
                'tier': pos.get('tier', 'unknown')
            })

        return web.json_response({
            'pending_count': pending_summary.get('pending_count', 0),
            'pending_total': round(pending_summary.get('pending_total', 0), 2),
            'resolved_count': pending_summary.get('resolved_count', 0),
            'by_timeframe': pending_summary.get('by_timeframe', {}),
            'positions': positions
        })

    async def api_dryrun_summary(self, request):
        """Return dry run summary from database"""
        db = getattr(self.system.discovery, 'db', None)
        if not db:
            return web.json_response({'error': 'No database available'})

        try:
            # Use asyncio.to_thread to prevent blocking the event loop
            summary = await asyncio.to_thread(db.get_dry_run_summary)
            return web.json_response({
                'total_positions': summary.get('total', 0),
                'pending': summary.get('pending', 0),
                'resolved': summary.get('resolved', 0),
                'wins': summary.get('wins', 0),
                'losses': summary.get('losses', 0),
                'pending_exposure': round(summary.get('pending_exposure', 0), 2),
                'realized_pnl': round(summary.get('realized_pnl', 0), 2),
                'win_rate': round(summary.get('win_rate', 0), 1)
            })
        except Exception as e:
            return web.json_response({'error': str(e)})

    async def api_whale_observations(self, request):
        """Return whale observation stats (trades being watched for resolution)"""
        db = getattr(self.system.discovery, 'db', None)
        if not db:
            return web.json_response({'error': 'No database available'})

        try:
            # Use asyncio.to_thread to prevent blocking the event loop
            summary = await asyncio.to_thread(db.get_pending_trades_summary)
            return web.json_response({
                'total_observations': summary.get('total', 0),
                'unique_tokens': summary.get('unique_tokens', 0),
                'unique_whales': summary.get('unique_whales', 0),
                'ready_to_resolve': summary.get('ready_to_resolve', 0)
            })
        except Exception as e:
            return web.json_response({'error': str(e)})

    async def api_observations_analytics(self, request):
        """Return comprehensive whale observation analytics - what we learned from trades not taken"""
        db = getattr(self.system.discovery, 'db', None)
        if not db:
            return web.json_response({'error': 'No database available'})

        try:
            # Use asyncio.to_thread to prevent blocking the event loop
            analytics = await asyncio.to_thread(db.get_whale_observations_analytics)
            return web.json_response(analytics)
        except Exception as e:
            return web.json_response({'error': str(e)})

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
                <span class="stat-label">Whale Observations</span>
                <span class="stat-value" id="observations-count">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Last Update</span>
                <span class="stat-value" id="last-update">-</span>
            </div>
        </div>

        <div class="card">
            <h2>Pending Positions</h2>
            <div style="text-align: center; padding: 15px 0;">
                <div class="big-number" id="pending-count">0</div>
                <div style="color: #8b949e;">positions awaiting resolution</div>
            </div>
            <div class="stat-row">
                <span class="stat-label">Total Committed</span>
                <span class="stat-value" id="pending-total">$0.00</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">15min</span>
                <span class="stat-value" id="pending-15min">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Hourly</span>
                <span class="stat-value" id="pending-hourly">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">4hour</span>
                <span class="stat-value" id="pending-4hour">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Daily</span>
                <span class="stat-value" id="pending-daily">0</span>
            </div>
        </div>

        <div class="card">
            <h2>Dry Run Summary (DB)</h2>
            <div class="stat-row">
                <span class="stat-label">Total Positions</span>
                <span class="stat-value" id="dryrun-total">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Pending</span>
                <span class="stat-value" id="dryrun-pending">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Resolved</span>
                <span class="stat-value" id="dryrun-resolved">0</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Win Rate</span>
                <span class="stat-value" id="dryrun-winrate">0%</span>
            </div>
            <div class="stat-row">
                <span class="stat-label">Realized P&L</span>
                <span class="stat-value" id="dryrun-pnl">$0.00</span>
            </div>
        </div>

        <div class="card">
            <h2>Tier Breakdown</h2>
            <div id="tier-stats">Loading...</div>
        </div>

        <div class="card" style="grid-column: span 2;">
            <h2>Whale Observations Analytics</h2>
            <p style="color: #8b949e; font-size: 0.85em; margin-bottom: 15px;">What we learned from trades we watched but didn't copy</p>
            <div class="grid" style="grid-template-columns: 1fr 1fr; gap: 15px;">
                <div>
                    <h3 style="color: #58a6ff; font-size: 0.9em; margin-bottom: 10px;">Summary</h3>
                    <div class="stat-row">
                        <span class="stat-label">Whales Observed</span>
                        <span class="stat-value" id="obs-whales">0</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Resolved Trades</span>
                        <span class="stat-value" id="obs-resolved">0</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Overall Win Rate</span>
                        <span class="stat-value" id="obs-winrate">0%</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Total P&L Observed</span>
                        <span class="stat-value" id="obs-pnl">$0.00</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Pending</span>
                        <span class="stat-value" id="obs-pending">0</span>
                    </div>
                </div>
                <div>
                    <h3 style="color: #58a6ff; font-size: 0.9em; margin-bottom: 10px;">Insights</h3>
                    <div class="stat-row">
                        <span class="stat-label">Best Timeframe</span>
                        <span class="stat-value" id="obs-best-tf">-</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Most Active TF</span>
                        <span class="stat-value" id="obs-active-tf">-</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Missed Profit</span>
                        <span class="stat-value positive" id="obs-missed">$0.00</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Avoided Loss</span>
                        <span class="stat-value negative" id="obs-avoided">$0.00</span>
                    </div>
                </div>
            </div>
            <div style="margin-top: 15px;">
                <h3 style="color: #58a6ff; font-size: 0.9em; margin-bottom: 10px;">Performance by Timeframe</h3>
                <div id="obs-by-tf">Loading...</div>
            </div>
            <div style="margin-top: 15px;">
                <h3 style="color: #3fb950; font-size: 0.9em; margin-bottom: 10px;">Top Performers (Whales to Watch)</h3>
                <div id="obs-top-whales" style="font-size: 0.85em;">Loading...</div>
            </div>
        </div>

        <div class="card" style="grid-column: span 2;">
            <h2>Pending Positions Detail</h2>
            <div class="whale-list" id="pending-list">No pending positions</div>
        </div>

        <div class="card" style="grid-column: span 2;">
            <h2>Monitored Whales</h2>
            <div class="whale-list" id="whale-list">Loading...</div>
        </div>

        <div class="card" style="grid-column: span 2;">
            <h2>Recent Resolved Trades</h2>
            <div class="whale-list" id="trade-list">No trades yet</div>
        </div>
    </div>

    <div class="refresh-info">Auto-refreshes every 5 seconds</div>

    <script>
        async function fetchData() {
            try {
                const [statsRes, whalesRes, tiersRes, tradesRes, pendingRes, dryrunRes, obsRes, analyticsRes] = await Promise.all([
                    fetch('/api/stats'),
                    fetch('/api/whales'),
                    fetch('/api/tiers'),
                    fetch('/api/trades'),
                    fetch('/api/pending'),
                    fetch('/api/dryrun'),
                    fetch('/api/observations'),
                    fetch('/api/observations/analytics')
                ]);

                const stats = await statsRes.json();
                const whalesData = await whalesRes.json();
                const tiers = await tiersRes.json();
                const tradesData = await tradesRes.json();
                const pendingData = await pendingRes.json();
                const dryrunData = await dryrunRes.json();
                const obsData = await obsRes.json();
                const analytics = await analyticsRes.json();

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
                document.getElementById('observations-count').textContent = obsData.total_observations || 0;
                document.getElementById('last-update').textContent = new Date().toLocaleTimeString();

                // Update pending positions
                document.getElementById('pending-count').textContent = pendingData.pending_count || 0;
                document.getElementById('pending-total').textContent = '$' + (pendingData.pending_total || 0).toFixed(2);
                const byTf = pendingData.by_timeframe || {};
                document.getElementById('pending-15min').textContent = (byTf['15min'] || {}).count || 0;
                document.getElementById('pending-hourly').textContent = (byTf['hourly'] || {}).count || 0;
                document.getElementById('pending-4hour').textContent = (byTf['4hour'] || {}).count || 0;
                document.getElementById('pending-daily').textContent = (byTf['daily'] || {}).count || 0;

                // Update dry run summary
                document.getElementById('dryrun-total').textContent = dryrunData.total_positions || 0;
                document.getElementById('dryrun-pending').textContent = dryrunData.pending || 0;
                document.getElementById('dryrun-resolved').textContent = dryrunData.resolved || 0;
                document.getElementById('dryrun-winrate').textContent = (dryrunData.win_rate || 0).toFixed(1) + '%';
                const pnl = dryrunData.realized_pnl || 0;
                const pnlEl = document.getElementById('dryrun-pnl');
                pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
                pnlEl.className = 'stat-value ' + (pnl >= 0 ? 'positive' : 'negative');

                // Update observations analytics
                if (analytics.summary) {
                    const s = analytics.summary;
                    document.getElementById('obs-whales').textContent = s.unique_whales_observed || 0;
                    document.getElementById('obs-resolved').textContent = s.total_resolved_trades || 0;
                    document.getElementById('obs-winrate').textContent = (s.overall_win_rate || 0).toFixed(1) + '%';
                    const obsPnl = s.total_pnl_observed || 0;
                    const obsPnlEl = document.getElementById('obs-pnl');
                    obsPnlEl.textContent = (obsPnl >= 0 ? '+' : '') + '$' + obsPnl.toFixed(2);
                    obsPnlEl.className = 'stat-value ' + (obsPnl >= 0 ? 'positive' : 'negative');
                    document.getElementById('obs-pending').textContent = s.pending_observations || 0;
                }
                if (analytics.insights) {
                    const i = analytics.insights;
                    document.getElementById('obs-best-tf').textContent = i.best_timeframe || '-';
                    document.getElementById('obs-active-tf').textContent = i.most_active_timeframe || '-';
                    document.getElementById('obs-missed').textContent = '$' + (i.missed_profit || 0).toFixed(2);
                    document.getElementById('obs-avoided').textContent = '$' + (i.avoided_loss || 0).toFixed(2);
                }
                // By timeframe table
                let tfHtml = '';
                for (const [tf, data] of Object.entries(analytics.by_timeframe || {})) {
                    const tfPnl = data.net_pnl || 0;
                    const tfClass = tfPnl >= 0 ? 'positive' : 'negative';
                    tfHtml += `<div class="stat-row">
                        <span class="stat-label"><span class="tier-badge tier-${tf}">${tf}</span></span>
                        <span class="stat-value">${data.trades} trades · ${data.win_rate}% win · <span class="${tfClass}">${tfPnl >= 0 ? '+' : ''}$${tfPnl.toFixed(2)}</span></span>
                    </div>`;
                }
                document.getElementById('obs-by-tf').innerHTML = tfHtml || 'No data yet';
                // Top performers
                let topHtml = '';
                for (const w of (analytics.top_performers || []).slice(0, 5)) {
                    topHtml += `<div class="stat-row">
                        <span class="whale-addr">${w.address.slice(0, 10)}... <span class="tier-badge tier-${w.timeframe}">${w.timeframe}</span></span>
                        <span class="stat-value positive">+$${w.net_pnl.toFixed(2)} (${w.win_rate}% / ${w.trades})</span>
                    </div>`;
                }
                document.getElementById('obs-top-whales').innerHTML = topHtml || 'No data yet';

                // Update pending positions list
                let pendingHtml = '';
                for (const pos of (pendingData.positions || []).slice(0, 15)) {
                    pendingHtml += `<div class="trade-item">
                        <div class="trade-header">
                            <span class="tier-badge tier-${pos.timeframe}">${pos.timeframe}</span>
                            <span>$${pos.size.toFixed(2)} @ ${pos.confidence}%</span>
                        </div>
                        <div class="trade-time">Whale: ${pos.whale} · ${pos.side} · Resolves: ${pos.expected_resolution}</div>
                        <div class="trade-market">${pos.market}</div>
                    </div>`;
                }
                document.getElementById('pending-list').innerHTML = pendingHtml || 'No pending positions';

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
                    const profit = trade.pnl || 0;  // API returns 'pnl' not 'profit'
                    const profitClass = profit >= 0 ? 'positive' : 'negative';
                    const timeframe = trade.timeframe || '15min';  // API returns 'timeframe' not 'tier'
                    tradeHtml += `<div class="trade-item">
                        <div class="trade-header">
                            <span class="tier-badge tier-${timeframe}">${timeframe}</span>
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
