import logging
from typing import List, Dict, Any, Optional
from domains.copilot.domain.entities import (
    TradeIntent, ReasoningOutput, RecommendationDecision, GoldenZone, InstrumentType
)
from domains.analytics.domain.services.bsm_calculator import BsmCalculatorDomainService
from domains.analytics.domain.services.technical_indicators_engine import TechnicalIndicatorsEngine

logger = logging.getLogger(__name__)

class CopilotReasoningEngine:
    """
    Acts as the math-based reasoning layer (Derivatives RAG) for the AI Trading Copilot.
    The LLM extracts user intent and passes it here. This engine uses quantitative 
    models to determine if the trade should be executed now, or if a 'Golden Zone' 
    (optimal limit entry) should be proposed to the user.
    """

    def __init__(self, market_data_provider=None):
        # In a real system, this would fetch live prices from the Ingestion domain.
        self.market_data_provider = market_data_provider

    def evaluate_intent(self, intent: TradeIntent, market_context: Dict[str, Any]) -> ReasoningOutput:
        """
        Evaluates the extracted LLM intent against math/derivative models.
        """
        logger.info(f"Evaluating trade intent for {intent.symbol}...")

        if intent.instrument_type == InstrumentType.OPTION or intent.is_options_trade:
            return self._evaluate_option_intent(intent, market_context)
        else:
            return self._evaluate_equity_intent(intent, market_context)

    def _evaluate_equity_intent(self, intent: TradeIntent, context: Dict[str, Any]) -> ReasoningOutput:
        """
        Uses Technical Indicators to find the golden zone for an equity trade.
        """
        current_price = context.get("current_price", 0.0)
        recent_closes = context.get("recent_closes", [])
        
        if not recent_closes or current_price == 0.0:
            return self._fallback_market_order(intent, current_price, "Insufficient market history for technical analysis.")

        # Compute Technicals
        rsi = TechnicalIndicatorsEngine.calculate_rsi(recent_closes)
        bb = TechnicalIndicatorsEngine.calculate_bollinger_bands(recent_closes)
        
        golden_zone = None
        decision = RecommendationDecision.EXECUTE_NOW
        summary = "Technical conditions are neutral. Executing at market."
        
        if rsi is not None and bb.get("lower") is not None and bb.get("upper") is not None:
            if intent.action == "BUY":
                if rsi < 30 or current_price <= bb["lower"]:
                    summary = f"Stock is oversold (RSI: {rsi}). Excellent entry point right now."
                    decision = RecommendationDecision.EXECUTE_NOW
                else:
                    # Recommend waiting for a pullback to the lower Bollinger Band
                    decision = RecommendationDecision.WAIT_FOR_ZONE
                    zone_low = bb["lower"] * 0.99
                    zone_high = bb["lower"] * 1.01
                    summary = f"Stock is not in an optimal buy zone (RSI: {rsi}). Recommending a limit order in the Golden Zone."
                    golden_zone = GoldenZone(
                        price_low=round(zone_low, 2),
                        price_high=round(zone_high, 2),
                        technical_justification=f"Lower Bollinger Band support at {round(bb['lower'], 2)}."
                    )
            elif intent.action == "SELL":
                if rsi > 70 or current_price >= bb["upper"]:
                    summary = f"Stock is overbought (RSI: {rsi}). Good exit point."
                    decision = RecommendationDecision.EXECUTE_NOW
                else:
                    decision = RecommendationDecision.WAIT_FOR_ZONE
                    golden_zone = GoldenZone(
                        price_low=round(bb["upper"] * 0.99, 2),
                        price_high=round(bb["upper"] * 1.01, 2),
                        technical_justification=f"Upper Bollinger Band resistance at {round(bb['upper'], 2)}."
                    )

        payload = self._build_order_payload(intent, current_price, golden_zone)
        
        return ReasoningOutput(
            original_intent=intent,
            decision=decision,
            golden_zone=golden_zone,
            current_market_price=current_price,
            human_readable_summary=summary,
            proposed_order_payload=payload
        )

    def _evaluate_option_intent(self, intent: TradeIntent, context: Dict[str, Any]) -> ReasoningOutput:
        """
        Uses Black-Scholes-Merton and Greeks to find optimal options trades.
        """
        spot = context.get("spot_price", 0.0)
        strike = context.get("strike", spot) # Default to ATM
        expiry = context.get("expiry_years", 30 / 365.0) # Default 30 DTE
        vol = context.get("implied_volatility", 0.20)
        rate = 0.05
        
        if spot <= 0.0:
            return self._fallback_market_order(intent, 0.0, "Missing spot price for options calculation.")

        opt_type = "call" if intent.action == "BUY" else "put"
        
        # Calculate theoretical price and Greeks
        greeks = BsmCalculatorDomainService.calculate_greeks(spot, strike, expiry, rate, vol, opt_type)
        theo_price = BsmCalculatorDomainService.calculate_price(spot, strike, expiry, rate, vol, opt_type)
        
        market_price = context.get("option_market_price", theo_price)
        
        summary = f"Calculated Greeks -> Delta: {greeks.delta:.2f}, Gamma: {greeks.gamma:.4f}, Vega: {greeks.vega:.2f}."
        decision = RecommendationDecision.EXECUTE_NOW
        golden_zone = None
        
        # Simple RAG reasoning: 
        # If market price is significantly higher than theoretical price, don't buy immediately.
        if intent.action == "BUY" and market_price > theo_price * 1.05:
            decision = RecommendationDecision.WAIT_FOR_ZONE
            golden_zone = GoldenZone(
                price_low=theo_price * 0.95,
                price_high=theo_price * 1.05,
                greeks_justification=f"Option is overpriced. Theoretical value is {theo_price:.2f} (IV: {vol*100:.1f}%). "
                                     f"Wait for IV crush or pullback to fair value."
            )
            summary += f" Option is trading at a premium. Recommend setting a limit order near fair value."
        else:
            summary += f" Option is fairly priced. Safe to execute at current levels."

        payload = self._build_order_payload(intent, market_price, golden_zone)

        return ReasoningOutput(
            original_intent=intent,
            decision=decision,
            golden_zone=golden_zone,
            current_market_price=market_price,
            human_readable_summary=summary,
            proposed_order_payload=payload
        )

    def _fallback_market_order(self, intent, price, reason) -> ReasoningOutput:
        payload = self._build_order_payload(intent, price, None)
        return ReasoningOutput(
            original_intent=intent,
            decision=RecommendationDecision.EXECUTE_NOW,
            current_market_price=price,
            human_readable_summary=reason,
            proposed_order_payload=payload
        )
        
    def _build_order_payload(self, intent: TradeIntent, current_price: float, zone: Optional[GoldenZone]) -> Dict[str, Any]:
        """
        Builds the proposed payload matching the 021 Trade API requirements.
        Prices are converted to paise (integer).
        """
        limit_price = current_price
        if zone is not None:
            # If there's a zone, default the limit order to the top of the buy zone or bottom of sell zone.
            limit_price = zone.price_high if intent.action == "BUY" else zone.price_low

        qty = intent.quantity if intent.quantity else 1
        qty_sign = 1 if intent.action == "BUY" else -1
        final_qty = qty * qty_sign

        return {
            "exchange": "NSE", 
            "token": 0, # To be resolved by instrument service
            "qty": final_qty,
            "price": int(limit_price * 100), # Paise
            "book": "RL" if zone else "RL", # RL = Regular Limit. 
            "product": "INTRADAY",
            "validity": "Day"
        }
