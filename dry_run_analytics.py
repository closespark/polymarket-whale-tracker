"""
Dry Run Analytics System

Comprehensive data collection for dry run evaluation:
1. Per-whale performance breakdown
2. Market-specific performance
3. Timing & market conditions
4. Confidence score calibration
5. Entry price analysis
6. Position sizing effectiveness
7. Risk events & edge cases

Generates daily and weekly reports for optimization.
"""

import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional
import os


class DryRunAnalytics:
    """
    Comprehensive analytics for dry run evaluation

    Collects granular data to optimize live trading strategy
    """

    def __init__(self, data_dir: str = "."):
        self.data_dir = data_dir
        self.analytics_file = os.path.join(data_dir, "dry_run_analytics.json")

        # Initialize data structures
        self.data = {
            'start_time': datetime.now().isoformat(),
            'trades': [],  # All trade records
            'whale_stats': defaultdict(lambda: {
                'trades': [],
                'wins': 0,
                'losses': 0,
                'total_profit': 0,
                'by_market_type': defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0}),
                'by_hour': defaultdict(lambda: {'wins': 0, 'losses': 0}),
                'by_day': defaultdict(lambda: {'wins': 0, 'losses': 0}),
                'by_confidence': defaultdict(lambda: {'wins': 0, 'losses': 0}),
                'streaks': {'current': 0, 'after_wins': [], 'after_losses': []}
            }),
            'market_stats': defaultdict(lambda: {
                'trades': 0, 'wins': 0, 'losses': 0, 'profit': 0,
                'best_whale': None, 'best_whale_win_rate': 0
            }),
            'timing_stats': {
                'by_hour': defaultdict(lambda: {'wins': 0, 'losses': 0, 'trades': 0}),
                'by_day': defaultdict(lambda: {'wins': 0, 'losses': 0, 'trades': 0}),
                'by_volatility': {'high': {'wins': 0, 'losses': 0}, 'low': {'wins': 0, 'losses': 0}}
            },
            'confidence_calibration': defaultdict(lambda: {
                'predicted_wins': 0, 'actual_wins': 0, 'total': 0
            }),
            'execution_stats': {
                'slippage': [],
                'detection_delays': [],
                'by_market_type': defaultdict(lambda: {'slippage': [], 'delays': []})
            },
            'kelly_stats': {
                'recommendations': [],
                'actual_sizes': [],
                'outcomes': []
            },
            'edge_cases': [],
            'daily_summaries': []
        }

        # Load existing data if available
        self._load_data()

        print(f"📊 Dry Run Analytics initialized")
        print(f"   Data file: {self.analytics_file}")

    def _load_data(self):
        """Load existing analytics data"""
        if os.path.exists(self.analytics_file):
            try:
                with open(self.analytics_file, 'r') as f:
                    saved = json.load(f)
                    # Merge with defaults
                    for key in saved:
                        if key in self.data:
                            if isinstance(self.data[key], dict):
                                self.data[key].update(saved[key])
                            else:
                                self.data[key] = saved[key]
                    print(f"   Loaded {len(saved.get('trades', []))} existing trades")
            except:
                pass

    def _save_data(self):
        """Save analytics data to file"""
        # Convert defaultdicts to regular dicts for JSON serialization
        save_data = json.loads(json.dumps(self.data, default=str))
        with open(self.analytics_file, 'w') as f:
            json.dump(save_data, f, indent=2)

    def record_trade(self,
                    whale_address: str,
                    market: str,
                    market_type: str,
                    confidence: float,
                    position_size: float,
                    whale_entry_price: float,
                    our_entry_price: float,
                    detection_delay_ms: int,
                    outcome: str,  # 'WIN' or 'LOSS'
                    profit: float,
                    kelly_recommendation: float = None,
                    whale_win_rate: float = None,
                    extra_data: Dict = None):
        """
        Record a trade with comprehensive data

        This is the main entry point for logging trades
        """

        timestamp = datetime.now()
        hour = timestamp.hour
        day = timestamp.strftime('%A')
        confidence_band = self._get_confidence_band(confidence)
        slippage = abs(our_entry_price - whale_entry_price) / whale_entry_price if whale_entry_price > 0 else 0
        was_win = outcome == 'WIN'

        # Create trade record
        trade = {
            'timestamp': timestamp.isoformat(),
            'whale_address': whale_address,
            'market': market,
            'market_type': market_type,
            'confidence': confidence,
            'confidence_band': confidence_band,
            'position_size': position_size,
            'whale_entry_price': whale_entry_price,
            'our_entry_price': our_entry_price,
            'slippage_pct': round(slippage * 100, 3),
            'detection_delay_ms': detection_delay_ms,
            'outcome': outcome,
            'profit': profit,
            'kelly_recommendation': kelly_recommendation,
            'whale_win_rate': whale_win_rate,
            'hour': hour,
            'day': day,
            'extra': extra_data or {}
        }

        self.data['trades'].append(trade)

        # Update whale stats
        whale_stats = self.data['whale_stats'][whale_address]
        whale_stats['trades'].append(trade)
        if was_win:
            whale_stats['wins'] += 1
        else:
            whale_stats['losses'] += 1
        whale_stats['total_profit'] += profit

        # By market type
        mt_stats = whale_stats['by_market_type'][market_type]
        if was_win:
            mt_stats['wins'] += 1
        else:
            mt_stats['losses'] += 1
        mt_stats['profit'] += profit

        # By hour
        hour_stats = whale_stats['by_hour'][str(hour)]
        if was_win:
            hour_stats['wins'] += 1
        else:
            hour_stats['losses'] += 1

        # By day
        day_stats = whale_stats['by_day'][day]
        if was_win:
            day_stats['wins'] += 1
        else:
            day_stats['losses'] += 1

        # By confidence
        conf_stats = whale_stats['by_confidence'][confidence_band]
        if was_win:
            conf_stats['wins'] += 1
        else:
            conf_stats['losses'] += 1

        # Streak tracking
        self._update_streak(whale_stats, was_win)

        # Update market stats
        market_stats = self.data['market_stats'][market_type]
        market_stats['trades'] += 1
        if was_win:
            market_stats['wins'] += 1
        else:
            market_stats['losses'] += 1
        market_stats['profit'] += profit

        # Update timing stats
        self.data['timing_stats']['by_hour'][str(hour)]['trades'] += 1
        if was_win:
            self.data['timing_stats']['by_hour'][str(hour)]['wins'] += 1
        else:
            self.data['timing_stats']['by_hour'][str(hour)]['losses'] += 1

        self.data['timing_stats']['by_day'][day]['trades'] += 1
        if was_win:
            self.data['timing_stats']['by_day'][day]['wins'] += 1
        else:
            self.data['timing_stats']['by_day'][day]['losses'] += 1

        # Update confidence calibration
        self.data['confidence_calibration'][confidence_band]['total'] += 1
        self.data['confidence_calibration'][confidence_band]['predicted_wins'] += confidence / 100
        if was_win:
            self.data['confidence_calibration'][confidence_band]['actual_wins'] += 1

        # Update execution stats
        self.data['execution_stats']['slippage'].append(slippage * 100)
        self.data['execution_stats']['detection_delays'].append(detection_delay_ms)
        self.data['execution_stats']['by_market_type'][market_type]['slippage'].append(slippage * 100)
        self.data['execution_stats']['by_market_type'][market_type]['delays'].append(detection_delay_ms)

        # Update Kelly stats
        if kelly_recommendation:
            self.data['kelly_stats']['recommendations'].append(kelly_recommendation)
            self.data['kelly_stats']['actual_sizes'].append(position_size)
            self.data['kelly_stats']['outcomes'].append(1 if was_win else 0)

        # Auto-save
        self._save_data()

        return trade

    def record_edge_case(self, event_type: str, description: str, impact: str, data: Dict = None):
        """Record unusual events and edge cases"""
        self.data['edge_cases'].append({
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'description': description,
            'impact': impact,
            'data': data or {}
        })
        self._save_data()

    def _get_confidence_band(self, confidence: float) -> str:
        """Get confidence band label"""
        if confidence >= 96:
            return '96-100%'
        elif confidence >= 93:
            return '93-95%'
        elif confidence >= 90:
            return '90-92%'
        elif confidence >= 85:
            return '85-89%'
        else:
            return '<85%'

    def _update_streak(self, whale_stats: Dict, was_win: bool):
        """Update streak tracking for whale"""
        current = whale_stats['streaks']['current']

        # Record performance based on prior streak
        if len(whale_stats['trades']) > 1:
            if current >= 2:
                whale_stats['streaks']['after_wins'].append(1 if was_win else 0)
            elif current <= -2:
                whale_stats['streaks']['after_losses'].append(1 if was_win else 0)

        # Update current streak
        if was_win:
            if current >= 0:
                whale_stats['streaks']['current'] = current + 1
            else:
                whale_stats['streaks']['current'] = 1
        else:
            if current <= 0:
                whale_stats['streaks']['current'] = current - 1
            else:
                whale_stats['streaks']['current'] = -1

    def get_whale_report(self, whale_address: str) -> str:
        """Generate detailed report for a specific whale"""
        stats = self.data['whale_stats'].get(whale_address, {})
        if not stats or not stats.get('trades'):
            return f"No data for whale {whale_address[:10]}..."

        total = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        avg_profit = stats['total_profit'] / total if total > 0 else 0

        report = f"""
WHALE: {whale_address[:10]}...{whale_address[-4:]}
{'='*60}
Overall:
- Copied: {total} trades
- Wins: {stats['wins']} ({win_rate:.1f}%)
- Losses: {stats['losses']}
- Avg profit: ${avg_profit:.2f}/trade
- Total: ${stats['total_profit']:.2f}

Market Breakdown:"""

        for mt, mt_stats in stats['by_market_type'].items():
            mt_total = mt_stats['wins'] + mt_stats['losses']
            mt_wr = mt_stats['wins'] / mt_total * 100 if mt_total > 0 else 0
            star = "⭐" if mt_wr >= 75 else "⚠️" if mt_wr < 65 else ""
            report += f"\n- {mt}: {mt_total} trades, {mt_wr:.0f}% win {star}"

        # Best/worst hours
        best_hour = None
        best_hour_wr = 0
        worst_hour = None
        worst_hour_wr = 100

        for hour, h_stats in stats['by_hour'].items():
            h_total = h_stats['wins'] + h_stats['losses']
            if h_total >= 2:
                h_wr = h_stats['wins'] / h_total * 100
                if h_wr > best_hour_wr:
                    best_hour = hour
                    best_hour_wr = h_wr
                if h_wr < worst_hour_wr:
                    worst_hour = hour
                    worst_hour_wr = h_wr

        report += f"""

Timing Patterns:
- Best hour: {best_hour}:00 ({best_hour_wr:.0f}% win)
- Worst hour: {worst_hour}:00 ({worst_hour_wr:.0f}% win)"""

        # Best/worst days
        best_day = None
        best_day_wr = 0
        for day, d_stats in stats['by_day'].items():
            d_total = d_stats['wins'] + d_stats['losses']
            if d_total >= 2:
                d_wr = d_stats['wins'] / d_total * 100
                if d_wr > best_day_wr:
                    best_day = day
                    best_day_wr = d_wr

        if best_day:
            report += f"\n- Best day: {best_day} ({best_day_wr:.0f}% win)"

        # Confidence analysis
        report += "\n\nConfidence Analysis:"
        for band, c_stats in sorted(stats['by_confidence'].items()):
            c_total = c_stats['wins'] + c_stats['losses']
            if c_total > 0:
                c_wr = c_stats['wins'] / c_total * 100
                status = "✅" if c_wr >= 70 else "❌"
                report += f"\n- {band}: {c_total} trades, {c_wr:.0f}% win {status}"

        # Streak behavior
        after_wins = stats['streaks']['after_wins']
        after_losses = stats['streaks']['after_losses']

        if len(after_wins) >= 3:
            aw_wr = sum(after_wins) / len(after_wins) * 100
            report += f"\n\nStreak Behavior:"
            report += f"\n- After 2+ wins: {aw_wr:.0f}% win rate"

        if len(after_losses) >= 3:
            al_wr = sum(after_losses) / len(after_losses) * 100
            report += f"\n- After 2+ losses: {al_wr:.0f}% win rate"
            if al_wr < 50:
                report += " (goes cold!)"

        return report

    def get_market_report(self) -> str:
        """Generate market type performance report"""
        report = """
MARKET TYPE PERFORMANCE
{'='*60}"""

        sorted_markets = sorted(
            self.data['market_stats'].items(),
            key=lambda x: x[1]['profit'],
            reverse=True
        )

        for market_type, stats in sorted_markets:
            if stats['trades'] == 0:
                continue

            win_rate = stats['wins'] / stats['trades'] * 100
            avg_profit = stats['profit'] / stats['trades']

            if win_rate >= 75:
                verdict = "⭐ PRIORITIZE"
            elif win_rate >= 68:
                verdict = "✅ GOOD"
            elif win_rate >= 60:
                verdict = "⚠️ CAREFUL"
            else:
                verdict = "❌ SKIP"

            report += f"""
{market_type}:
- Trades: {stats['trades']}
- Win rate: {win_rate:.0f}%
- Avg profit: ${avg_profit:.2f}
- Total: ${stats['profit']:.2f}
- VERDICT: {verdict}
"""

        return report

    def get_timing_report(self) -> str:
        """Generate timing analysis report"""
        report = """
TIMING ANALYSIS
{'='*60}

Best Trading Hours:"""

        # Sort hours by win rate
        hour_data = []
        for hour, stats in self.data['timing_stats']['by_hour'].items():
            if stats['trades'] >= 3:
                wr = stats['wins'] / stats['trades'] * 100
                hour_data.append((int(hour), wr, stats['trades']))

        hour_data.sort(key=lambda x: x[1], reverse=True)

        for i, (hour, wr, trades) in enumerate(hour_data[:3], 1):
            report += f"\n{i}. {hour}:00-{hour+1}:00 → {wr:.0f}% win rate ({trades} trades)"

        report += "\n\nWorst Trading Hours:"
        for i, (hour, wr, trades) in enumerate(hour_data[-3:], 1):
            report += f"\n{i}. {hour}:00-{hour+1}:00 → {wr:.0f}% win rate ({trades} trades)"

        # Day performance
        report += "\n\nDay Performance:"
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

        for day in day_order:
            stats = self.data['timing_stats']['by_day'].get(day, {})
            if stats.get('trades', 0) > 0:
                wr = stats['wins'] / stats['trades'] * 100
                report += f"\n{day}: {wr:.0f}%"

        return report

    def get_confidence_calibration_report(self) -> str:
        """Generate confidence calibration report"""
        report = """
CONFIDENCE CALIBRATION
{'='*60}"""

        for band in ['<85%', '85-89%', '90-92%', '93-95%', '96-100%']:
            stats = self.data['confidence_calibration'].get(band, {})
            total = stats.get('total', 0)
            if total == 0:
                continue

            predicted = stats.get('predicted_wins', 0) / total * 100
            actual = stats.get('actual_wins', 0) / total * 100
            diff = actual - predicted

            if abs(diff) <= 5:
                status = "✅ CALIBRATED"
            elif diff < -10:
                status = "❌ OVERCONFIDENT"
            elif diff > 10:
                status = "⚠️ UNDERCONFIDENT"
            else:
                status = "⚠️ OFF"

            report += f"""
Confidence {band}:
- Expected: {predicted:.0f}% win
- Actual: {actual:.0f}% win
- Calibration: {diff:+.0f} points
- Status: {status}
"""

        return report

    def get_execution_report(self) -> str:
        """Generate execution quality report"""
        slippage = self.data['execution_stats']['slippage']
        delays = self.data['execution_stats']['detection_delays']

        if not slippage:
            return "No execution data yet"

        avg_slippage = sum(slippage) / len(slippage)
        avg_delay = sum(delays) / len(delays) if delays else 0

        report = f"""
EXECUTION ANALYSIS
{'='*60}

Average Metrics:
- Detection delay: {avg_delay:.0f}ms ({avg_delay/1000:.1f}s)
- Price slippage: {avg_slippage:.2f}%
- Best slippage: {min(slippage):.2f}%
- Worst slippage: {max(slippage):.2f}%

Slippage by Market Type:"""

        for mt, mt_stats in self.data['execution_stats']['by_market_type'].items():
            if mt_stats['slippage']:
                mt_avg = sum(mt_stats['slippage']) / len(mt_stats['slippage'])
                report += f"\n- {mt}: {mt_avg:.2f}%"

        return report

    def get_daily_summary(self) -> str:
        """Generate today's summary"""
        today = datetime.now().date()
        today_trades = [t for t in self.data['trades']
                       if datetime.fromisoformat(t['timestamp']).date() == today]

        if not today_trades:
            return "No trades today"

        wins = sum(1 for t in today_trades if t['outcome'] == 'WIN')
        losses = len(today_trades) - wins
        profit = sum(t['profit'] for t in today_trades)
        win_rate = wins / len(today_trades) * 100

        # Best performer
        whale_profits = defaultdict(float)
        for t in today_trades:
            whale_profits[t['whale_address']] += t['profit']

        best_whale = max(whale_profits.items(), key=lambda x: x[1]) if whale_profits else (None, 0)

        report = f"""
DRY RUN DAY SUMMARY - {today}
{'='*60}
Trades: {len(today_trades)}
Wins: {wins} ({win_rate:.1f}%)
Losses: {losses}
Profit: ${profit:.2f}

Best Performer: {best_whale[0][:10] if best_whale[0] else 'N/A'}... (+${best_whale[1]:.2f})
"""

        return report

    def get_weekly_report(self) -> str:
        """Generate comprehensive weekly report"""
        all_trades = self.data['trades']
        if not all_trades:
            return "No trades recorded"

        total_profit = sum(t['profit'] for t in all_trades)
        wins = sum(1 for t in all_trades if t['outcome'] == 'WIN')
        losses = len(all_trades) - wins
        win_rate = wins / len(all_trades) * 100 if all_trades else 0

        report = f"""
{'='*70}
DRY RUN WEEKLY REPORT
{'='*70}

OVERALL PERFORMANCE:
Trades: {len(all_trades)}
Win Rate: {win_rate:.1f}%
Total Profit: ${total_profit:.2f}

{'='*70}
TOP PERFORMING WHALES:
{'='*70}"""

        # Rank whales
        whale_perf = []
        for addr, stats in self.data['whale_stats'].items():
            total = stats['wins'] + stats['losses']
            if total >= 3:
                wr = stats['wins'] / total * 100
                whale_perf.append((addr, wr, stats['total_profit'], total))

        whale_perf.sort(key=lambda x: x[2], reverse=True)

        for i, (addr, wr, profit, trades) in enumerate(whale_perf[:5], 1):
            report += f"\n{i}. {addr[:10]}...: {wr:.0f}% wins, ${profit:.2f}"

        report += f"""

{'='*70}
BOTTOM PERFORMING WHALES (Consider Removing):
{'='*70}"""

        for i, (addr, wr, profit, trades) in enumerate(whale_perf[-5:], 1):
            report += f"\n{i}. {addr[:10]}...: {wr:.0f}% wins, ${profit:.2f}"

        # Add other reports
        report += "\n" + self.get_market_report()
        report += "\n" + self.get_timing_report()
        report += "\n" + self.get_confidence_calibration_report()
        report += "\n" + self.get_execution_report()

        # Action items
        report += f"""

{'='*70}
RECOMMENDED ACTIONS FOR LIVE TRADING:
{'='*70}
"""
        # Generate recommendations based on data
        recommendations = self._generate_recommendations()
        for i, rec in enumerate(recommendations, 1):
            report += f"\n{i}. {rec}"

        return report

    def _generate_recommendations(self) -> List[str]:
        """Generate actionable recommendations"""
        recs = []

        # Check confidence calibration
        for band, stats in self.data['confidence_calibration'].items():
            if stats.get('total', 0) >= 5:
                predicted = stats['predicted_wins'] / stats['total'] * 100
                actual = stats['actual_wins'] / stats['total'] * 100
                if actual < predicted - 15:
                    recs.append(f"Increase confidence threshold (currently overconfident at {band})")
                    break

        # Check market performance
        for mt, stats in self.data['market_stats'].items():
            if stats['trades'] >= 5:
                wr = stats['wins'] / stats['trades'] * 100
                if wr < 60:
                    recs.append(f"Consider skipping {mt} markets ({wr:.0f}% win rate)")

        # Check timing
        worst_hours = []
        for hour, stats in self.data['timing_stats']['by_hour'].items():
            if stats['trades'] >= 3:
                wr = stats['wins'] / stats['trades'] * 100
                if wr < 55:
                    worst_hours.append(f"{hour}:00")

        if worst_hours:
            recs.append(f"Reduce trading during: {', '.join(worst_hours[:3])}")

        # Check whale performance
        for addr, stats in self.data['whale_stats'].items():
            total = stats['wins'] + stats['losses']
            if total >= 5 and stats['wins'] / total < 0.55:
                recs.append(f"Consider removing whale {addr[:10]}... (underperforming)")
                break

        if not recs:
            recs.append("No critical issues detected - system performing well")

        return recs


