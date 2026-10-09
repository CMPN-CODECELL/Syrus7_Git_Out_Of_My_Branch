from enum import Enum


class ConditionType(str, Enum):
    ABOVE_PRICE = "ABOVE_PRICE"
    BELOW_PRICE = "BELOW_PRICE"
    IV_SPIKE = "IV_SPIKE"
    DELTA_BREACH = "DELTA_BREACH"


class DeliveryChannel(str, Enum):
    WEBSOCKET = "WEBSOCKET"
    WEBHOOK = "WEBHOOK"
    EMAIL = "EMAIL"


class AlertStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    THROTTLED = "THROTTLED"
    FAILED = "FAILED"
