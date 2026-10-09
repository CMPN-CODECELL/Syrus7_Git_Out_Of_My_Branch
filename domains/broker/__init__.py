"""
Broker domain: the only code in Kraken that talks to 021 Trade.

Nothing reaches 021 except through domains.broker. Order mutations (place/modify/cancel)
are never retried; read requests are retried with backoff and jitter.
"""
