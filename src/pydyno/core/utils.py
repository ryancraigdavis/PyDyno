import time
from attrs import define, field
from typing import Dict, Any, Optional


@define
class ConnectionMetrics:
    """Metrics for monitoring connection pool performance"""

    pool_name: str = field()
    service_type: str = field()

    # Request metrics
    total_requests: int = field(default=0, init=False)
    successful_requests: int = field(default=0, init=False)
    failed_requests: int = field(default=0, init=False)

    # Timing metrics
    average_response_time: float = field(default=0.0, init=False)
    total_response_time: float = field(default=0.0, init=False)

    # Connection metrics
    active_connections: int = field(default=0, init=False)
    idle_connections: int = field(default=0, init=False)

    # Health metrics
    last_health_check: float = field(factory=time.time, init=False)
    health_status: bool = field(default=True, init=False)
    consecutive_failures: int = field(default=0, init=False)

    # Timestamps
    created_at: float = field(factory=time.time, init=False)
    last_request_at: Optional[float] = field(default=None, init=False)

    def record_request_start(self) -> float:
        """Record start of a request and return start time"""
        start_time = time.time()
        self.total_requests += 1
        self.last_request_at = start_time
        return start_time

    def record_request_success(self, start_time: float):
        """Record successful completion of a request"""
        response_time = time.time() - start_time
        self.successful_requests += 1
        self.total_response_time += response_time

        # Update average response time
        if self.successful_requests > 0:
            self.average_response_time = (
                self.total_response_time / self.successful_requests
            )

        # Reset consecutive failures on success
        self.consecutive_failures = 0

    def record_request_failure(self, start_time: float):
        """Record failed completion of a request"""
        self.failed_requests += 1
        self.consecutive_failures += 1

    def record_health_check(self, is_healthy: bool):
        """Record result of health check"""
        self.health_status = is_healthy
        self.last_health_check = time.time()
        if is_healthy:
            self.consecutive_failures = 0

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100.0

    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as percentage"""
        return 100.0 - self.success_rate

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for serialization"""
        return {
            "pool_name": self.pool_name,
            "service_type": self.service_type,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "average_response_time": self.average_response_time,
            "active_connections": self.active_connections,
            "idle_connections": self.idle_connections,
            "health_status": self.health_status,
            "consecutive_failures": self.consecutive_failures,
            "last_health_check": self.last_health_check,
            "created_at": self.created_at,
            "last_request_at": self.last_request_at,
        }
