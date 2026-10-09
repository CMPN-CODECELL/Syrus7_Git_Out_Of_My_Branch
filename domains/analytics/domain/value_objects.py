"""
File Overview: Value objects for the Analytics domain.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class GreekValueObject:
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float

@dataclass(frozen=True)
class ImpliedVolatilityValueObject:
    value: float
    def is_elevated(self, threshold: float) -> bool:
        return self.value > threshold

@dataclass(frozen=True)
class PCRValueObject:
    value: float
    def interpretation(self) -> str:
        if self.value > 1.2: return "BULLISH"
        if self.value < 0.8: return "BEARISH"
        return "NEUTRAL"

@dataclass(frozen=True)
class PolarityValueObject:
    value: float
    def label(self) -> str:
        if self.value > 0.1: return "BULLISH"
        if self.value < -0.1: return "BEARISH"
        return "NEUTRAL"
