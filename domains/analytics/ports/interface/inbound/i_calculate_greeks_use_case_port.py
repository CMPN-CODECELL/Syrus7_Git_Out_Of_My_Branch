"""
File Overview: Inbound port interface for options Greeks pricing and surface calculation use cases.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from domains.analytics.domain.value_objects import GreekValueObject


class ICalculateGreeksUseCasePort(ABC):
    """Inbound use-case port for calculating option price, Greeks, and volatility parameters."""

    @abstractmethod
    async def calculate_single_option(
        self,
        spot: float,
        strike: float,
        expiry_days: int,
        rate: float,
        volatility: float,
        option_type: str = "call",
        dividend_yield: float = 0.0,
    ) -> Dict[str, Any]:
        """Calculate BSM price and Greeks for a single contract."""
        pass

    @abstractmethod
    async def get_ticker_analytics(self, symbol: str) -> Dict[str, Any]:
        """Fetch live ticker data and calculate complete option chain surface parameters."""
        pass
