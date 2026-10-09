"""
File Overview: Outbound port interface for managing ML model artifacts (weights/scalers).

All Functions/Classes:
- i_model_store: Interface for model management. Take artifact metadata and send to storage.
- save_model: Persist model identifier. Take symbol/path and send to implementation.
- load_model: Retrieve model coordinates. Take symbol and send binary/file path.

Endpoints/APIs: None

Database Tables: None
"""
from abc import ABC, abstractmethod


class IModelStorePort(ABC):
    @abstractmethod
    def save_model(self, symbol: str, path: str) -> None:
        pass
    @abstractmethod
    def load_model(self, symbol: str) -> str:
        pass
