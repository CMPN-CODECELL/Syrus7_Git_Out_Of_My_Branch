"""
File Overview: Value objects defining supported domains in the Ingestion context.
"""
from dataclasses import dataclass
from datetime import date
from enum import Enum

class ExchangeValueObject(Enum):
    NSE = "NSE"
    BSE = "BSE"

@dataclass(frozen=True)
class ExpiryValueObject:
    date_val: date
    def days_to_expiry(self, current_date: date) -> int:
        return (self.date_val - current_date).days

@dataclass(frozen=True)
class SymbolValueObject:
    value: str
    def __post_init__(self):
        if not self.value.isupper():
            raise ValueError("Symbol must be uppercase")
