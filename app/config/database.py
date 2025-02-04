from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseYAMLSettings


__all__ = ("DatabaseConnectionSettings", "db_connection_settings")


class DatabaseConnectionSettings(BaseYAMLSettings):
    """Configuration settings for relational database connections.

    Configuration sections:
    - Connection parameters
    - Authentication credentials
    - Drivers and operation modes
    - Connection timeouts
    - Connection pooling
    - SSL/TLS configuration
    """

    yaml_group = "database"
    model_config = SettingsConfigDict(
        env_prefix="DB_",
        extra="forbid",
    )

    # Core connection parameters
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

    # Authentication
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

    # Drivers and operation modes
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

    # Timeouts
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

    # Connection pooling
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

    # SSL/TLS Configuration
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

    @property
    def async_connection_url(self) -> str:
        """Construct asynchronous database connection URL."""
        return self._build_connection_url(is_async=True)

    @property
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


# Instantiate settings for immediate use
db_connection_settings = DatabaseConnectionSettings()
