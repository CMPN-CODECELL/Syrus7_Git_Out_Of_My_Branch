from app.config.settings import get_settings

def get_logging_config():
    settings = get_settings()
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "redact": {
                "()": "shared.logging.redaction.RedactingFilter",
            },
        },
        "formatters": {
            "json": {
                "()": "shared.logging.formatters.JSONFormatter",
            },
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json" if settings.AppEnv == "production" else "standard",
                "level": settings.LogLevel,
                "filters": ["redact"],
            },
        },
        "loggers": {
            # httpx logs full request URLs at INFO; keep it at WARNING so query strings stay out of logs.
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
            "websockets": {"level": "WARNING"},
        },
        "root": {
            "handlers": ["console"],
            "level": settings.LogLevel,
        },
    }
