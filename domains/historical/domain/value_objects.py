"""
File Overview: Value objects for Historical OHLC domain context.
"""
from enum import Enum

class TimeframeEnum(str, Enum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"
