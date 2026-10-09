"""
File Overview: Command object for triggering news ingestion for a specific symbol.

All Functions/Classes:
- ingest_news_command: Data transfer object for news ingestion parameters. Take symbol and max_articles and send to ingestion service.

Endpoints/APIs: None

Database Tables: None
"""
from dataclasses import dataclass

@dataclass
class IngestNewsCommand:
    symbol: str
    max_articles: int
