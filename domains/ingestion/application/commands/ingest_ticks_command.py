"""
File Overview: Command object for triggering market tick ingestion for a specific symbol/expiry.

All Functions/Classes:
- ingest_ticks_command: Data transfer object for tick ingestion parameters. Take symbol and expiry and send to market data source.

Endpoints/APIs: None

Database Tables: None
"""
from dataclasses import dataclass

@dataclass
class IngestTicksCommand:
    symbol: str
    expiry: str
