"""
File Overview: Technical Indicators Engine calculating RSI, MACD, Bollinger Bands, and ATR from price series/OHLC data.
Vectorized domain service in analytics bounded context with zero synthetic or mock fallbacks.
"""
import numpy as np
from typing import Dict, List, Any, Optional


class TechnicalIndicatorsEngine:
    """Calculates quantitative technical indicators from price arrays or candle lists."""

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        if len(prices) < period + 1:
            return None

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(round(rsi, 2))

    @staticmethod
    def calculate_macd(
        prices: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Dict[str, Optional[float]]:
        if len(prices) < slow_period + signal_period:
            return {"macd": None, "signal": None, "histogram": None}

        prices_arr = np.array(prices, dtype=float)

        def _ema(data: np.ndarray, window: int) -> np.ndarray:
            alpha = 2.0 / (window + 1)
            ema = np.empty_like(data, dtype=float)
            ema[0] = data[0]
            for i in range(1, len(data)):
                ema[i] = alpha * data[i] + (1.0 - alpha) * ema[i - 1]
            return ema

        fast_ema = _ema(prices_arr, fast_period)
        slow_ema = _ema(prices_arr, slow_period)
        macd_line = fast_ema - slow_ema
        signal_line = _ema(macd_line, signal_period)
        histogram = macd_line - signal_line

        return {
            "macd": float(round(macd_line[-1], 4)),
            "signal": float(round(signal_line[-1], 4)),
            "histogram": float(round(histogram[-1], 4)),
        }

    @staticmethod
    def calculate_atr(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> Optional[float]:
        """Calculate Average True Range using standard Wilder / EMA smoothing."""
        if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
            return None

        trs: List[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

        if len(trs) < period:
            return None

        atr = float(np.mean(trs[:period]))
        for i in range(period, len(trs)):
            atr = (atr * (period - 1) + trs[i]) / period

        return float(round(atr, 4))

    @staticmethod
    def calculate_bollinger_bands(
        prices: List[float], period: int = 20, num_std: float = 2.0
    ) -> Dict[str, Optional[float]]:
        if len(prices) < period:
            return {"middle": None, "upper": None, "lower": None}

        recent = prices[-period:]
        sma = float(np.mean(recent))
        std = float(np.std(recent, ddof=1))  # Sample standard deviation

        upper = sma + (num_std * std)
        lower = sma - (num_std * std)

        return {
            "middle": float(round(sma, 2)),
            "upper": float(round(upper, 2)),
            "lower": float(round(lower, 2)),
        }

    @classmethod
    def compute_all_indicators(cls, candles: Any) -> Dict[str, Any]:
        """Compute complete technical suite for a candle series."""
        if not candles:
            return {
                "rsi": None,
                "macd": {"macd": None, "signal": None, "histogram": None},
                "bollinger": {"middle": None, "upper": None, "lower": None},
                "atr": None,
                "candle_count": 0,
            }

        closes = [getattr(c, "close", c) if hasattr(c, "close") else float(c) for c in candles]
        highs = [getattr(c, "high", c) if hasattr(c, "high") else float(c) for c in candles]
        lows = [getattr(c, "low", c) if hasattr(c, "low") else float(c) for c in candles]

        rsi = cls.calculate_rsi(closes)
        macd = cls.calculate_macd(closes)
        bb = cls.calculate_bollinger_bands(closes)
        atr = cls.calculate_atr(highs, lows, closes) if (highs and lows and closes) else None

        return {
            "rsi": rsi,
            "macd": macd,
            "bollinger": bb,
            "atr": atr,
            "candle_count": len(candles),
            "latest_close": closes[-1] if closes else None,
        }
