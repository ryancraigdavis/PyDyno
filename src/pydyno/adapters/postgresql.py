"""PostgreSQL Connection Adapter for PyDyno"""

import os
from typing import Dict, Any, Optional, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.ext.declarative import declarative_base

from pydyno.core.adapters import ConnectionAdapter
from pydyno.core.pool_config import PoolConfig
from pydyno.core.exceptions import AdapterInitializationError, AdapterConfigurationError

# Re-export Base for convenience
Base = declarative_base()


class PostgreSQLAdapter(ConnectionAdapter):
    """
    PostgreSQL connection adapter using SQLAlchemy async with asyncpg

    This adapter manages a pool of PostgreSQL connections and provides
    both raw SQL execution and SQLAlchemy ORM session management.

    Example:
        config = {
            'host': 'localhost',
            'port': 5432,
            'user': 'postgres',
            'password': 'password',
            'database': 'mydb'
        }

        pool_config = PoolConfig(max_connections=20, timeout=30.0)

        adapter = PostgreSQLAdapter(
            name="main_db",
            service_type="postgresql",
            config=config,
            pool_config=pool_config
        )

        await adapter.initialize()

        # Use with session context manager
        async with adapter.session_scope() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()
    """

    def __init__(
        self,
        name: str,
        service_type: str,
        config: Dict[str, Any],
        pool_config: PoolConfig,
    ):
        # Validate PostgreSQL-specific configuration
        self._validate_postgresql_config(config)

        super().__init__(name, service_type, config, pool_config)

        # PostgreSQL-specific attributes
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[sessionmaker] = None

    def _validate_postgresql_config(self, config: Dict[str, Any]):
        """Validate PostgreSQL-specific configuration"""
        # Check for either full URL or individual components
        if "url" in config:
            if not isinstance(config["url"], str) or not config["url"].strip():
                raise AdapterConfigurationError(
                    "PostgreSQL URL must be a non-empty string"
                )
            return

        # Check for required individual components
        required_fields = ["user", "password", "database"]
        missing_fields = [
            field
            for field in required_fields
            if field not in config or not config[field]
        ]

        if missing_fields:
            raise AdapterConfigurationError(
                f"Missing required PostgreSQL config fields: {missing_fields}. "
                f"Either provide 'url' or all of: {required_fields}"
            )

        # Validate individual field types
        if "host" in config and not isinstance(config["host"], str):
            raise AdapterConfigurationError("PostgreSQL host must be a string")

        if "port" in config and not isinstance(config["port"], (int, str)):
            raise AdapterConfigurationError(
                "PostgreSQL port must be an integer or string"
            )

        try:
            if "port" in config:
                port = int(config["port"])
                if port < 1 or port > 65535:
                    raise AdapterConfigurationError(
                        "PostgreSQL port must be between 1 and 65535"
                    )
        except (ValueError, TypeError):
            raise AdapterConfigurationError("PostgreSQL port must be a valid integer")

    def _build_database_url(self) -> str:
        """Build PostgreSQL database URL from configuration"""
        # Return URL directly if provided
        if "url" in self.config:
            url = self.config["url"]
            # Ensure we're using asyncpg driver
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif not url.startswith("postgresql+asyncpg://"):
                self.logger.warning(
                    f"URL doesn't specify asyncpg driver, using as-is: {url}"
                )
            return url

        # Build URL from components
        host = self.config.get("host", "localhost")
        port = self.config.get("port", 5432)
        user = self.config["user"]
        password = self.config["password"]
        database = self.config["database"]

        # Don't add sslmode or application_name to URL - handle in connect_args
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"

    async def initialize(self):
        """Initialize the PostgreSQL connection pool"""
        if self._initialized:
            self.logger.debug(f"PostgreSQL adapter '{self.name}' already initialized")
            return

        try:
            self.logger.info(f"Initializing PostgreSQL adapter '{self.name}'...")

            # Build database URL
            database_url = self._build_database_url()

            # Prepare connect_args for asyncpg
            connect_args: Dict[str, Any] = {
                "server_settings": {
                    "application_name": f"pydyno_{self.name}",
                    "timezone": "utc",
                }
            }

            # Handle SSL configuration for asyncpg
            if "sslmode" in self.config:
                sslmode = self.config["sslmode"]
                if sslmode == "disable":
                    connect_args["ssl"] = False
                elif sslmode in ["require", "verify-ca", "verify-full"]:
                    connect_args["ssl"] = True
                elif sslmode == "prefer":
                    connect_args["ssl"] = "prefer"
                elif sslmode == "allow":
                    connect_args["ssl"] = "try"

            # Create async engine with connection pooling
            self._engine = create_async_engine(
                database_url,
                # Connection pool settings
                poolclass=AsyncAdaptedQueuePool,
                pool_size=self.pool_config.max_connections,
                max_overflow=self.pool_config.max_overflow,
                pool_pre_ping=self.pool_config.pool_pre_ping,
                pool_recycle=self.pool_config.pool_recycle,
                pool_timeout=self.pool_config.timeout,
                pool_reset_on_return="commit",
                # Logging
                echo=self.pool_config.echo,
                # Connection arguments for asyncpg
                connect_args=connect_args,  # ✅ Use the variable, not inline dict
            )

            # Remove event listeners for now (they cause async issues)
            # event.listen(self._engine.sync_engine, "connect", self._on_connect)
            # event.listen(self._engine.sync_engine, "checkout", self._on_checkout)

            # Create session factory
            self._session_factory = sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )

            # Test the connection
            await self._test_connection()

            self._initialized = True
            self.logger.info(
                f"PostgreSQL adapter '{self.name}' initialized successfully with "
                f"{self.pool_config.max_connections} max connections"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to initialize PostgreSQL adapter '{self.name}': {e}"
            )
            raise AdapterInitializationError(
                f"PostgreSQL initialization failed: {e}"
            ) from e

    async def _test_connection(self):
        """Test the database connection during initialization"""
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(text("SELECT 1"))
                test_value = result.scalar()
                if test_value != 1:
                    raise RuntimeError("Connection test failed: unexpected result")
            self.logger.debug("PostgreSQL connection test successful")
        except Exception as e:
            self.logger.error(f"PostgreSQL connection test failed: {e}")
            raise

    def _on_connect(self, dbapi_connection, connection_record):
        """Called when a new database connection is created"""
        self.logger.debug("New PostgreSQL connection established")
        # Don't try to execute SQL here with async connections
        # Handle extensions in application startup instead

    def _on_checkout(self, dbapi_connection, connection_record, connection_proxy):
        """Called when a connection is retrieved from the pool"""
        self.logger.debug("PostgreSQL connection checked out from pool")
        # Update active connections metric
        if hasattr(self._engine, "pool"):
            self.metrics.active_connections = self._engine.pool.checkedout()

    async def get_session(self) -> AsyncSession:
        """
        Get a new database session from the pool

        Returns:
            AsyncSession: A new SQLAlchemy async session

        Note:
            Remember to close the session when done, or use session_scope() context manager
        """
        await self._ensure_initialized()
        return self._session_factory()

    @asynccontextmanager
    async def session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Provide a transactional scope around a series of operations

        This context manager automatically handles:
        - Session creation and cleanup
        - Transaction commit on success
        - Transaction rollback on error
        - Metrics tracking

        Usage:
            async with adapter.session_scope() as session:
                result = await session.execute(text("SELECT * FROM users"))
                # Automatically commits on success, rolls back on error
        """
        start_time = self._record_operation_start()
        session = await self.get_session()

        try:
            yield session
            await session.commit()
            self._record_operation_success(start_time)

        except Exception as e:
            await session.rollback()
            self._record_operation_failure(start_time, e)
            raise

        finally:
            await session.close()

    async def execute_query(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Execute a raw SQL query

        Args:
            query: SQL query string
            params: Optional dictionary of query parameters

        Returns:
            Query result
        """
        start_time = self._record_operation_start()

        try:
            async with self.session_scope() as session:
                result = await session.execute(text(query), params or {})
                self._record_operation_success(start_time)
                return result

        except Exception as e:
            self._record_operation_failure(start_time, e)
            raise

    async def execute_scalar(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Execute a query and return a single scalar value

        Args:
            query: SQL query string
            params: Optional dictionary of query parameters

        Returns:
            Single scalar value from the query
        """
        result = await self.execute_query(query, params)
        return result.scalar()

    async def health_check(self) -> bool:
        """
        Check if PostgreSQL connection is healthy

        Performs a lightweight SELECT 1 query to test connectivity
        """
        try:
            await self._ensure_initialized()

            # Simple health check query
            result = await self.execute_scalar("SELECT 1")

            is_healthy = result == 1
            self.metrics.record_health_check(is_healthy)

            if is_healthy:
                self.logger.debug(
                    f"PostgreSQL adapter '{self.name}' health check passed"
                )
            else:
                self.logger.warning(
                    f"PostgreSQL adapter '{self.name}' health check failed: unexpected result"
                )

            return is_healthy

        except Exception as e:
            self.logger.error(
                f"PostgreSQL adapter '{self.name}' health check failed: {e}"
            )
            self.metrics.record_health_check(False)
            return False

    async def create_tables(self, base=None):
        """
        Create all tables defined in SQLAlchemy models

        Args:
            base: SQLAlchemy declarative base (defaults to the exported Base)
        """
        await self._ensure_initialized()

        target_base = base or Base
        self.logger.info(f"Creating database tables for adapter '{self.name}'...")

        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(target_base.metadata.create_all)

            self.logger.info(
                f"Database tables created successfully for adapter '{self.name}'"
            )

        except Exception as e:
            self.logger.error(f"Failed to create tables for adapter '{self.name}': {e}")
            raise

    async def drop_tables(self, base=None):
        """
        Drop all tables defined in SQLAlchemy models

        Args:
            base: SQLAlchemy declarative base (defaults to the exported Base)

        Warning:
            This will delete all data! Use with extreme caution.
        """
        await self._ensure_initialized()

        target_base = base or Base
        self.logger.warning(
            f"Dropping all database tables for adapter '{self.name}'..."
        )

        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(target_base.metadata.drop_all)

            self.logger.info(f"All tables dropped for adapter '{self.name}'")

        except Exception as e:
            self.logger.error(f"Failed to drop tables for adapter '{self.name}': {e}")
            raise

    async def get_connection_info(self) -> Dict[str, Any]:
        """Get detailed information about the PostgreSQL connection and pool"""
        if not self._initialized:
            return {"status": "not_initialized"}

        try:
            async with self.session_scope() as session:
                # Get PostgreSQL version
                version_result = await session.execute(text("SELECT version()"))
                version = version_result.scalar()

                # Get current database name
                db_result = await session.execute(text("SELECT current_database()"))
                current_db = db_result.scalar()

                # Get connection count for current database
                conn_count_result = await session.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                    )
                )
                connection_count = conn_count_result.scalar()

                # Pool information
                pool_info = {}
                if hasattr(self._engine, "pool"):
                    pool = self._engine.pool
                    pool_info = {
                        "pool_size": pool.size(),
                        "checked_out_connections": pool.checkedout(),
                        "overflow": pool.overflow(),
                        "checked_in": pool.checkedin(),
                    }

                return {
                    "status": "connected",
                    "database_name": current_db,
                    "postgresql_version": version,
                    "active_connections": connection_count,
                    "pool_info": pool_info,
                    "adapter_metrics": self.metrics.to_dict(),
                    "database_url_host": self.config.get("host", "from_url"),
                }

        except Exception as e:
            self.logger.error(
                f"Failed to get connection info for adapter '{self.name}': {e}"
            )
            return {"status": "error", "error": str(e)}

    async def close(self):
        """Close the PostgreSQL connection pool"""
        if self._closed:
            self.logger.debug(f"PostgreSQL adapter '{self.name}' already closed")
            return

        try:
            if self._engine:
                await self._engine.dispose()
                self.logger.info(
                    f"PostgreSQL engine disposed for adapter '{self.name}'"
                )

            self._engine = None
            self._session_factory = None
            self._closed = True

            self.logger.info(f"PostgreSQL adapter '{self.name}' closed successfully")

        except Exception as e:
            self.logger.error(f"Error closing PostgreSQL adapter '{self.name}': {e}")
            raise


# Convenience functions for creating PostgreSQL adapters


def create_postgresql_adapter(
    name: str,
    config: Optional[Dict[str, Any]] = None,
    pool_config: Optional[PoolConfig] = None,
) -> PostgreSQLAdapter:
    """
    Create a PostgreSQL adapter with optional environment variable fallbacks

    Args:
        name: Name for the adapter
        config: Database configuration (falls back to environment variables)
        pool_config: Pool configuration (uses defaults if not provided)

    Returns:
        Configured PostgreSQL adapter

    Environment Variables:
        POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD,
        POSTGRES_DB, DATABASE_URL
    """
    if config is None:
        # Try to build config from environment variables
        if "DATABASE_URL" in os.environ:
            config = {"url": os.environ["DATABASE_URL"]}
        else:
            config = {
                "host": os.environ.get("POSTGRES_HOST", "localhost"),
                "port": int(os.environ.get("POSTGRES_PORT", "5432")),
                "user": os.environ.get("POSTGRES_USER", ""),
                "password": os.environ.get("POSTGRES_PASSWORD", ""),
                "database": os.environ.get("POSTGRES_DB", ""),
            }

    if pool_config is None:
        pool_config = PoolConfig()

    return PostgreSQLAdapter(
        name=name, service_type="postgresql", config=config, pool_config=pool_config
    )


async def create_postgresql_adapter_from_env(
    name: str, pool_config: Optional[PoolConfig] = None
) -> PostgreSQLAdapter:
    """
    Create and initialize a PostgreSQL adapter from environment variables

    Args:
        name: Name for the adapter
        pool_config: Pool configuration (uses defaults if not provided)

    Returns:
        Initialized PostgreSQL adapter
    """
    adapter = create_postgresql_adapter(name, pool_config=pool_config)
    await adapter.initialize()
    return adapter
