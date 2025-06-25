"""Core manager for Pydyno."""

import asyncio
import logging
from typing import Dict, Any, Optional, Union
from attrs import define, field

from pydyno.core.adapters import ConnectionAdapter
from pydyno.core.utils import ConnectionMetrics
from pydyno.core.exceptions import PoolAlreadyExistsError, PoolNotFoundError
from pydyno.core.pool_config import PoolConfig


# Main Manager Class
@define
class PyDyno:
    """
    PyDyno - Unified Connection Pool Manager

    A connection pooling library inspired by Netflix's Dyno, providing a unified
    interface for managing connections to various services like PostgreSQL, Redis, HTTP APIs.

    Example:
        >>> dyno = PyDyno()
        >>> await dyno.create_pool("db", "postgresql", config, pool_config)
        >>> async with dyno.get_connection("db") as conn:
        ...     result = await conn.execute("SELECT 1")
    """

    # Configuration
    enable_health_monitoring: bool = field(default=True)
    health_check_interval: float = field(default=60.0)
    max_consecutive_failures: int = field(default=3)

    # Internal state (not part of init)
    _pools: Dict[str, ConnectionAdapter] = field(factory=dict, init=False)
    _health_monitor_task: Optional[asyncio.Task] = field(default=None, init=False)
    _running: bool = field(default=False, init=False)
    _logger: logging.Logger = field(init=False)

    def __attrs_post_init__(self):
        """Post-initialization setup"""
        self._logger = logging.getLogger("pydyno.manager")
        self._logger.info("PyDyno manager initialized")

    async def create_pool(
        self, name: str, adapter: ConnectionAdapter, auto_initialize: bool = True
    ) -> ConnectionAdapter:
        """Create a new connection pool with the given adapter
        Args:
            name: Unique name for the pool
            adapter: Pre-configured connection adapter
            auto_initialize: Whether to initialize the adapter immediately
        Returns:
            The initialized connection adapter
        Raises:
            PoolAlreadyExistsError: If pool name already exists
        """
        if name in self._pools:
            raise PoolAlreadyExistsError(f"Pool '{name}' already exists")

        if auto_initialize:
            await adapter.initialize()

        self._pools[name] = adapter

        # Start health monitoring if enabled and not already running
        if self.enable_health_monitoring and not self._running:
            await self._start_health_monitoring()

        self._logger.info(
            f"Created {adapter.service_type} pool '{name}' with "
            f"{adapter.pool_config.max_connections} max connections"
        )

        return adapter

    def get_pool(self, name: str) -> ConnectionAdapter:
        """Get an existing connection pool"""
        if name not in self._pools:
            available = list(self._pools.keys())
            raise PoolNotFoundError(
                f"Pool '{name}' not found. Available pools: {available}"
            )
        return self._pools[name]

    def list_pools(self) -> Dict[str, str]:
        """List all available pools and their service types"""
        return {name: adapter.service_type for name, adapter in self._pools.items()}

    async def health_check(self, pool_name: Optional[str] = None) -> Dict[str, bool]:
        """Check health of specific pool or all pools"""
        if pool_name:
            pool = self.get_pool(pool_name)
            await pool._ensure_initialized()
            is_healthy = await pool.health_check()
            pool.metrics.record_health_check(is_healthy)
            return {pool_name: is_healthy}
        else:
            results = {}
            for name, pool in self._pools.items():
                try:
                    await pool._ensure_initialized()
                    is_healthy = await pool.health_check()
                    pool.metrics.record_health_check(is_healthy)
                    results[name] = is_healthy
                except Exception as e:
                    self._logger.error(f"Health check failed for pool '{name}': {e}")
                    pool.metrics.record_health_check(False)
                    results[name] = False
            return results

    async def get_metrics(
        self, pool_name: Optional[str] = None
    ) -> Union[ConnectionMetrics, Dict[str, ConnectionMetrics]]:
        """Get metrics for specific pool or all pools"""
        if pool_name:
            pool = self.get_pool(pool_name)
            return pool.metrics
        else:
            return {name: pool.metrics for name, pool in self._pools.items()}

    async def get_metrics_dict(
        self, pool_name: Optional[str] = None
    ) -> Union[Dict[str, Any], Dict[str, Dict[str, Any]]]:
        """Get metrics as dictionaries for JSON serialization"""
        if pool_name:
            pool = self.get_pool(pool_name)
            return pool.metrics.to_dict()
        else:
            return {name: pool.metrics.to_dict() for name, pool in self._pools.items()}

    async def _start_health_monitoring(self):
        """Start background health monitoring task"""
        if self._running:
            return

        self._running = True
        self._health_monitor_task = asyncio.create_task(self._health_monitor_loop())
        self._logger.info("Health monitoring started")

    async def _health_monitor_loop(self):
        """Background task for health monitoring"""
        while self._running:
            try:
                health_results = await self.health_check()

                # Log unhealthy pools
                for pool_name, is_healthy in health_results.items():
                    if not is_healthy:
                        pool = self._pools[pool_name]
                        failures = pool.metrics.consecutive_failures

                        if failures >= self.max_consecutive_failures:
                            self._logger.critical(
                                f"Pool '{pool_name}' has failed {failures} consecutive health checks"
                            )
                        else:
                            self._logger.warning(
                                f"Pool '{pool_name}' health check failed"
                            )

                # Wait for next health check
                await asyncio.sleep(self.health_check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error in health monitor loop: {e}")
                await asyncio.sleep(self.health_check_interval)

    async def close_pool(self, name: str):
        """Close a specific connection pool"""
        if name not in self._pools:
            self._logger.warning(f"Attempted to close non-existent pool '{name}'")
            return

        pool = self._pools[name]
        try:
            await pool.close()
            del self._pools[name]
            self._logger.info(f"Closed pool '{name}'")
        except Exception as e:
            self._logger.error(f"Error closing pool '{name}': {e}")
            raise

    async def close_all(self):
        """Close all connection pools and stop health monitoring"""
        # Stop health monitoring
        self._running = False
        if self._health_monitor_task:
            self._health_monitor_task.cancel()
            try:
                await self._health_monitor_task
            except asyncio.CancelledError:
                pass
            self._health_monitor_task = None

        # Close all pools
        pool_names = list(self._pools.keys())
        for name in pool_names:
            try:
                await self.close_pool(name)
            except Exception as e:
                self._logger.error(f"Error closing pool '{name}': {e}")

        self._logger.info("All pools closed and health monitoring stopped")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - automatically close all pools"""
        await self.close_all()

    def __repr__(self) -> str:
        pool_count = len(self._pools)
        pool_names = list(self._pools.keys())
        return f"PyDyno(pools={pool_count}, names={pool_names})"


# Convenience function for global instance management
_global_dyno: Optional[PyDyno] = None


def get_global_dyno() -> PyDyno:
    """Get the global PyDyno instance"""
    global _global_dyno
    if _global_dyno is None:
        _global_dyno = PyDyno()
    return _global_dyno


def set_global_dyno(dyno: PyDyno):
    """Set the global PyDyno instance"""
    global _global_dyno
    _global_dyno = dyno


async def close_global_dyno():
    """Close the global PyDyno instance if it exists"""
    global _global_dyno
    if _global_dyno is not None:
        await _global_dyno.close_all()
        _global_dyno = None
