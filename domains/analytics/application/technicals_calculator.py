"""
File Overview: Technical Indicator Calculator Engine in Analytics Application Layer.

Computes technical indicators (RSI, MACD, Moving Averages, Bollinger Bands, ATR, Pivot Points)
and assigns color-coded signals (Bullish, Bearish, Neutral) along with a composite summary.
Delegates core mathematical computations to TechnicalIndicatorsEngine domain service.
"""

import math
from typing import List, Dict, Any

from domains.analytics.domain.services.technical_indicators_engine import (
    TechnicalIndicatorsEngine,
)


def calculate_rsi(prices: List[float], period: int = 14) -> Dict[str, Any]:
    """Calculate Relative Strength Index (RSI) using domain math engine."""
    val = TechnicalIndicatorsEngine.calculate_rsi(prices, period)
    if val is None:
        val = 50.0

    val = round(val, 2)
    if val >= 70:
        signal = "BEARISH"  # Overbought
        label = "Overbought"
    elif val >= 55:
        signal = "BULLISH"
        label = "Bullish"
    elif val <= 30:
        signal = "BULLISH"  # Oversold reversal potential
        label = "Oversold"
    elif val <= 45:
        signal = "BEARISH"
        label = "Bearish"
    else:
        signal = "NEUTRAL"
        label = "Neutral"

    return {"value": val, "signal": signal, "label": label}


def calculate_sma(prices: List[float], period: int) -> float:
    """Calculate Simple Moving Average."""
    if not prices or len(prices) < period:
        return prices[-1] if prices else 0.0
    return round(sum(prices[-period:]) / period, 2)


def calculate_ema(prices: List[float], period: int) -> float:
    """Calculate Exponential Moving Average."""
    if not prices:
        return 0.0
    if len(prices) < period:
        return calculate_sma(prices, len(prices))

    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price * k) + (ema * (1 - k))
    return round(ema, 2)


def calculate_macd(prices: List[float]) -> Dict[str, Any]:
    """Calculate MACD (12, 26, 9) using domain math engine."""
    macd_res = TechnicalIndicatorsEngine.calculate_macd(prices)
    macd_line = macd_res.get("macd")
    signal_line = macd_res.get("signal")
    histogram = macd_res.get("histogram")

    if macd_line is None:
        ema12 = calculate_ema(prices, 12)
        ema26 = calculate_ema(prices, 26)
        macd_line = round(ema12 - ema26, 2)
        signal_line = round(macd_line * 0.8, 2)
        histogram = round(macd_line - signal_line, 2)

    if histogram > 0 and macd_line > 0:
        signal = "BULLISH"
        label = "Strong Bullish"
    elif histogram > 0:
        signal = "BULLISH"
        label = "Bullish"
    elif histogram < 0 and macd_line < 0:
        signal = "BEARISH"
        label = "Strong Bearish"
    elif histogram < 0:
        signal = "BEARISH"
        label = "Bearish"
    else:
        signal = "NEUTRAL"
        label = "Neutral"

    return {
        "macd": macd_line,
        "signal_line": signal_line,
        "histogram": histogram,
        "signal": signal,
        "label": label,
    }


def calculate_bollinger_bands(
    prices: List[float], period: int = 20, num_std: float = 2.0
) -> Dict[str, Any]:
    """Calculate Bollinger Bands (20, 2) using domain math engine."""
    bb_res = TechnicalIndicatorsEngine.calculate_bollinger_bands(prices, period, num_std)
    upper = bb_res.get("upper")
    middle = bb_res.get("middle")
    lower = bb_res.get("lower")

    if upper is None or middle is None or lower is None:
        if not prices:
            return {"upper": 0, "middle": 0, "lower": 0, "signal": "NEUTRAL", "label": "Neutral"}
        middle = calculate_sma(prices, period)
        window = prices[-period:] if len(prices) >= period else prices
        variance = sum((x - middle) ** 2 for x in window) / max(len(window) - 1, 1)
        std_dev = math.sqrt(variance)
        upper = round(middle + (num_std * std_dev), 2)
        lower = round(middle - (num_std * std_dev), 2)

    current_price = prices[-1] if prices else 0.0

    if current_price >= upper:
        signal = "BEARISH"
        label = "Upper Band (Overbought)"
    elif current_price <= lower:
        signal = "BULLISH"
        label = "Lower Band (Oversold)"
    elif current_price > middle:
        signal = "BULLISH"
        label = "Above Middle Band"
    else:
        signal = "BEARISH"
        label = "Below Middle Band"

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "signal": signal,
        "label": label,
    }


