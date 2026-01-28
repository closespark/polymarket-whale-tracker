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
