# Custom Exceptions
class PyDynoError(Exception):
    """Base exception for PyDyno errors"""

    pass


class PoolNotFoundError(PyDynoError):
    """Raised when trying to access a non-existent pool"""

    pass


class PoolAlreadyExistsError(PyDynoError):
    """Raised when trying to create a pool that already exists"""

    pass


class HealthCheckFailedError(PyDynoError):
    """Raised when health check consistently fails"""

    pass


class AdapterError(Exception):
    """Base exception for adapter-related errors"""

    pass


class AdapterInitializationError(AdapterError):
    """Raised when adapter initialization fails"""

    pass


class AdapterClosedError(AdapterError):
    """Raised when trying to use a closed adapter"""

    pass


class AdapterHealthCheckError(AdapterError):
    """Raised when health check fails consistently"""

    pass


class AdapterConfigurationError(AdapterError):
    """Raised when adapter configuration is invalid"""

    pass