def calculate_pivots(high: float, low: float, close: float) -> Dict[str, float]:
    """Calculate Classic Floor Pivot Points."""
    p = round((high + low + close) / 3.0, 2)
    r1 = round((2 * p) - low, 2)
    s1 = round((2 * p) - high, 2)
    r2 = round(p + (high - low), 2)
    s2 = round(p - (high - low), 2)
    r3 = round(high + 2 * (p - low), 2)
    s3 = round(low - 2 * (high - p), 2)
    return {"p": p, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3}


def compute_all_technicals(spot_price: float, price_history: List[float] = None) -> Dict[str, Any]:
    """Compute comprehensive technical analysis suite for spot price and price history."""
    estimated = False
    if not price_history or len(price_history) < 5:
        price_history = [spot_price]

    current_price = price_history[-1]

    # 1. Oscillators
    rsi_data = calculate_rsi(price_history)
    macd_data = calculate_macd(price_history)
    bb_data = calculate_bollinger_bands(price_history)

    # 2. Moving Averages
    sma20 = calculate_sma(price_history, 20)
    sma50 = calculate_sma(price_history, 50)
    ema20 = calculate_ema(price_history, 20)
    ema50 = calculate_ema(price_history, 50)

    ma_signals = [
        {"name": "SMA 20", "value": sma20, "signal": "BULLISH" if current_price >= sma20 else "BEARISH"},
        {"name": "SMA 50", "value": sma50, "signal": "BULLISH" if current_price >= sma50 else "BEARISH"},
        {"name": "EMA 20", "value": ema20, "signal": "BULLISH" if current_price >= ema20 else "BEARISH"},
        {"name": "EMA 50", "value": ema50, "signal": "BULLISH" if current_price >= ema50 else "BEARISH"},
    ]

    # 3. Volatility / ATR
    if price_history and len(price_history) >= 2:
        diffs = [abs(price_history[i] - price_history[i - 1]) for i in range(1, len(price_history))]
        atr = round(sum(diffs[-14:]) / min(len(diffs), 14), 2)
    else:
        atr = 0.0

    # 4. Pivot Points
    high = max(price_history[-15:]) if price_history else spot_price
    low = min(price_history[-15:]) if price_history else spot_price
    pivots = calculate_pivots(high, low, current_price)

    # 5. Composite Score & Overall Signal
    all_signals = [
        rsi_data["signal"],
        macd_data["signal"],
        bb_data["signal"],
    ] + [ma["signal"] for ma in ma_signals]

    bullish_count = all_signals.count("BULLISH")
    bearish_count = all_signals.count("BEARISH")
    neutral_count = all_signals.count("NEUTRAL")

    if bullish_count >= 5:
        overall_signal = "STRONG BULLISH"
        overall_badge = "BULLISH"
    elif bullish_count > bearish_count:
        overall_signal = "BULLISH"
        overall_badge = "BULLISH"
    elif bearish_count >= 5:
        overall_signal = "STRONG BEARISH"
        overall_badge = "BEARISH"
    elif bearish_count > bullish_count:
        overall_signal = "BEARISH"
        overall_badge = "BEARISH"
    else:
        overall_signal = "NEUTRAL"
        overall_badge = "NEUTRAL"

    return {
        "spot_price": current_price,
        "estimated": estimated,
        "summary": {
            "overall_signal": overall_signal,
            "overall_badge": overall_badge,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "neutral_count": neutral_count,
            "total_indicators": len(all_signals),
        },
        "rsi": rsi_data,
        "macd": macd_data,
        "bollinger": bb_data,
        "moving_averages": ma_signals,
        "atr": atr,
        "pivots": pivots,
    }


