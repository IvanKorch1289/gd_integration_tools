from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv


load_dotenv()


class APISettings(BaseSettings):
    """Класс настроек API СКБ-Техно."""

    API_KEY: str = Field(default='666-555-777', env='API_KEY')
    SKB_URL: str = Field(default='https://ya.ru/', env='SKB_URL')


class DatabaseSettings(BaseSettings):
    """Класс настроек соединения с БД."""

    DB_HOST: str = Field(default='localhost', env='DB_HOST')
    DB_PORT: int = Field(default=5432, env='DB_PORT')
    DB_NAME: str = Field(default='postgres', env='DB_NAME')
    DB_USER: str = Field(default='postgres', env='DB_USER')
    DB_PASS: str = Field(default='postgres', env='DB_PASS')
    DB_ECHO: bool = Field(default=False, env='DB_ECHO')
    DB_POOLSIZE: int = Field(default=10)
    DB_MAXOVERFLOW: int = Field(default=10)

    @property
    def db_url_asyncpg(self):
        return f'postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'


database_settings = DatabaseSettings()
api_settings = APISettings()
