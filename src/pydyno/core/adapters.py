"""Core adapter classes for PyDyno"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

import attrs
from attrs import define, field

from pydyno.core.utils import ConnectionMetrics
from pydyno.core.pool_config import PoolConfig


@define
class ConnectionAdapter(ABC):
    """Abstract base class for service-specific connection adapters
    All concrete adapters (PostgreSQL, Redis, HTTP, etc.) should inherit from this class.
    Provides common functionality like metrics tracking, health monitoring, and logging.
    """

    name: str = field()
    service_type: str = field()
    config: Dict[str, Any] = field()
    pool_config: PoolConfig = field()
    # Runtime state (mutable, managed internally)
    metrics: ConnectionMetrics = field(init=False)
    logger: logging.Logger = field(init=False)
    _initialized: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)

    def __attrs_post_init__(self):
        """Post-initialization setup called by attrs after __init__"""
        # Validation first
        self._validate_fields()

        # Create metrics instance for this adapter
        self.metrics = ConnectionMetrics(
            pool_name=self.name, service_type=self.service_type
        )

        # Set up structured logger
        self.logger = logging.getLogger(
            f"pydyno.adapters.{self.service_type}.{self.name}"
        )

        self.logger.debug(f"Created {self.service_type} adapter '{self.name}'")

    def _validate_fields(self):
        """Validate all fields after initialization"""
        # Validate name
        if not self.name or not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Adapter name must be a non-empty string")

        # Validate service_type
        if (
            not self.service_type
            or not isinstance(self.service_type, str)
            or not self.service_type.strip()
        ):
            raise ValueError("Service type must be a non-empty string")

        # Validate config
        if not isinstance(self.config, dict):
            raise ValueError("Config must be a dictionary")

        # Validate pool_config
        if not isinstance(self.pool_config, PoolConfig):
            raise ValueError("pool_config must be a PoolConfig instance")

    # Abstract methods that subclasses must implement
    @abstractmethod
    async def initialize(self):
        """
        Initialize the connection pool

        This method should:
        1. Set up the actual connection pool (Redis, PostgreSQL, etc.)
        2. Perform any necessary authentication or setup
        3. Set self._initialized = True on success
        4. Log successful initialization

        Raises:
            Exception: If initialization fails for any reason

        Note:
            This method should be idempotent - safe to call multiple times.
            If already initialized, it should return immediately.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the service is healthy and reachable

        This method should:
        1. Perform a lightweight operation to test connectivity
        2. Update metrics by calling self.metrics.record_health_check(result)
        3. Return True if healthy, False otherwise
        4. Log health check results

        Returns:
            bool: True if service is healthy and reachable, False otherwise

        Note:
            Should be fast and lightweight - avoid expensive operations.
            This method is called regularly by the health monitoring system.
        """
        pass

    @abstractmethod
    async def close(self):
        """
        Close all connections in the pool and clean up resources

        This method should:
        1. Close/dispose of the connection pool
        2. Clean up any resources (file handles, network connections, etc.)
        3. Set self._closed = True
        4. Log successful closure

        Note:
            Should be idempotent - safe to call multiple times.
            If already closed, it should return immediately.
        """
        pass

    # Concrete methods provided by base class
    def is_initialized(self) -> bool:
        """
        Check if adapter has been initialized

        Returns:
            bool: True if initialize() has been called successfully
        """
        return self._initialized

    def is_closed(self) -> bool:
        """
        Check if adapter has been closed

        Returns:
            bool: True if close() has been called
        """
        return self._closed

    def is_healthy(self) -> bool:
        """
        Check if adapter is currently healthy (based on last health check)

        Returns:
            bool: True if last health check was successful
        """
        return self.metrics.health_status

    def get_consecutive_failures(self) -> int:
        """
        Get number of consecutive failures

        Returns:
            int: Number of consecutive health check failures
        """
        return self.metrics.consecutive_failures

    async def _ensure_initialized(self):
        """
        Ensure adapter is initialized and ready for use

        This method:
        1. Checks if adapter is closed (raises RuntimeError if so)
        2. Calls initialize() if not already initialized
        3. Handles initialization errors gracefully

        Raises:
            RuntimeError: If adapter is closed or initialization fails
        """
        if self._closed:
            raise RuntimeError(
                f"Adapter '{self.name}' has been closed and cannot be used"
            )

        if not self._initialized:
            try:
                self.logger.debug(f"Auto-initializing adapter '{self.name}'")
                await self.initialize()
            except Exception as e:
                self.logger.error(f"Failed to initialize adapter '{self.name}': {e}")
                raise RuntimeError(
                    f"Adapter '{self.name}' initialization failed: {e}"
                ) from e

    def _record_operation_start(self) -> float:
        """
        Record the start of an operation and return start time

        This method updates metrics and should be called at the beginning
        of any operation that you want to track performance for.

        Returns:
            float: Start time timestamp for timing the operation
        """
        return self.metrics.record_request_start()

    def _record_operation_success(self, start_time: float):
        """
        Record successful completion of an operation

        Args:
            start_time: Start time returned by _record_operation_start()
        """
        self.metrics.record_request_success(start_time)
        self.logger.debug(
            f"Operation completed successfully in {self.metrics.average_response_time:.3f}s"
        )

    def _record_operation_failure(
        self, start_time: float, error: Optional[Exception] = None
    ):
        """
        Record failed completion of an operation

        Args:
            start_time: Start time returned by _record_operation_start()
            error: Optional exception that caused the failure
        """
        self.metrics.record_request_failure(start_time)
        if error:
            self.logger.warning(f"Operation failed: {error}")
        else:
            self.logger.warning("Operation failed")

    async def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status information about this adapter

        Returns:
            Dictionary containing:
            - Basic adapter info (name, service_type, status)
            - Configuration info (without sensitive values)
            - Pool configuration
            - Current metrics
            - Health status
        """
        return {
            "name": self.name,
            "service_type": self.service_type,
            "initialized": self.is_initialized(),
            "closed": self.is_closed(),
            "healthy": self.is_healthy(),
            "consecutive_failures": self.get_consecutive_failures(),
            "config_keys": list(
                self.config.keys()
            ),  # Don't expose sensitive config values
            "pool_config": attrs.asdict(self.pool_config),
            "metrics": self.metrics.to_dict(),
        }

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Safely get a configuration value

        Args:
            key: Configuration key to retrieve
            default: Default value if key doesn't exist

        Returns:
            Configuration value or default
        """
        return self.config.get(key, default)

    def has_config(self, key: str) -> bool:
        """
        Check if a configuration key exists

        Args:
            key: Configuration key to check

        Returns:
            bool: True if key exists in configuration
        """
        return key in self.config

    def __repr__(self) -> str:
        """
        String representation of the adapter

        Returns:
            Human-readable string describing the adapter
        """
        if self._closed:
            status = "closed"
        elif self._initialized:
            status = "initialized"
        else:
            status = "uninitialized"

        return (
            f"{self.__class__.__name__}("
            f"name='{self.name}', "
            f"service_type='{self.service_type}', "
            f"status='{status}'"
            f")"
        )
