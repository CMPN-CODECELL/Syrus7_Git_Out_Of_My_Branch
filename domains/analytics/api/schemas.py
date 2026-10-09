"""
File Overview: Pydantic response models and schemas for the analytics API.

All Functions/Classes:
- ResponseMetadata: Base schema for all API responses. Take status/source and send to validated JSON response.
- MarketDataResponse: Stores price and volume metrics. Take raw data and send to validated object.
- OptionsSummaryResponse: Stores PCR and option volume/OI stats. Take calculation results and send to validated object.
- DerivativesResponse: Final unified response schema. Take all analytical components and send to client.
- SymbolsResponse: Returns recommended symbols. Take list from settings and send to client.
- ErrorEnvelope: Standardized error response. Take error details and send to validated error object.

Endpoints/APIs:
- Definition layer for all /v1/ analytics endpoints.

Database Tables:
- None.
"""
from typing import Optional


from pydantic import BaseModel, Field


class ResponseMetadata(BaseModel):
    generated_at: str = ""
    source: str = ""
    stale: bool = True
    partial: bool = True
    status: str = "COMPLETED"  # COMPLETED, CALCULATING, FAILED


# ── Market Data ─────────────────────────────────────────────────

class MarketDataResponse(BaseModel):
    last_price: float
    open: float
    high: float
    low: float
    volume: int
    previous_close: float
    change_percent: float
    currency: str = "INR"
    market_status: str
    last_updated: str


# ── Options Summary ────────────────────────────────────────────

class OptionTick(BaseModel):
    strike: float
    type: str  # CE/PE
    last_price: float
    iv: float
    oi: int
    volume: int
    expiry: str

class OptionsSummaryResponse(BaseModel):
    pcr: float = 0.0
    ce_volume: int = 0
    pe_volume: int = 0
    ce_oi: int = 0
    pe_oi: int = 0
    total_strikes: int = 0
    expiry_dates: list[str] = Field(default_factory=list)
    chain: list[OptionTick] = Field(default_factory=list)
    available: bool = False
    last_updated: str = ""


# ── Derivatives Response ────────────────────────────────────────

class PricedStrike(BaseModel):
    strike: float
    fair_call: float
    fair_put: float
    call_iv: float
    put_iv: float
    bs_fair_call: Optional[float] = None
    bs_fair_put: Optional[float] = None
    live_call: Optional[float] = None
    live_put: Optional[float] = None


class DerivativesResponse(ResponseMetadata):
    symbol: str
    pcr: float = 0.0
    ce_volume: int = 0
    pe_volume: int = 0
    ce_oi: int = 0
    pe_oi: int = 0
    total_strikes: int = 0
    expiry_dates: list[str] = Field(default_factory=list)
    fair_priced_chain: list[PricedStrike] = Field(default_factory=list)
    available: bool = False
    last_updated: str = ""


# ── Symbols Response ───────────────────────────────────────────

class SymbolsResponse(ResponseMetadata):
    symbols: list[str] = Field(default_factory=list)
    count: int


class SymbolSearchItem(BaseModel):
    symbol: str
    name: str
    type: str


class SymbolSearchResponse(ResponseMetadata):
    results: list[SymbolSearchItem] = Field(default_factory=list)
    count: int



# ── Error Envelope ──────────────────────────────────────────────

class ErrorEnvelope(ResponseMetadata):
    error: str
    code: str
    details: dict | list[dict] | None = None


# ── Option Pricer Schemas ────────────────────────────────────────

class OptionChainSide(BaseModel):
    oi: Optional[int] = 0
    chng_in_oi: Optional[int] = 0
    volume: Optional[int] = 0
    iv: Optional[float] = 0.0
    ltp: Optional[float] = 0.0
    chng: Optional[float] = 0.0
    bid_qty: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    ask_qty: Optional[int] = None


class OptionChainRow(BaseModel):
    strike_price: float
    call: OptionChainSide
    put: OptionChainSide


class PricerTickerDataResponse(ResponseMetadata):
    symbol: str
    stock_price: float
    implied_volatility: Optional[float] = 0.0
    historical_volatility: Optional[float] = 0.0
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    open_interest: int = 0
    volume: int = 0
    strike_price: float = 0.0
    expiry_days: int = 0
    risk_free_rate: float = 6.5
    dividend_yield: float = 0.0
    expiry_dates: list[str] = Field(default_factory=list)
    option_chains: dict[str, list[OptionChainRow]] = Field(default_factory=dict)



class BSMCalculateRequest(BaseModel):
    S0: float = Field(..., description="Stock price")
    K: float = Field(..., description="Strike price")
    T_days: int = Field(..., description="Expiry in days")
    r: float = Field(..., description="Risk-free interest rate (percentage, e.g. 5.25)")
    sigma: float = Field(..., description="Volatility (percentage, e.g. 28.4)")
    option_type: str = Field(..., description="'call' or 'put'")
    q: float = Field(0.0, description="Dividend yield (percentage, e.g. 0.55)")
    market_mid: Optional[float] = Field(None, description="Current market midpoint price of option")


class BSMCalculateResponse(BaseModel):
    S0: float
    K: float
    T_years: float
    r: float
    sigma: float
    option_type: str
    q: float
    d1: float
    d2: float
    Nd1: float
    Nd2: float
    fair_value: float
    market_mid: Optional[float] = None
    edge: Optional[float] = None


# ── Technicals Response Schemas ─────────────────────────────────

class IndicatorSignal(BaseModel):
    value: Optional[float] = None
    macd: Optional[float] = None
    signal_line: Optional[float] = None
    histogram: Optional[float] = None
    upper: Optional[float] = None
    middle: Optional[float] = None
    lower: Optional[float] = None
    signal: str
    label: str


class MovingAverageItem(BaseModel):
    name: str
    value: float
    signal: str


class PivotsData(BaseModel):
    p: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float


class TechnicalsSummary(BaseModel):
    overall_signal: str
    overall_badge: str
    bullish_count: int
    bearish_count: int
    neutral_count: int
    total_indicators: int


class TechnicalsResponse(ResponseMetadata):
    symbol: str
    spot_price: float
    summary: TechnicalsSummary
    rsi: IndicatorSignal
    macd: IndicatorSignal
    bollinger: IndicatorSignal
    moving_averages: list[MovingAverageItem]
    atr: float
    pivots: PivotsData

