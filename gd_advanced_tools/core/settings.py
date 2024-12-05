from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings


ROOT_PATH = Path(__file__).parent.parent

load_dotenv()


class APISettings(BaseSettings):
    """Класс настроек API СКБ-Техно."""

    skb_api_key: str = Field(default="666-555-777", env="SKB_API_KEY")
    skb_url: str = Field(default="https://ya.ru/", env="SKB_URL")
    skb_endpoint: dict = {
        "GET_KINDS": "Kinds",
        "CREATE_REQUEST": "Create",
        "GET_RESULT": "Result",
    }


class DatabaseSettings(BaseSettings):
    """Класс настроек соединения с БД."""

    db_host: str = Field(default="localhost", env="DB_HOST")
    db_port: int = Field(default=5432, env="DB_PORT")
    db_name: str = Field(default="postgres", env="DB_NAME")
    db_user: str = Field(default="postgres", env="DB_USER")
    db_pass: str = Field(default="postgres", env="DB_PASS")
    db_echo: bool = Field(default=False, env="DB_ECHO")
    db_poolsize: int = Field(default=10)
    db_maxoverflow: int = Field(default=10)

    @property
    def db_url_asyncpg(self):
        return f"postgresql+asyncpg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"


class FileStorageSettings(BaseSettings):
    """Класс настроек соединения с файловым хранилищем."""

    fs_bucket: str = Field(default="my-bucket", env="FS_BUCKET")
    fs_endpoint: str = Field(default="http://127.0.0.1:9090", env="FS_URL")
    fs_access_key: str = Field(default="minioadmin", env="FS_ACCESS_KEY")
    fs_secret_key: str = Field(default="minioadmin", env="FS_SECRET_KEY")


class LogStorageSettings(BaseSettings):
    """Класс настроек соединения с хранилищем логов."""

    log_host: str = Field(default="localhost", env="LOG_HOST")
    log_port: int = Field(default=9000, env="LOG_PORT")
    log_udp_port: int = Field(default=12201, env="LOG_TCP_PORT")


class Settings(BaseSettings):
    debug: bool = True

    root_dir: Path
    src_dir: Path
    jwt_secret: str = Field(default="SECRET", env="JWT_SECRET")

    database_settings: DatabaseSettings = DatabaseSettings()
    api_settings: APISettings = APISettings()
    logging_settings: LogStorageSettings = LogStorageSettings()
    storage_settings: FileStorageSettings = FileStorageSettings()
    constants: dict = {"REQUEST_PRIORITY_DEFAULT": 80}


settings = Settings(
    root_dir=ROOT_PATH,
    src_dir=ROOT_PATH / "gd_advanced_tools",
)
