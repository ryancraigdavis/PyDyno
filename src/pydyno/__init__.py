"""
PyDyno - Unified Connection Pooling for Python

A modern, async-first connection pooling library inspired by Netflix's Dyno.
"""

from pydyno.core.manager import PyDyno, get_global_dyno, set_global_dyno, close_global_dyno
from pydyno.core.pool_config import PoolConfig
from pydyno.core.utils import ConnectionMetrics
from pydyno.core.exceptions import (
    PyDynoError,
    PoolNotFoundError, 
    PoolAlreadyExistsError,
    HealthCheckFailedError,
    AdapterError,
    AdapterInitializationError,
    AdapterClosedError,
    AdapterHealthCheckError,
    AdapterConfigurationError
)

__version__ = "0.1.3"

__all__ = [
    # Core classes
    "PyDyno",
    "PoolConfig", 
    "ConnectionMetrics",
    
    # Global instance management
    "get_global_dyno",
    "set_global_dyno", 
    "close_global_dyno",
    
    # Exceptions
    "PyDynoError",
    "PoolNotFoundError",
    "PoolAlreadyExistsError", 
    "HealthCheckFailedError",
    "AdapterError",
    "AdapterInitializationError",
    "AdapterClosedError",
    "AdapterHealthCheckError",
    "AdapterConfigurationError",
]