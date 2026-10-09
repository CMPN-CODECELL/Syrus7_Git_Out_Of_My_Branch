"""
File Overview: Celery tasks for processing derivatives market data and options chains.
"""
import logging
from celery import shared_task
import asyncio

logger = logging.getLogger(__name__)

@shared_task(name="domains.analytics.tasks.derivatives_tasks.process_tick_batch")
def process_tick_batch(symbol: str) -> bool:
    """
    Celery task to run Crank-Nicolson/BSM options pricing for a symbol.
    """
    logger.debug("[%s] Celery task process_tick_batch started", symbol)
    try:
        from domains.analytics.application.services.derivatives.derivatives_orchestrator_service import DerivativesOrchestratorService
        orchestrator = DerivativesOrchestratorService()
        success = asyncio.run(orchestrator.price_options_chain(symbol))
        logger.debug("[%s] Celery task process_tick_batch finished with success=%s", symbol, success)
        return success
    except Exception as exc:
        logger.error("[%s] Celery task process_tick_batch failed: %s", symbol, exc)
        return False
