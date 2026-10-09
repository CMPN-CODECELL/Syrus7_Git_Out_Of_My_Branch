import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from domains.analytics.application.services.derivatives.derivatives_orchestrator_service import DerivativesOrchestratorService
from domains.analytics.tasks.derivatives_tasks import process_tick_batch

@pytest.mark.unit
class TestDerivativesOrchestratorService:
    @pytest.mark.asyncio
    @patch("domains.analytics.application.services.derivatives.derivatives_orchestrator_service.get_redis_client")
    async def test_price_options_chain_success(self, mock_get_redis):
        # Setup mock Redis client
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        
        # Prepare sample raw options data structure (matches OptionChainSummaryDTO schema)
        raw_payload = {
            "summary": {
                "underlying_price": 24000.0,
                "risk_free_rate": 6.5,
                "expiry_days": 30,
                "dividend_yield": 1.2
            },
            "chain": [
                {
                    "strike_price": 24000.0,
                    "call": {"iv": 0.15, "ltp": 250.0},
                    "put": {"iv": 0.14, "ltp": 220.0}
                }
            ]
        }
        mock_redis.get.return_value = json.dumps(raw_payload)
        
        orchestrator = DerivativesOrchestratorService()
        success = await orchestrator.price_options_chain("NIFTY")
        
        assert success is True
        
        # Check that it fetched raw options chain
        mock_redis.get.assert_called_once()
        # Check that it cached priced options chain
        mock_redis.set.assert_called_once()
        # Check that it published to streams/pubsub
        mock_redis.xadd.assert_called_once()
        mock_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    @patch("domains.analytics.application.services.derivatives.derivatives_orchestrator_service.get_redis_client")
    async def test_price_options_chain_no_data(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        
        orchestrator = DerivativesOrchestratorService()
        success = await orchestrator.price_options_chain("NIFTY")
        
        assert success is False
        mock_redis.set.assert_not_called()

@pytest.mark.unit
class TestDerivativesCeleryTask:
    @patch("domains.analytics.application.services.derivatives.derivatives_orchestrator_service.DerivativesOrchestratorService")
    def test_process_tick_batch_task(self, mock_service_class):
        mock_instance = MagicMock()
        mock_instance.price_options_chain = AsyncMock(return_value=True)
        mock_service_class.return_value = mock_instance
        
        result = process_tick_batch("NIFTY")
        
        assert result is True
        mock_instance.price_options_chain.assert_called_once_with("NIFTY")
