"""
Claude AI Trade Validator
Uses Anthropic Claude to analyze and validate whale trades before copying
"""

import anthropic
import json
from datetime import datetime
from colorama import Fore, init

import config

init(autoreset=True)


class ClaudeTradeValidator:
    """
    Use Claude AI to analyze whale trades and provide confidence scoring

    This adds an extra layer of intelligence to the copy trading system
    by having Claude analyze:
    - Market conditions
    - Trade timing
    - Risk factors
    - Historical patterns
    """

    def __init__(self, force_disable=True):
        self.enabled = False
        self.client = None

        # For 15-min markets with small capital, speed > AI accuracy
        # Set force_disable=False to enable Claude AI validation
        if force_disable:
            print(f"{Fore.CYAN}Claude AI disabled (speed mode for 15-min markets)")
            return

        if config.ANTHROPIC_API_KEY and config.ANTHROPIC_API_KEY != 'your_anthropic_key_here':
            try:
                self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
                self.enabled = True
                print(f"{Fore.GREEN}Claude AI validator initialized")
            except Exception as e:
                print(f"{Fore.YELLOW}Claude AI disabled: {e}")
        else:
            print(f"{Fore.YELLOW}Claude AI disabled - no API key")

        # Track validations for analysis
        self.validation_history = []

    async def validate_trade(self, trade_data, base_confidence):
        """
        Use Claude to analyze a trade and adjust confidence

        Args:
            trade_data: Dict with trade details
            base_confidence: Initial confidence score (0-100)

        Returns:
            Dict with AI analysis and adjusted confidence
        """

        if not self.enabled:
            return {
                'final_confidence': base_confidence,
                'ai_confidence_boost': 0,
                'reasoning': 'AI validation disabled',
                'concerns': [],
                'recommendation': 'PROCEED' if base_confidence >= 80 else 'SKIP'
            }

        try:
            # Build prompt for Claude
            prompt = self._build_analysis_prompt(trade_data, base_confidence)

            # Call Claude
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Parse response
            response_text = message.content[0].text
            result = self._parse_response(response_text, base_confidence)

            return result

        except Exception as e:
            print(f"{Fore.RED}Claude validation error: {e}")
            return {
                'final_confidence': base_confidence,
                'ai_confidence_boost': 0,
                'reasoning': f'AI error: {str(e)[:50]}',
                'concerns': ['AI validation failed'],
                'recommendation': 'PROCEED' if base_confidence >= 85 else 'SKIP'
            }

    def _build_analysis_prompt(self, trade_data, base_confidence):
        """Build the prompt for Claude analysis"""

        return f"""Analyze this Polymarket whale trade for copy-trading suitability.

TRADE DETAILS:
- Whale: {trade_data.get('whale_address', 'Unknown')[:12]}...
- Side: {trade_data.get('side', 'Unknown')}
- Price: ${trade_data.get('price', 0):.4f}
- Size: ${trade_data.get('usdc_value', 0):.2f}
- Market: {trade_data.get('market_question', 'Unknown')}
- Base confidence: {base_confidence}%

CONTEXT:
This is a 15-minute prediction market (resolves in 15 min).
We have $100 capital and want high-confidence trades only.

ANALYZE:
1. Is this a good trade to copy? Consider timing, price, market type.
2. What's the confidence adjustment? (-20 to +20 points)
3. Any concerns?

RESPOND IN THIS EXACT FORMAT:
CONFIDENCE_ADJUSTMENT: [number between -20 and +20]
REASONING: [one sentence]
CONCERNS: [comma-separated list or "none"]
RECOMMENDATION: [COPY or SKIP]"""

    def _parse_response(self, response_text, base_confidence):
        """Parse Claude's response into structured data"""

        try:
            lines = response_text.strip().split('\n')

            adjustment = 0
            reasoning = "AI analysis complete"
            concerns = []
            recommendation = "PROCEED"

            for line in lines:
                line = line.strip()

                if line.startswith('CONFIDENCE_ADJUSTMENT:'):
                    try:
                        adj_str = line.split(':')[1].strip()
                        adjustment = int(float(adj_str))
                        adjustment = max(-20, min(20, adjustment))
                    except:
                        pass

                elif line.startswith('REASONING:'):
                    reasoning = line.split(':', 1)[1].strip()

                elif line.startswith('CONCERNS:'):
                    concern_str = line.split(':', 1)[1].strip()
                    if concern_str.lower() != 'none':
                        concerns = [c.strip() for c in concern_str.split(',')]

                elif line.startswith('RECOMMENDATION:'):
                    rec = line.split(':')[1].strip().upper()
                    recommendation = 'COPY' if 'COPY' in rec else 'SKIP'

            final_confidence = base_confidence + adjustment
            final_confidence = max(0, min(100, final_confidence))

            return {
                'final_confidence': final_confidence,
                'ai_confidence_boost': adjustment,
                'reasoning': reasoning,
                'concerns': concerns,
                'recommendation': recommendation
            }

        except Exception as e:
            return {
                'final_confidence': base_confidence,
                'ai_confidence_boost': 0,
                'reasoning': f'Parse error: {str(e)[:30]}',
                'concerns': ['Could not parse AI response'],
                'recommendation': 'PROCEED' if base_confidence >= 85 else 'SKIP'
            }

    def log_validation(self, trade_data, result):
        """Log validation for later analysis"""

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'whale': trade_data.get('whale_address', '')[:12],
            'side': trade_data.get('side', ''),
            'price': trade_data.get('price', 0),
            'ai_adjustment': result.get('ai_confidence_boost', 0),
            'final_confidence': result.get('final_confidence', 0),
            'recommendation': result.get('recommendation', ''),
            'concerns': result.get('concerns', [])
        }

        self.validation_history.append(log_entry)

        # Save to file
        try:
            with open('claude_validations.jsonl', 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception:
            pass


if __name__ == "__main__":
    # Test the validator
    import asyncio

    validator = ClaudeTradeValidator()

    test_trade = {
        'whale_address': '0x1234567890abcdef1234567890abcdef12345678',
        'side': 'BUY',
        'price': 0.52,
        'usdc_value': 500,
        'market_question': 'Will BTC be above $98,000 at 6:00 PM?'
    }

    async def test():
        result = await validator.validate_trade(test_trade, 85)
        print(f"\nResult:")
        print(json.dumps(result, indent=2))

    asyncio.run(test())
