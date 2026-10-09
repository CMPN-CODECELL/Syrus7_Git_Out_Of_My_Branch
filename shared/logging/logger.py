import logging.config
import contextvars
from app.config.logging import get_logging_config

correlation_id_var = contextvars.ContextVar("correlation_id", default=None)

def get_correlation_id() -> str:
    return correlation_id_var.get()

def set_correlation_id(val: str) -> None:
    correlation_id_var.set(val)

def setup_logging():
    config = get_logging_config()
    logging.config.dictConfig(config)
