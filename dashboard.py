"""
Polymarket Whale Tracker Dashboard
Real-time web UI for monitoring whales, trades, and performance
"""

from flask import Flask, render_template_string, jsonify
import json
import os
from datetime import datetime
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'whale-tracker-secret'

# Global state
dashboard_state = {
    'whales': [],
    'recent_trades': [],
    'recommendations': [],
    'stats': {
        'total_whales': 0,
        'active_whales': 0,
        'trades_today': 0,
        'win_rate': 0,
        'total_profit': 0
    },
    'balance': {
        'usdc': 0,
        'matic': 0,
        'address': ''
    },
    'config': {
        'auto_copy': False,
        'dry_run': True,
        'max_copy_size': 100,
        'confidence_threshold': 80
    }
}


def get_balance():
    """Fetch current wallet balance"""
    try:
        funder = os.getenv('FUNDER_ADDRESS')
        rpc_url = os.getenv('POLYGON_RPC_URL', 'https://polygon-rpc.com')
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        funder_checksum = Web3.to_checksum_address(funder)

        # USDC contract
        usdc_address = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'
        usdc_abi = [
            {'constant': True, 'inputs': [{'name': '_owner', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': 'balance', 'type': 'uint256'}], 'type': 'function'},
            {'constant': True, 'inputs': [], 'name': 'decimals', 'outputs': [{'name': '', 'type': 'uint8'}], 'type': 'function'}
        ]
        usdc = w3.eth.contract(address=Web3.to_checksum_address(usdc_address), abi=usdc_abi)

        usdc_balance = usdc.functions.balanceOf(funder_checksum).call()
        decimals = usdc.functions.decimals().call()
        matic_balance = w3.eth.get_balance(funder_checksum)

        return {
            'usdc': usdc_balance / (10 ** decimals),
            'matic': float(w3.from_wei(matic_balance, 'ether')),
            'address': funder
        }
    except Exception as e:
        print(f"Balance error: {e}")
        return {'usdc': 0, 'matic': 0, 'address': os.getenv('FUNDER_ADDRESS', '')}


def load_whale_pool():
    """Load whale pool from CSV if exists"""
    try:
        if os.path.exists('ultra_fast_pool.csv'):
            import pandas as pd
            df = pd.read_csv('ultra_fast_pool.csv')
            whales = df.to_dict('records')
            return whales[:20]  # Top 20
    except:
        pass
    return []


def load_trade_log():
    """Load recent trades from log file"""
    trades = []
    try:
        if os.path.exists('small_capital_log.jsonl'):
            with open('small_capital_log.jsonl', 'r') as f:
                for line in f:
                    try:
                        trade = json.loads(line.strip())
                        trades.append(trade)
                    except:
                        pass
            return trades[-50:]  # Last 50 trades
    except:
        pass
    return trades


def load_scan_status():
    """Load current scan status from stats file"""
    status = {
        'deep_scan_progress': 0,
        'total_whales_found': 0,
        'active_last_5min': 0,
        'monitoring_count': 0,
        'last_update': None,
        'scan_running': False,
        'blocks_scanned': 0,
        'total_blocks': 50000,
        'events_found': 0,
        'scan_status': 'idle'
    }

    # Load scan progress
    try:
        if os.path.exists('scan_progress.json'):
            with open('scan_progress.json', 'r') as f:
                progress = json.load(f)
                status['deep_scan_progress'] = progress.get('progress_percent', 0)
                status['blocks_scanned'] = progress.get('blocks_scanned', 0)
                status['total_blocks'] = progress.get('total_blocks', 50000)
                status['events_found'] = progress.get('events_found', 0)
                status['scan_status'] = progress.get('status', 'scanning')
                status['scan_running'] = True
    except:
        pass

    # Load whale stats
    try:
        if os.path.exists('ultra_fast_stats.json'):
            with open('ultra_fast_stats.json', 'r') as f:
                data = json.load(f)
                status['total_whales_found'] = data.get('total_whales', 0)
                status['monitoring_count'] = data.get('monitoring', 0)
                status['active_last_5min'] = data.get('active_last_5min', 0)
                status['last_update'] = data.get('timestamp', None)
                status['scan_running'] = True
    except:
        pass

    return status


def load_trading_stats():
    """Load comprehensive trading stats"""
    stats = {
        'mode': 'DRY_RUN',
        'current_capital': 100.0,
        'starting_capital': 100.0,
        'total_profit': 0.0,
        'roi_percent': 0.0,
        'total_trades': 0,
        'winning_trades': 0,
        'losing_trades': 0,
        'win_rate': 0.0,
        'avg_profit_per_trade': 0.0,
        'best_trade': 0.0,
        'worst_trade': 0.0,
        'profit_per_day': 0.0,
        'trades_today': 0,
        'current_streak': 0,
        'best_streak': 0,
        'uptime_hours': 0.0,
        'days_to_1k': None
    }

    try:
        if os.path.exists('trading_stats.json'):
            with open('trading_stats.json', 'r') as f:
                data = json.load(f)
                stats.update(data)
    except:
        pass

    return stats


# HTML Template
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Whale Tracker</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid #30363d;
            margin-bottom: 20px;
        }
        .logo { font-size: 24px; font-weight: bold; color: #58a6ff; }
        .status { display: flex; gap: 20px; align-items: center; }
        .status-badge {
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-live { background: #238636; color: white; }
        .status-dry { background: #f0883e; color: white; }

        .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 20px; }
        @media (max-width: 900px) { .grid { grid-template-columns: repeat(2, 1fr); } }

        .card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
        }
        .card h3 { color: #8b949e; font-size: 12px; text-transform: uppercase; margin-bottom: 8px; }
        .card .value { font-size: 28px; font-weight: bold; color: #f0f6fc; }
        .card .value.green { color: #3fb950; }
        .card .value.blue { color: #58a6ff; }

        .section { margin-bottom: 30px; }
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .section-title { font-size: 18px; font-weight: 600; }

        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #30363d;
        }
        th { color: #8b949e; font-size: 12px; text-transform: uppercase; }

        .address { font-family: monospace; color: #58a6ff; }
        .profit { color: #3fb950; }
        .loss { color: #f85149; }

        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }
        .badge-buy { background: #238636; color: white; }
        .badge-sell { background: #da3633; color: white; }
        .badge-copy { background: #1f6feb; color: white; }
        .badge-skip { background: #6e7681; color: white; }

        .two-col { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
        @media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }

        .recommendation {
            background: #1c2128;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
        }
        .recommendation.strong { border-left: 4px solid #3fb950; }
        .recommendation.medium { border-left: 4px solid #f0883e; }
        .recommendation .header { display: flex; justify-content: space-between; margin-bottom: 8px; }
        .recommendation .market { font-weight: 600; }
        .recommendation .confidence { font-size: 14px; }

        .refresh-btn {
            background: #21262d;
            border: 1px solid #30363d;
            color: #c9d1d9;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
        }
        .refresh-btn:hover { background: #30363d; }

        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .live-dot {
            width: 8px;
            height: 8px;
            background: #3fb950;
            border-radius: 50%;
            animation: pulse 2s infinite;
            display: inline-block;
            margin-right: 6px;
        }

        .market-focus {
            background: linear-gradient(135deg, #1f6feb22, #3fb95022);
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }
        .market-focus h4 { color: #58a6ff; margin-bottom: 10px; }
        .market-focus ul { list-style: none; padding-left: 0; }
        .market-focus li { padding: 4px 0; color: #8b949e; }
        .market-focus li::before { content: "⚡ "; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">Polymarket Whale Tracker</div>
            <div class="status">
                <span><span class="live-dot"></span>Live</span>
                <span class="status-badge {{ 'status-live' if config.auto_copy else 'status-dry' }}">
                    {{ 'AUTO-COPY ON' if config.auto_copy else 'DRY RUN' }}
                </span>
            </div>
        </header>

        <div class="market-focus">
            <h4>Market Focus: 15-Minute Prediction Markets</h4>
            <ul>
                <li>BTC price predictions (e.g., "Will BTC be above $98,000 at 6:00 PM?")</li>
                <li>ETH price predictions</li>
                <li>SPY/Stock index predictions</li>
                <li>Up to 96 trading opportunities per day</li>
            </ul>
        </div>

        <!-- Scan Status Banner -->
        {% if scan_status.scan_running or scan_status.total_whales_found > 0 %}
        <div class="card" style="margin-bottom: 20px; background: linear-gradient(135deg, #1f6feb22, #238636 22);">
            <h3 style="color: #58a6ff; margin-bottom: 12px;">SCAN STATUS</h3>
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px;">
                <div>
                    <div style="color: #8b949e; font-size: 11px;">TOTAL TRADERS FOUND</div>
                    <div style="font-size: 24px; font-weight: bold; color: #3fb950;">{{ scan_status.total_whales_found }}</div>
                </div>
                <div>
                    <div style="color: #8b949e; font-size: 11px;">MONITORING POOL</div>
                    <div style="font-size: 24px; font-weight: bold; color: #58a6ff;">{{ scan_status.monitoring_count }}</div>
                </div>
                <div>
                    <div style="color: #8b949e; font-size: 11px;">ACTIVE (LAST 5 MIN)</div>
                    <div style="font-size: 24px; font-weight: bold; color: #f0883e;">{{ scan_status.active_last_5min }}</div>
                </div>
                <div>
                    <div style="color: #8b949e; font-size: 11px;">LAST UPDATE</div>
                    <div style="font-size: 14px; color: #c9d1d9;">{{ scan_status.last_update[:19] if scan_status.last_update else 'Scanning...' }}</div>
                </div>
            </div>
            {% if scan_status.scan_status == 'scanning' or scan_status.deep_scan_progress < 100 %}
            <div style="margin-top: 15px; padding: 15px; background: #21262d; border-radius: 6px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span style="color: #f0883e; font-weight: 600;">Deep Scan In Progress</span>
                    <span style="color: #3fb950; font-weight: bold;">{{ "%.1f"|format(scan_status.deep_scan_progress) }}%</span>
                </div>
                <div style="background: #30363d; border-radius: 4px; height: 20px; overflow: hidden;">
                    <div style="background: linear-gradient(90deg, #238636, #3fb950); height: 100%; width: {{ scan_status.deep_scan_progress }}%; transition: width 0.5s;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 12px; color: #8b949e;">
                    <span>{{ "{:,}".format(scan_status.blocks_scanned) }} / {{ "{:,}".format(scan_status.total_blocks) }} blocks</span>
                    <span>{{ "{:,}".format(scan_status.events_found) }} trades found</span>
                </div>
            </div>
            {% elif scan_status.scan_status == 'complete' %}
            <div style="margin-top: 15px; padding: 10px; background: #23863622; border: 1px solid #238636; border-radius: 6px;">
                <span style="color: #3fb950;">Scan complete!</span> Found {{ "{:,}".format(scan_status.events_found) }} trades. Now monitoring in real-time.
            </div>
            {% endif %}
        </div>
        {% endif %}

        <!-- Trading Performance Section -->
        {% if trading_stats.total_trades > 0 %}
        <div class="card" style="margin-bottom: 20px; background: linear-gradient(135deg, #23863622, #1f6feb22);">
            <h3 style="color: #3fb950; margin-bottom: 12px;">
                TRADING PERFORMANCE
                <span style="font-size: 12px; color: #f0883e; margin-left: 10px;">{{ trading_stats.mode }}</span>
            </h3>
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px;">
                <div>
                    <div style="color: #8b949e; font-size: 11px;">CAPITAL</div>
                    <div style="font-size: 24px; font-weight: bold; color: #3fb950;">${{ "%.2f"|format(trading_stats.current_capital) }}</div>
                    <div style="font-size: 11px; color: {% if trading_stats.roi_percent >= 0 %}#3fb950{% else %}#f85149{% endif %};">
                        {{ "%.1f"|format(trading_stats.roi_percent) }}% ROI
                    </div>
                </div>
                <div>
                    <div style="color: #8b949e; font-size: 11px;">WIN RATE</div>
                    <div style="font-size: 24px; font-weight: bold; color: {% if trading_stats.win_rate >= 70 %}#3fb950{% elif trading_stats.win_rate >= 60 %}#f0883e{% else %}#f85149{% endif %};">
                        {{ "%.1f"|format(trading_stats.win_rate) }}%
                    </div>
                    <div style="font-size: 11px; color: #8b949e;">{{ trading_stats.winning_trades }}W / {{ trading_stats.losing_trades }}L</div>
                </div>
                <div>
                    <div style="color: #8b949e; font-size: 11px;">TOTAL TRADES</div>
                    <div style="font-size: 24px; font-weight: bold; color: #58a6ff;">{{ trading_stats.total_trades }}</div>
                    <div style="font-size: 11px; color: #8b949e;">{{ trading_stats.trades_today }} today</div>
                </div>
                <div>
                    <div style="color: #8b949e; font-size: 11px;">PROFIT/DAY</div>
                    <div style="font-size: 24px; font-weight: bold; color: {% if trading_stats.profit_per_day >= 0 %}#3fb950{% else %}#f85149{% endif %};">
                        ${{ "%.2f"|format(trading_stats.profit_per_day) }}
                    </div>
                    {% if trading_stats.days_to_1k %}
                    <div style="font-size: 11px; color: #8b949e;">{{ "%.0f"|format(trading_stats.days_to_1k) }} days to $1K</div>
                    {% endif %}
                </div>
            </div>
            <div style="margin-top: 15px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; padding-top: 12px; border-top: 1px solid #30363d;">
                <div style="font-size: 12px;">
                    <span style="color: #8b949e;">Total Profit:</span>
                    <span style="color: {% if trading_stats.total_profit >= 0 %}#3fb950{% else %}#f85149{% endif %}; font-weight: 600;">
                        ${{ "%.2f"|format(trading_stats.total_profit) }}
                    </span>
                </div>
                <div style="font-size: 12px;">
                    <span style="color: #8b949e;">Best Trade:</span>
                    <span style="color: #3fb950; font-weight: 600;">${{ "%.2f"|format(trading_stats.best_trade) }}</span>
                </div>
                <div style="font-size: 12px;">
                    <span style="color: #8b949e;">Avg/Trade:</span>
                    <span style="color: #58a6ff; font-weight: 600;">${{ "%.2f"|format(trading_stats.avg_profit_per_trade) }}</span>
                </div>
                <div style="font-size: 12px;">
                    <span style="color: #8b949e;">Streak:</span>
                    <span style="color: #f0883e; font-weight: 600;">{{ trading_stats.current_streak }}W (best: {{ trading_stats.best_streak }})</span>
                </div>
            </div>
        </div>
        {% endif %}

        <div class="grid">
            <div class="card">
                <h3>USDC Balance</h3>
                <div class="value green">${{ "%.2f"|format(balance.usdc) }}</div>
            </div>
            <div class="card">
                <h3>Active Whales</h3>
                <div class="value blue">{{ stats.active_whales }}</div>
            </div>
            <div class="card">
                <h3>Trades Today</h3>
                <div class="value">{{ trading_stats.trades_today if trading_stats.trades_today else stats.trades_today }}</div>
            </div>
            <div class="card">
                <h3>Win Rate</h3>
                <div class="value green">{{ "%.1f"|format(trading_stats.win_rate if trading_stats.total_trades > 0 else stats.win_rate) }}%</div>
            </div>
        </div>

        <div class="two-col">
            <div class="section">
                <div class="section-header">
                    <span class="section-title">Whale Pool (Top 15-Min Specialists)</span>
                    <button class="refresh-btn" onclick="location.reload()">Refresh</button>
                </div>
                <div class="card">
                    <table>
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Address</th>
                                <th>Profit</th>
                                <th>Win Rate</th>
                                <th>Trades</th>
                            </tr>
                        </thead>
                        <tbody id="whale-table">
                            {% if whales %}
                                {% for whale in whales %}
                                <tr>
                                    <td>#{{ loop.index }}</td>
                                    <td class="address">{{ whale.address[:8] if whale.address else 'N/A' }}...{{ whale.address[-4:] if whale.address else '' }}</td>
                                    <td class="profit">${{ "%.0f"|format(whale.profit|default(0)) }}</td>
                                    <td>{{ "%.1f"|format((whale.win_rate|default(0)) * 100) }}%</td>
                                    <td>{{ whale.trades|default(0) }}</td>
                                </tr>
                                {% endfor %}
                            {% else %}
                                <tr>
                                    <td colspan="5" style="text-align: center; color: #8b949e;">
                                        No whales discovered yet. Run <code>python small_capital_system.py</code> to start discovery.
                                    </td>
                                </tr>
                            {% endif %}
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="section">
                <div class="section-header">
                    <span class="section-title">Trade Recommendations</span>
                </div>
                <div id="recommendations">
                    {% if recommendations %}
                        {% for rec in recommendations %}
                        <div class="recommendation {{ 'strong' if rec.confidence > 85 else 'medium' }}">
                            <div class="header">
                                <span class="market">{{ rec.market[:40] }}...</span>
                                <span class="confidence {{ 'profit' if rec.confidence > 80 else '' }}">{{ rec.confidence }}%</span>
                            </div>
                            <div>
                                <span class="badge {{ 'badge-buy' if rec.side == 'BUY' else 'badge-sell' }}">{{ rec.side }}</span>
                                @ ${{ "%.2f"|format(rec.price) }} | ${{ "%.0f"|format(rec.size) }}
                            </div>
                        </div>
                        {% endfor %}
                    {% else %}
                        <div class="recommendation">
                            <div class="header">
                                <span class="market">Waiting for whale trades...</span>
                            </div>
                            <div style="color: #8b949e; font-size: 13px;">
                                Recommendations appear when whales make trades in 15-min markets.
                            </div>
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>

        <div class="section">
            <div class="section-header">
                <span class="section-title">Recent Trades</span>
            </div>
            <div class="card">
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Whale</th>
                            <th>Market</th>
                            <th>Side</th>
                            <th>Price</th>
                            <th>Size</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="trades-table">
                        {% if recent_trades %}
                            {% for trade in recent_trades[-10:]|reverse %}
                            <tr>
                                <td>{{ trade.timestamp[:19] if trade.timestamp else 'N/A' }}</td>
                                <td class="address">{{ (trade.whale_address[:8] + '...' + trade.whale_address[-4:]) if trade.whale_address else 'N/A' }}</td>
                                <td>{{ trade.market_question[:30] if trade.market_question else 'Unknown' }}...</td>
                                <td><span class="badge {{ 'badge-buy' if trade.side == 'BUY' else 'badge-sell' }}">{{ trade.side|default('?') }}</span></td>
                                <td>${{ "%.2f"|format(trade.price|default(0)) }}</td>
                                <td>${{ "%.0f"|format(trade.usdc_value|default(0)) }}</td>
                                <td><span class="badge {{ 'badge-copy' if trade.copied else 'badge-skip' }}">{{ 'COPIED' if trade.copied else 'SKIPPED' }}</span></td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr>
                                <td colspan="7" style="text-align: center; color: #8b949e;">
                                    No trades recorded yet. Start the whale tracker to see trades.
                                </td>
                            </tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="section">
            <div class="section-header">
                <span class="section-title">Configuration</span>
            </div>
            <div class="card">
                <table>
                    <tr>
                        <td><strong>Mode</strong></td>
                        <td>{{ 'LIVE TRADING' if config.auto_copy else 'DRY RUN (Paper Trading)' }}</td>
                    </tr>
                    <tr>
                        <td><strong>Max Copy Size</strong></td>
                        <td>${{ config.max_copy_size }}</td>
                    </tr>
                    <tr>
                        <td><strong>Confidence Threshold</strong></td>
                        <td>{{ config.confidence_threshold }}%</td>
                    </tr>
                    <tr>
                        <td><strong>Wallet Address</strong></td>
                        <td class="address">{{ balance.address }}</td>
                    </tr>
                </table>
            </div>
        </div>
    </div>

    <script>
        // Auto-refresh every 10 seconds for real-time updates
        setTimeout(function() { location.reload(); }, 10000);
    </script>
</body>
</html>
'''


@app.route('/')
def index():
    # Update state
    dashboard_state['balance'] = get_balance()
    dashboard_state['whales'] = load_whale_pool()
    dashboard_state['recent_trades'] = load_trade_log()
    dashboard_state['stats']['active_whales'] = len(dashboard_state['whales'])
    dashboard_state['stats']['trades_today'] = len([t for t in dashboard_state['recent_trades']
                                                     if t.get('timestamp', '').startswith(datetime.now().strftime('%Y-%m-%d'))])

    # Load config
    dashboard_state['config'] = {
        'auto_copy': os.getenv('AUTO_COPY_ENABLED', 'false').lower() == 'true',
        'dry_run': os.getenv('AUTO_COPY_ENABLED', 'false').lower() != 'true',
        'max_copy_size': float(os.getenv('MAX_COPY_SIZE_USD', '100')),
        'confidence_threshold': float(os.getenv('CONFIDENCE_THRESHOLD', '80'))
    }

    # Load scan status
    scan_status = load_scan_status()

    # Load trading stats
    trading_stats = load_trading_stats()

    return render_template_string(
        DASHBOARD_HTML,
        balance=dashboard_state['balance'],
        whales=dashboard_state['whales'],
        recent_trades=dashboard_state['recent_trades'],
        recommendations=dashboard_state['recommendations'],
        stats=dashboard_state['stats'],
        config=dashboard_state['config'],
        scan_status=scan_status,
        trading_stats=trading_stats
    )


@app.route('/api/refresh')
def api_refresh():
    dashboard_state['balance'] = get_balance()
    dashboard_state['whales'] = load_whale_pool()
    dashboard_state['recent_trades'] = load_trade_log()
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})


@app.route('/api/balance')
def api_balance():
    return jsonify(get_balance())


@app.route('/api/whales')
def api_whales():
    return jsonify(load_whale_pool())


@app.route('/api/trades')
def api_trades():
    return jsonify(load_trade_log())


if __name__ == '__main__':
    print("\n" + "="*60)
    print("  WHALE TRACKER DASHBOARD")
    print("  http://localhost:8080")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=8080, debug=False)
