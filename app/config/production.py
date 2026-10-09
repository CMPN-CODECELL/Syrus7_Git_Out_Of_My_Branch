from app.config.settings import Settings

class ProductionSettings(Settings):
    AppEnv: str = "production"
    LogLevel: str = "WARNING"

