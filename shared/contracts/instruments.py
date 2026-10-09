from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

InternalExchange = Literal["NSECM", "NSEFO", "NSEIDX", "BSEEQ", "BSEEQD", "BSEIDX"]
RequestExchange = Literal["NSE", "NSEFO", "BSE", "BSEFO"]

# Internal (responses / instruments file) -> request names. Index exchanges are data only.
EXCHANGE_TO_REQUEST: dict[str, str] = {
    "NSECM": "NSE",
    "NSEFO": "NSEFO",
    "BSEEQ": "BSE",
    "BSEEQD": "BSEFO",
}

EXCHANGE_TO_WS_CODE: dict[str, int] = {
    "NSECM": 1,
    "NSEFO": 2,
    "NSEIDX": 3,
    "BSEEQ": 4,
    "BSEEQD": 5,
    "BSEIDX": 6,
}
WS_CODE_TO_EXCHANGE: dict[int, str] = {v: k for k, v in EXCHANGE_TO_WS_CODE.items()}


class Instrument(BaseModel):
    """One row of the 021 instruments file. Prices (circuits, strike, tick) are paise."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token: int
    exchange: InternalExchange
    underlying_token: int
    underlying_exchange: str
    min_lot_size: int = 0
    board_lot_quantity: int = Field(1, ge=1)
    freeze_quantity: int = 0
    lower_circuit: int = 0
    upper_circuit: int = 0
    expiry: int = 0
    option_type: Optional[Literal["CALL", "PUT"]] = None
    strike_price: int = 0
    symbol: str
    instrument_type: str
    isin: str = ""
    ticksize: int = Field(1, ge=1)

    @property
    def is_index(self) -> bool:
        return self.exchange in ("NSEIDX", "BSEIDX") or self.instrument_type == "IDX"

    @property
    def is_derivative(self) -> bool:
        return self.exchange in ("NSEFO", "BSEEQD")

    @property
    def request_exchange(self) -> Optional[str]:
        """Exchange name to use in order requests; None for data-only indices."""
        return EXCHANGE_TO_REQUEST.get(self.exchange)

    @property
    def ws_code(self) -> int:
        return EXCHANGE_TO_WS_CODE[self.exchange]
