from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class PriceQuote(BaseModel):
    """Latest 021 price for one instrument, with its age so callers can refuse stale data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token: int
    exchange: str
    ltp: int
    as_of: datetime
    stale: bool
    open: Optional[int] = None
    prev_close: Optional[int] = None
    source: Literal["021_SOCKET", "021_SNAPSHOT"] = "021_SOCKET"
