"""
File Overview: Domain events indicating ingestion milestones.
"""
from shared.domain.base_domain_event import BaseDomainEvent

class ArticleIngestedEvent(BaseDomainEvent):
    pass

class TickBatchIngestedEvent(BaseDomainEvent):
    pass
