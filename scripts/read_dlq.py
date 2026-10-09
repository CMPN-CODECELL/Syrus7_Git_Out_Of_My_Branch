import redis
import json

r = redis.from_url('redis://127.0.0.1:6379/0')
msgs = r.xrevrange('stream:dlq:nlp_to_api', count=1)
if msgs:
    payload = msgs[0][1]
    data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in payload.items()}
    inner_payload = json.loads(data.get("payload", "{}"))
    print(f"Error: {inner_payload.get('error')}")
    print(f"Original Stream: {inner_payload.get('original_stream')}")
    print(f"Symbol: {inner_payload.get('payload', {}).get('symbol')}")
else:
    print("DLQ is empty")
