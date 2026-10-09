from typing import Optional, Dict, Any, Tuple
from domains.notifications.domain.entities import AlertRule
from domains.notifications.domain.value_objects import ConditionType


class RuleMatcherDomainService:
    """Pure domain service for evaluating market data against alert rule threshold conditions."""

    @staticmethod
    def match(rule: AlertRule, payload: Dict[str, Any]) -> Tuple[bool, Optional[float], Optional[str]]:
        """Evaluate rule condition against tick payload.

        Returns (is_matched, actual_value, evaluation_message).
        """
        if not rule.is_active:
            return False, None, None

        cond = rule.condition_type

        if cond == ConditionType.ABOVE_PRICE:
            last_price = payload.get("last_price") or payload.get("spot_price")
            if last_price is not None and last_price > rule.threshold:
                msg = f"{rule.symbol} price {last_price} crossed above threshold {rule.threshold}"
                return True, float(last_price), msg

        elif cond == ConditionType.BELOW_PRICE:
            last_price = payload.get("last_price") or payload.get("spot_price")
            if last_price is not None and last_price < rule.threshold:
                msg = f"{rule.symbol} price {last_price} dropped below threshold {rule.threshold}"
                return True, float(last_price), msg

        elif cond == ConditionType.IV_SPIKE:
            iv = payload.get("implied_volatility") or payload.get("iv")
            if iv is not None and iv >= rule.threshold:
                msg = f"{rule.symbol} implied volatility {iv}% spiked above threshold {rule.threshold}%"
                return True, float(iv), msg

        elif cond == ConditionType.DELTA_BREACH:
            delta = payload.get("delta")
            if delta is not None and abs(float(delta)) >= rule.threshold:
                msg = f"{rule.symbol} delta {delta} breached threshold {rule.threshold}"
                return True, float(delta), msg

        return False, None, None
