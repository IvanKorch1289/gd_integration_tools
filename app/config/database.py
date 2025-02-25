from typing import ClassVar, Literal, Optional

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseSettingsWithLoader


__all__ = (
    "DatabaseConnectionSettings",
    "db_connection_settings",
    "MongoConnectionSettings",
    "mongo_connection_settings",
)


class DatabaseConnectionSettings(BaseSettingsWithLoader):
    """Configuration settings for relational database connections."""

    yaml_group: ClassVar[str] = "database"
    model_config = SettingsConfigDict(
        env_prefix="DB_",
        extra="forbid",
    )

    type: Literal["postgresql", "oracle"] = Field(
        ...,
        description="Database management system type",
        examples=["postgresql"],
    )
    host: str = Field(
        ...,
        description="Database server hostname or IP address",
        examples=["localhost", "db.example.com"],
    )
    port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="Database server port number",
        examples=[5432, 1521],
    )
    name: str = Field(
        ...,
        description="Database name or service identifier",
        examples=["myapp_prod", "ORCL"],
    )
    username: str = Field(
        ...,
        description="Database user name",
        examples=["admin", "app_user"],
    )
    password: str = Field(
        ...,
        description="Database user password",
        examples=["secure_password_123"],
    )
    async_driver: str = Field(
        ...,
        description="Asynchronous driver package",
        examples=["asyncpg", "aioodbc"],
    )
    sync_driver: str = Field(
        ...,
        description="Synchronous driver package",
        examples=["psycopg2", "cx_oracle"],
    )
    echo: bool = Field(
        ..., description="Enable SQL query logging", examples=[False]
    )
    connect_timeout: int = Field(
        ...,
        description="Connection establishment timeout in seconds",
        examples=[10],
    )
    command_timeout: int = Field(
        ...,
        description="Database command execution timeout in seconds",
        examples=[30],
    )
    pool_size: int = Field(
        ...,
        ge=1,
        description="Maximum number of permanent connections in pool",
        examples=[5],
    )
    max_overflow: int = Field(
        ...,
        ge=0,
        description="Maximum temporary connections beyond pool size",
        examples=[10],
    )
    pool_recycle: int = Field(
        ...,
        description="Connection recycling interval in seconds",
        examples=[3600],
    )
    pool_timeout: int = Field(
        ...,
        description="Wait timeout for pool connection in seconds",
        examples=[30],
    )
    ssl_mode: Optional[str] = Field(
        None,
        description="SSL connection mode (PostgreSQL specific)",
        examples=["require", "verify-full"],
    )
    ca_bundle: Optional[str] = Field(
        None,
        description="Path to SSL CA certificate file",
        examples=["/path/to/ca.crt"],
    )

    @computed_field
    def async_connection_url(self) -> str:
        """Construct asynchronous database connection URL."""
        return self._build_connection_url(is_async=True)

    @computed_field
    def sync_connection_url(self) -> str:
        """Construct synchronous database connection URL."""
        return self._build_connection_url(is_async=False)

    def _build_connection_url(self, is_async: bool) -> str:
        """Internal method for constructing database connection strings."""
        driver = self.async_driver if is_async else self.sync_driver

        if self.type == "postgresql":
            return (
                f"postgresql+{driver}://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.name}"
            )
        elif self.type == "oracle":
            # Oracle connection string implementation
            raise NotImplementedError("Oracle support pending implementation")
        raise ValueError(f"Unsupported database type: {self.type}")


class MongoConnectionSettings(BaseSettingsWithLoader):
    """Configuration settings for no-relational database connections."""

    yaml_group: ClassVar[str] = "mongo"
    model_config = SettingsConfigDict(
        env_prefix="MONGO_",
        extra="forbid",
    )

    username: str = Field(
        ...,
        description="MongoDB username",
        examples=["admin"],
    )
    password: str = Field(
        ...,
        description="MongoDB password",
        examples=["secure_password_123"],
    )
    host: str = Field(
        ...,
        description="MongoDB server hostname or IP address",
        examples=["localhost", "mongo.example.com"],
    )
    port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="MongoDB server port number",
        examples=[27017],
    )
    name: str = Field(
        ...,
        description="Database name",
        examples=["myapp_prod"],
    )
    timeout: int = Field(
        ...,
        description="Connection timeout in milliseconds",
        examples=[5],
    )
    max_pool_size: int = Field(
        ...,
        ge=1,
        le=100,
        description="Maximum number of MongoDB connections in the pool",
        examples=[50],
    )
    min_pool_size: int = Field(
        ...,
        ge=1,
        le=100,
        description="Minimum number of MongoDB connections in the pool",
        examples=[5],
    )

    @computed_field
    def connection_string(self) -> str:
        return f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}/{self.name}?authSource=admin"


# Instantiate settings for immediate use
db_connection_settings = DatabaseConnectionSettings()
mongo_connection_settings = MongoConnectionSettings()