# Singleton instance
_analytics = None

def get_analytics() -> DryRunAnalytics:
    """Get or create analytics instance"""
    global _analytics
    if _analytics is None:
        _analytics = DryRunAnalytics()
    return _analytics


if __name__ == "__main__":
    # Demo
    analytics = DryRunAnalytics()

    # Simulate some trades
    analytics.record_trade(
        whale_address="0x1234567890abcdef1234567890abcdef12345678",
        market="BTC Up or Down - 15 min",
        market_type="BTC 15-min",
        confidence=94.5,
        position_size=8.50,
        whale_entry_price=0.65,
        our_entry_price=0.66,
        detection_delay_ms=2800,
        outcome="WIN",
        profit=3.40,
        kelly_recommendation=9.0,
        whale_win_rate=0.73
    )

    analytics.record_trade(
        whale_address="0x1234567890abcdef1234567890abcdef12345678",
        market="ETH Up or Down - 15 min",
        market_type="ETH 15-min",
        confidence=91.2,
        position_size=6.00,
        whale_entry_price=0.58,
        our_entry_price=0.59,
        detection_delay_ms=3200,
        outcome="LOSS",
        profit=-6.00,
        kelly_recommendation=7.0,
        whale_win_rate=0.73
    )

    print(analytics.get_daily_summary())
    print(analytics.get_whale_report("0x1234567890abcdef1234567890abcdef12345678"))
