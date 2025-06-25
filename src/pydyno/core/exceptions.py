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


class AdapterNotInitializedError(PyDynoError):
    """Raised when trying to use an uninitialized adapter"""

    pass


class HealthCheckFailedError(PyDynoError):
    """Raised when health check consistently fails"""

    pass
