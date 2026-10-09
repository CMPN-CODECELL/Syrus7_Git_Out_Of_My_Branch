
import httpx
import asyncio

async def verify_proxy():
    url = "http://127.0.0.1:8000/v1/ingestion/options/NIFTY"
    print(f"Testing proxy for NIFTY: {url}")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"Symbol: {data.get('symbol')}")
                print(f"Spot: {data.get('underlying_value')}")
                print(f"Ticks: {len(data.get('raw_chain', []))}")
            else:
                print(f"Error: {resp.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify_proxy())
