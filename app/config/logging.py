from app.config.settings import get_settings

def get_logging_config():
    settings = get_settings()
    return {
        "version": 1,
        "disable_existing_loggers": False,
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
            },
        },
        "root": {
            "handlers": ["console"],
            "level": settings.LogLevel,
        },
    }
