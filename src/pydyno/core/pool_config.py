from attrs import define, field


@define
class PoolConfig:
    """Configuration for connection pools with validation"""

    max_connections: int = field(default=10)
    min_connections: int = field(default=1)
    max_overflow: int = field(default=20)
    timeout: float = field(default=30.0)
    pool_recycle: int = field(default=3600)
    pool_pre_ping: bool = field(default=True)
    echo: bool = field(default=False)
    retry_attempts: int = field(default=3)
    health_check_interval: float = field(default=60.0)

    def __attrs_post_init__(self):
        """Validation after all fields are set"""
        if self.max_connections < 1:
            raise ValueError("max_connections must be at least 1")

        if self.min_connections < 0:
            raise ValueError("min_connections cannot be negative")

        if self.min_connections > self.max_connections:
            raise ValueError("min_connections cannot exceed max_connections")

        if self.timeout <= 0:
            raise ValueError("timeout must be positive")

        if self.pool_recycle <= 0:
            raise ValueError("pool_recycle must be positive")

        if self.retry_attempts < 0:
            raise ValueError("retry_attempts cannot be negative")

        if self.health_check_interval <= 0:
            raise ValueError("health_check_interval must be positive")
