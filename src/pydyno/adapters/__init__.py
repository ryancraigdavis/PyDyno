"""PyDyno Adapters

Connection adapters for various services and databases.
"""

# Always available
from pydyno.adapters.postgresql import PostgreSQLAdapter, create_postgresql_adapter

# Conditional imports based on optional dependencies
try:
    from pydyno.adapters.kafka import (
        KafkaAdapter, 
        KafkaMessage, 
        KafkaClientType,
        create_kafka_adapter,
        create_emby_kafka_adapter,
        create_kafka_adapter_from_env
    )
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

__all__ = [
    # PostgreSQL (always available)
    "PostgreSQLAdapter",
    "create_postgresql_adapter",
]

# Add Kafka exports if available
if KAFKA_AVAILABLE:
    __all__.extend([
        "KafkaAdapter",
        "KafkaMessage", 
        "KafkaClientType",
        "create_kafka_adapter",
        "create_emby_kafka_adapter",
        "create_kafka_adapter_from_env",
    ])