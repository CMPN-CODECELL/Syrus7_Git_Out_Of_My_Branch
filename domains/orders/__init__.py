"""
Orders domain (Level 2): proposals, one-time approval, execution, the order journal,
reconciliation of unknown outcomes, order tracking and the per-user live feed.

The only path that sends an order to 021 is ExecutionService.approve(), reached from
POST /v1/proposals/{id}/approve by an authenticated human click.
"""
