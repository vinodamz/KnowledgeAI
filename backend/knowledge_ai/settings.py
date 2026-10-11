from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='KNOWLEDGE_AI_', env_file='.env', extra='ignore')
    database_url: str
    signing_secret: str
    session_seconds: int = Field(default=28800, ge=60, le=604800)
    secure_cookies: bool = False

    @field_validator('signing_secret')
    @classmethod
    def secret_valid(cls, value):
        if len(value) < 32 or value.startswith('CHANGE_ME'):
            raise ValueError('A randomly generated signing secret of at least 32 characters is required')
        return value

    @field_validator('database_url')
    @classmethod
    def postgres_only(cls, value):
        if not value.startswith('postgresql+psycopg://'):
            raise ValueError('PostgreSQL with psycopg is required')
        return value
