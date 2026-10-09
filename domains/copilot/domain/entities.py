from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

class IntentAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    ANALYZE = "ANALYZE"

class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"
    FUTURE = "FUTURE"

class RecommendationDecision(str, Enum):
    EXECUTE_NOW = "EXECUTE_NOW"
    WAIT_FOR_ZONE = "WAIT_FOR_ZONE"
    REJECT = "REJECT"

@dataclass
class TradeIntent:
    """The structured intent extracted by the LLM from natural language."""
    action: IntentAction
    symbol: str
    quantity: Optional[int] = None
    instrument_type: InstrumentType = InstrumentType.EQUITY
    target_price: Optional[float] = None
    time_horizon_days: Optional[int] = None
    is_options_trade: bool = False
    strike_preference: Optional[str] = None # ATM, ITM, OTM
    
@dataclass
class GoldenZone:
    """Optimal entry/exit zone recommended by the derivatives/technical reasoning layer."""
    price_low: float
    price_high: float
    optimal_time_window: Optional[str] = None
    technical_justification: str = ""
    greeks_justification: str = ""

@dataclass
class ReasoningOutput:
    """The final structured JSON output from the Reasoning Layer to show to the UI."""
    original_intent: TradeIntent
    decision: RecommendationDecision
    golden_zone: Optional[GoldenZone] = None
    current_market_price: Optional[float] = None
    estimated_cost: Optional[float] = None
    risk_score: float = 0.0 # 0.0 to 1.0
    human_readable_summary: str = ""
    proposed_order_payload: Optional[Dict[str, Any]] = None
