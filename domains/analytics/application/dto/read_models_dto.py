"""
File Overview: Data models and calculation logic for analytics read-model snapshots.

All Functions/Classes:
- OptionChainSummaryReadModel: Pydantic schema for option chain snapshots. Take JSON data and send to validated object.
- compute_pcr: Logic to calculate Put-Call Ratio. Take option chain dict and send PCR summary stats.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""
from pydantic import BaseModel, Field



class OptionChainSummaryDTO(BaseModel):
    spot_price: float = 0.0
    expiry_dates: list[str] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    fetched_at: str = ""
    chains: dict = Field(default_factory=dict)


def compute_pcr(option_chain: dict) -> dict:
    chains = option_chain.get("chains") or {}
    if not chains:
        return {
            "pcr": 0.0,
            "ce_volume": 0,
            "pe_volume": 0,
            "ce_oi": 0,
            "pe_oi": 0,
        }

    total_ce_vol = 0
    total_pe_vol = 0
    total_ce_oi = 0
    total_pe_oi = 0

    for _, ticks in chains.items():
        for tick in ticks:
            volume = int(tick.get("volume", 0))
            oi = int(tick.get("oi", 0))
            if tick.get("type") == "CE":
                total_ce_vol += volume
                total_ce_oi += oi
            elif tick.get("type") == "PE":
                total_pe_vol += volume
                total_pe_oi += oi

    pcr = round(total_pe_vol / total_ce_vol, 4) if total_ce_vol > 0 else 0.0
    return {
        "pcr": pcr,
        "ce_volume": total_ce_vol,
        "pe_volume": total_pe_vol,
        "ce_oi": total_ce_oi,
        "pe_oi": total_pe_oi,
    }
