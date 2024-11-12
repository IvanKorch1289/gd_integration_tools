from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_PATH = Path(__file__).parent.parent


class LoggingSettings(BaseSettings):
    format: str = Field(default='{time:YYYY-MM-DD HH:mm:ss} | {level: <5} | {message}')
    file: str = Field(default='backend_log')
    rotation: str = Field(default='1MB')
    compression: str = Field(default='zip')


class APISettings(BaseSettings):
    """Класс настроек API СКБ-Техно."""

    api_key: str = Field(default='666-555-777', env='API_KEY')
    skb_url: str = Field(default='https://ya.ru/', env='SKB_URL')

    model_config = SettingsConfigDict(env_file=".env")


class DatabaseSettings(BaseSettings):
    """Класс настроек соединения с БД."""

    db_host: str = Field(default='localhost', env='DB_HOST')
    db_port: int = Field(default=5432, env='DB_PORT')
    db_name: str = Field(default='postgres', env='DB_NAME')
    db_user: str = Field(default='postgres', env='DB_USER')
    db_pass: str = Field(default='postgres', env='DB_PASS')
    db_echo: bool = Field(default=False, env='DB_ECHO')
    db_poolsize: int = Field(default=10)
    db_maxoverflow: int = Field(default=10)
    # model_config = SettingsConfigDict(env_file=".env")

    @property
    def db_url_asyncpg(self):
        return f'postgresql+asyncpg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}'


class Settings(BaseSettings):
    debug: bool = True

    root_dir: Path
    src_dir: Path

    database_settings: DatabaseSettings = DatabaseSettings()

    api_settings: APISettings = APISettings()
    logging_settings: LoggingSettings = LoggingSettings()


settings = Settings(
    root_dir=ROOT_PATH,
    src_dir=ROOT_PATH / 'gd_advanced_tools',
)
