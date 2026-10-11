from pydantic import Field, field_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='KNOWLEDGE_AI_', env_file='.env', extra='ignore')
    database_url: str
    signing_secret: str
    session_seconds: int = Field(default=28800, ge=60, le=604800)
    secure_cookies: bool = False
    object_directory: str = "/data/objects"
    publication_directory: str = "/data/publications"
    embedding_base_url: str = "http://host.docker.internal:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = Field(default=768, ge=1)
    upload_max_bytes: int = Field(default=10_000_000, ge=1, le=20_000_000)
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = Field(default="gemini-flash-latest", validation_alias=AliasChoices("KNOWLEDGE_AI_GEMINI_MODEL", "GEMINI_MODEL"))

    @field_validator("gemini_model")
    @classmethod
    def gemini_model_valid(cls, value):
        import re
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", value):
            raise ValueError("Invalid Gemini model name")
        return value

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
