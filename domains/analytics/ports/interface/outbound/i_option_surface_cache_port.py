"""
File Overview: Outbound port interface for caching and retrieving option chain surfaces.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class IOptionSurfaceCachePort(ABC):
    """Outbound port for reading/writing option chain snapshot surfaces in Redis or Cache."""

    @abstractmethod
    async def get_cached_surface(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached option surface for a symbol."""
        pass

    @abstractmethod
    async def save_surface(self, symbol: str, surface_data: Dict[str, Any], ttl_seconds: int = 600) -> None:
        """Cache option surface data."""
        pass
