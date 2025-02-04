from sqlalchemy import create_engine, text
from sqlalchemy.event import listen
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.config.settings import DatabaseConnectionSettings, settings
from app.utils.errors import DatabaseError
from app.utils.logging_service import db_logger


__all__ = ("db_initializer",)


class DatabaseInitializer:
    """Class for initializing and managing database connections.

    Provides creation of synchronous and asynchronous engines, connection pool management,
    SQL query logging, and connection health checks.

    Args:
        settings (DatabaseSettings): Database configuration parameters

    Attributes:
        async_engine (AsyncEngine): SQLAlchemy async engine
        async_session_maker (async_sessionmaker): Async session factory
        sync_engine (Engine): SQLAlchemy sync engine
        sync_session_maker (sessionmaker): Sync session factory
    """

    def __init__(self, settings: DatabaseConnectionSettings):
        self.settings: DatabaseConnectionSettings = settings

        # Main async engine
        self.async_engine = self._create_async_engine()
        self.async_session_maker = async_sessionmaker(
            bind=self.async_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        # Sync engine for migrations only
        self.sync_engine = self._create_sync_engine()
        self.sync_session_maker = sessionmaker(
            bind=self.sync_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        self.register_logging_events()

    def _create_async_engine(self) -> AsyncEngine:
        """Creates and configures an async database engine.

        Returns:
            AsyncEngine: Configured SQLAlchemy async engine
        """
        return create_async_engine(
            url=self.settings.async_connection_url,
            echo=self.settings.echo,
            pool_size=self.settings.pool_size,
            max_overflow=self.settings.max_overflow,
            pool_recycle=self.settings.pool_recycle,
            pool_timeout=self.settings.pool_timeout,
            connect_args=self._get_connect_args(),
        )

    def _create_sync_engine(self):
        """Creates and configures a sync database engine.

        Returns:
            Engine: Configured SQLAlchemy sync engine
        """
        return create_engine(
            url=self.settings.sync_connection_url,
            echo=self.settings.echo,
            pool_size=self.settings.pool_size,
            max_overflow=self.settings.max_overflow,
            pool_recycle=self.settings.pool_recycle,
            pool_timeout=self.settings.pool_timeout,
            connect_args=self._get_connect_args(),
        )

    def _get_connect_args(self) -> dict:
        """Generates additional database connection arguments.

        Returns:
            dict: Additional connection parameters
        """
        connect_args = {}

        if self.settings.type == "postgresql":
            connect_args.update(
                {
                    "command_timeout": self.settings.command_timeout,
                    "timeout": self.settings.connect_timeout,
                }
            )

            if self.settings.ca_bundle:
                import ssl

                ssl_context = ssl.create_default_context(
                    cafile=self.settings.ca_bundle
                )
                connect_args["ssl"] = ssl_context

        elif self.settings.type == "oracle":
            connect_args.update(
                {
                    "encoding": "UTF-8",
                    "nencoding": "UTF-8",
                }
            )

        return connect_args

    async def _initialize_async_pool(self):
        """Pre-initializes connections in the async pool"""
        connections = []
        try:
            for _ in range(self.async_engine.pool.size()):
                conn = await self.async_engine.connect()
                connections.append(conn)
            db_logger.info("Async connection pool initialized")
        except Exception as e:
            db_logger.error(
                f"Async connection pool initialization failed: {str(e)}"
            )
        finally:
            for conn in connections:
                await conn.close()

    def register_logging_events(self):
        """Registers event handlers for SQL query logging."""

        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            db_logger.info("SQL Statement: %s", statement)
            db_logger.info("Parameters: %s", parameters)

        def after_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            db_logger.info("SQL Execution Completed.")

        # For async engine
        listen(
            self.async_engine.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )
        listen(
            self.async_engine.sync_engine,
            "after_cursor_execute",
            after_cursor_execute,
        )

        # For sync engine
        listen(
            self.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )
        listen(self.sync_engine, "after_cursor_execute", after_cursor_execute)

    def get_async_engine(self):
        """Returns the async database engine.

        Returns:
            Engine: SQLAlchemy async engine
        """
        return self.async_engine

    def get_sync_engine(self):
        """Returns the sync engine for Alembic migrations.

        Returns:
            Engine: SQLAlchemy sync engine
        """
        return self.sync_engine

    def dispose_sync(self):
        """Closes all sync connections"""
        try:
            self.sync_engine.dispose()
            db_logger.info("Sync database connections closed")
        except Exception as exc:
            db_logger.error(
                f"Failed to close sync database connections: {str(exc)}"
            )

    async def dispose_async(self):
        """Closes all async connections"""
        try:
            await self.async_engine.dispose()
            db_logger.info("Async database connections closed")
        except Exception as exc:
            db_logger.error(
                f"Failed to close async database connections: {str(exc)}"
            )

    async def check_connection(self) -> bool:
        """Verifies database connection health.

        Returns:
            bool: True if connection is active and working correctly

        Raises:
            DatabaseError: If connection fails or unexpected result received
        """
        async with self.async_session_maker() as session:
            try:
                result = await session.execute(text("SELECT 1"))
                if result.scalar_one_or_none() != 1:
                    raise DatabaseError(
                        message="Database connection verification failed"
                    )
                return True
            except Exception as exc:
                raise DatabaseError(
                    message=f"Database connection check failed: {str(exc)}",
                )


# Database initializer with configuration settings
db_initializer = DatabaseInitializer(settings=settings.database)
