import httpx
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

class Zero21TradeClient:
    """
    Client for interacting with the 021 Trade API (https://devapi.021.trade/api/developer-api/v1).
    Used for placing and managing orders.
    """
    BASE_URL = "https://devapi.021.trade/api/developer-api/v1"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.access_token: Optional[str] = None
        
    async def authenticate(self) -> bool:
        """Authenticate and retrieve access token."""
        url = f"{self.BASE_URL}/auth/token"
        payload = {"username": self.username, "password": self.password}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.access_token = data["data"]["accessToken"]
                    logger.info("Successfully authenticated with 021 Trade API.")
                    return True
            
            logger.error(f"Authentication failed: {response.text}")
            return False

    def _get_headers(self) -> Dict[str, str]:
        if not self.access_token:
            raise ValueError("Not authenticated. Call authenticate() first.")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    async def place_order(self, order_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Place an order using the 021 Trade API.
        Expected order_payload matches the reasoning engine output.
        """
        url = f"{self.BASE_URL}/orders"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=self._get_headers(), json=order_payload)
            result = response.json()
            
            if response.status_code == 200 and result.get("success"):
                logger.info(f"Order placed successfully: {result['data']['orderId']}")
                return result["data"]
            else:
                error_msg = result.get("error", response.text)
                logger.error(f"Failed to place order: {error_msg}")
                raise Exception(f"Order placement failed: {error_msg}")

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current portfolio positions."""
        url = f"{self.BASE_URL}/portfolio/positions"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._get_headers())
            if response.status_code == 200:
                return response.json()
            raise Exception("Failed to fetch positions.")
