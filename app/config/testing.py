from pydantic_settings import SettingsConfigDict

from app.config.settings import Settings


class TestingSettings(Settings):
    # Never read the developer's .env in tests: it may hold real 021 / Gemini credentials,
    # and a test login would revoke the running app's 021 token.
    model_config = SettingsConfigDict(env_file=None, populate_by_name=True, extra="ignore")
