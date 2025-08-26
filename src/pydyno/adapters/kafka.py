"""Kafka Connection Adapter for PyDyno"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Union, AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum

try:
    from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
    from aiokafka.errors import KafkaError
    from kafka import TopicPartition
    AIOKAFKA_AVAILABLE = True
except ImportError:
    AIOKAFKA_AVAILABLE = False
    AIOKafkaProducer = None
    AIOKafkaConsumer = None
    KafkaError = Exception
    TopicPartition = None

from pydyno.core.adapters import ConnectionAdapter
from pydyno.core.pool_config import PoolConfig
from pydyno.core.exceptions import AdapterInitializationError, AdapterConfigurationError


class KafkaClientType(Enum):
    """Kafka client types supported by the adapter"""
    PRODUCER = "producer"
    CONSUMER = "consumer" 
    BOTH = "both"


@dataclass
class KafkaMessage:
    """Wrapper for Kafka message data"""
    topic: str
    key: Optional[bytes] = None
    value: Optional[bytes] = None
    partition: Optional[int] = None
    offset: Optional[int] = None
    timestamp: Optional[int] = None
    headers: Optional[Dict[str, bytes]] = None


class KafkaAdapter(ConnectionAdapter):
    """
    Kafka connection adapter using aiokafka
    
    This adapter manages Kafka producer and consumer connections with connection pooling,
    health monitoring, and metrics collection. Perfect for real-time streaming applications
    like Emby recommendation services.
    
    Example for Emby recommendation service:
        config = {
            'bootstrap_servers': ['localhost:9092'],
            'client_type': 'both',
            'producer_config': {
                'acks': 'all',
                'retries': 3,
                'batch_size': 16384,
                'compression_type': 'gzip'
            },
            'consumer_config': {
                'group_id': 'emby-recommendations',
                'auto_offset_reset': 'latest',
                'enable_auto_commit': True
            },
            'topics': ['emby.events', 'emby.user_activity']
        }
        
        adapter = KafkaAdapter(
            name="emby_kafka",
            service_type="kafka",
            config=config,
            pool_config=PoolConfig(max_connections=5)
        )
        
        # Produce messages (from Emby plugin events)
        await adapter.send_message("emby.events", {"event": "play", "user_id": 123})
        
        # Consume messages (for recommendation processing)
        async with adapter.consume_messages(["emby.events"]) as consumer:
            async for message in consumer:
                await process_emby_event(message.value)
    """

    def __init__(
        self,
        name: str,
        service_type: str,
        config: Dict[str, Any],
        pool_config: PoolConfig,
    ):
        # Check if aiokafka is available
        if not AIOKAFKA_AVAILABLE:
            raise AdapterInitializationError(
                "aiokafka is required for Kafka adapter. Install with: pip install aiokafka"
            )
            
        # Validate Kafka-specific configuration
        self._validate_kafka_config(config)
        
        super().__init__(name, service_type, config, pool_config)
        
        # Kafka-specific attributes
        self._client_type = KafkaClientType(config.get('client_type', 'both'))
        self._producers: List[AIOKafkaProducer] = []
        self._consumers: List[AIOKafkaConsumer] = []
        self._producer_pool_index = 0
        self._consumer_pool_index = 0
        self._lock = asyncio.Lock()
        
        # Background tasks
        self._producer_tasks: List[asyncio.Task] = []
        self._consumer_tasks: List[asyncio.Task] = []

    def _validate_kafka_config(self, config: Dict[str, Any]):
        """Validate Kafka-specific configuration"""
        # Bootstrap servers are required
        if 'bootstrap_servers' not in config:
            raise AdapterConfigurationError(
                "Kafka configuration must include 'bootstrap_servers'"
            )
            
        bootstrap_servers = config['bootstrap_servers']
        if not isinstance(bootstrap_servers, (list, str)):
            raise AdapterConfigurationError(
                "bootstrap_servers must be a string or list of strings"
            )
            
        # Validate client type
        client_type = config.get('client_type', 'both')
        if client_type not in [e.value for e in KafkaClientType]:
            raise AdapterConfigurationError(
                f"client_type must be one of: {[e.value for e in KafkaClientType]}"
            )
            
        # For consumers, group_id should be specified
        if client_type in ['consumer', 'both']:
            consumer_config = config.get('consumer_config', {})
            if not consumer_config.get('group_id'):
                self.logger.warning(
                    "No group_id specified in consumer_config. "
                    "Consider setting one for proper consumer group coordination."
                )

    async def initialize(self):
        """Initialize Kafka producer and consumer pools"""
        if self._initialized:
            self.logger.debug(f"Kafka adapter '{self.name}' already initialized")
            return

        try:
            self.logger.info(f"Initializing Kafka adapter '{self.name}'...")
            
            # Initialize producers if needed
            if self._client_type in [KafkaClientType.PRODUCER, KafkaClientType.BOTH]:
                await self._initialize_producers()
                
            # Initialize consumers if needed  
            if self._client_type in [KafkaClientType.CONSUMER, KafkaClientType.BOTH]:
                await self._initialize_consumers()
                
            # Test connectivity
            await self._test_connectivity()
            
            self._initialized = True
            self.logger.info(
                f"Kafka adapter '{self.name}' initialized successfully with "
                f"{len(self._producers)} producers, {len(self._consumers)} consumers"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Kafka adapter '{self.name}': {e}")
            raise AdapterInitializationError(f"Kafka initialization failed: {e}") from e

    async def _initialize_producers(self):
        """Initialize Kafka producer pool"""
        producer_config = self.config.get('producer_config', {})
        bootstrap_servers = self.config['bootstrap_servers']
        
        # Default producer configuration optimized for reliability
        default_producer_config = {
            'acks': 'all',  # Wait for all replicas
            'retries': 3,
            'batch_size': 16384,
            'linger_ms': 10,  # Small batching delay
            'compression_type': 'gzip',
            'max_in_flight_requests_per_connection': 5,
            'enable_idempotence': True,  # Prevent duplicates
        }
        
        # Merge user config with defaults
        final_producer_config = {**default_producer_config, **producer_config}
        
        # Create producer pool
        for i in range(self.pool_config.max_connections):
            producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                **final_producer_config
            )
            
            self._producers.append(producer)
            self.logger.debug(f"Created Kafka producer {i+1}/{self.pool_config.max_connections}")

    async def _initialize_consumers(self):
        """Initialize Kafka consumer pool"""
        consumer_config = self.config.get('consumer_config', {})
        bootstrap_servers = self.config['bootstrap_servers']
        
        # Default consumer configuration optimized for reliability
        default_consumer_config = {
            'auto_offset_reset': 'latest',
            'enable_auto_commit': True,
            'auto_commit_interval_ms': 5000,
            'session_timeout_ms': 30000,
            'heartbeat_interval_ms': 10000,
            'max_poll_records': 500,
            'consumer_timeout_ms': 1000,
        }
        
        # Merge user config with defaults
        final_consumer_config = {**default_consumer_config, **consumer_config}
        
        # Create consumer pool (typically fewer consumers than producers)
        consumer_pool_size = max(1, self.pool_config.max_connections // 2)
        
        for i in range(consumer_pool_size):
            # Create consumer with unique group_id if multiple consumers
            config_copy = final_consumer_config.copy()
            if consumer_pool_size > 1 and 'group_id' in config_copy:
                config_copy['group_id'] = f"{config_copy['group_id']}-{i}"
            
            consumer = AIOKafkaConsumer(
                bootstrap_servers=bootstrap_servers,
                **config_copy
            )
            
            self._consumers.append(consumer)
            self.logger.debug(f"Created Kafka consumer {i+1}/{consumer_pool_size}")

    async def _test_connectivity(self):
        """Test Kafka connectivity"""
        try:
            # Test producer connectivity if available
            if self._producers:
                producer = self._producers[0]
                await producer.start()
                
                # Get cluster metadata as connectivity test
                metadata = await producer.client.fetch_metadata()
                if not metadata.brokers:
                    raise RuntimeError("No Kafka brokers available")
                    
                await producer.stop()
                self.logger.debug("Producer connectivity test successful")
                
            # Test consumer connectivity if available
            if self._consumers:
                consumer = self._consumers[0]
                await consumer.start()
                
                # Getting cluster metadata tests connectivity
                await consumer.getmany(timeout_ms=100)  # Quick poll test
                await consumer.stop()
                self.logger.debug("Consumer connectivity test successful")
                
        except Exception as e:
            self.logger.error(f"Kafka connectivity test failed: {e}")
            raise

    async def _get_producer(self) -> AIOKafkaProducer:
        """Get a producer from the pool using round-robin"""
        if not self._producers:
            raise RuntimeError("No producers available. Check client_type configuration.")
            
        async with self._lock:
            producer = self._producers[self._producer_pool_index]
            self._producer_pool_index = (self._producer_pool_index + 1) % len(self._producers)
            
            # Start producer if not already started
            if not producer._closed:
                if not hasattr(producer, '_started') or not producer._started:
                    await producer.start()
                    producer._started = True
                    
            return producer

    async def _get_consumer(self) -> AIOKafkaConsumer:
        """Get a consumer from the pool using round-robin"""
        if not self._consumers:
            raise RuntimeError("No consumers available. Check client_type configuration.")
            
        async with self._lock:
            consumer = self._consumers[self._consumer_pool_index]
            self._consumer_pool_index = (self._consumer_pool_index + 1) % len(self._consumers)
            
            # Start consumer if not already started
            if not consumer._closed:
                if not hasattr(consumer, '_started') or not consumer._started:
                    await consumer.start()
                    consumer._started = True
                    
            return consumer

    async def send_message(
        self, 
        topic: str, 
        value: Any, 
        key: Optional[Any] = None,
        partition: Optional[int] = None,
        headers: Optional[Dict[str, bytes]] = None
    ) -> Dict[str, Any]:
        """
        Send a message to a Kafka topic
        
        Args:
            topic: Kafka topic name
            value: Message value (will be JSON-serialized if not bytes)
            key: Optional message key
            partition: Optional specific partition
            headers: Optional message headers
            
        Returns:
            Dictionary with send metadata (topic, partition, offset)
        """
        start_time = self._record_operation_start()
        
        try:
            await self._ensure_initialized()
            producer = await self._get_producer()
            
            # Serialize value and key if needed
            if isinstance(value, (dict, list)):
                import json
                value = json.dumps(value).encode('utf-8')
            elif isinstance(value, str):
                value = value.encode('utf-8')
                
            if key is not None and isinstance(key, str):
                key = key.encode('utf-8')
            
            # Send message
            future = await producer.send(
                topic=topic,
                value=value,
                key=key,
                partition=partition,
                headers=headers
            )
            
            # Wait for confirmation
            record_metadata = await future
            
            result = {
                'topic': record_metadata.topic,
                'partition': record_metadata.partition,
                'offset': record_metadata.offset,
                'timestamp': record_metadata.timestamp,
            }
            
            self._record_operation_success(start_time)
            self.logger.debug(
                f"Sent message to {topic}:{record_metadata.partition}@{record_metadata.offset}"
            )
            
            return result
            
        except Exception as e:
            self._record_operation_failure(start_time, e)
            raise

    async def send_batch(
        self, 
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Send multiple messages in batch
        
        Args:
            messages: List of message dictionaries with 'topic', 'value', and optional 'key'
            
        Returns:
            List of send metadata dictionaries
        """
        start_time = self._record_operation_start()
        
        try:
            await self._ensure_initialized()
            producer = await self._get_producer()
            
            # Send all messages asynchronously
            futures = []
            for msg in messages:
                topic = msg['topic']
                value = msg['value']
                key = msg.get('key')
                partition = msg.get('partition')
                headers = msg.get('headers')
                
                # Serialize if needed
                if isinstance(value, (dict, list)):
                    import json
                    value = json.dumps(value).encode('utf-8')
                elif isinstance(value, str):
                    value = value.encode('utf-8')
                    
                if key is not None and isinstance(key, str):
                    key = key.encode('utf-8')
                
                future = await producer.send(
                    topic=topic,
                    value=value,
                    key=key,
                    partition=partition,
                    headers=headers
                )
                futures.append(future)
            
            # Wait for all confirmations
            results = []
            for future in futures:
                record_metadata = await future
                results.append({
                    'topic': record_metadata.topic,
                    'partition': record_metadata.partition,
                    'offset': record_metadata.offset,
                    'timestamp': record_metadata.timestamp,
                })
            
            self._record_operation_success(start_time)
            self.logger.debug(f"Sent batch of {len(messages)} messages")
            
            return results
            
        except Exception as e:
            self._record_operation_failure(start_time, e)
            raise

    @asynccontextmanager
    async def consume_messages(
        self, 
        topics: List[str],
        timeout_ms: int = 1000
    ) -> AsyncGenerator[AIOKafkaConsumer, None]:
        """
        Consume messages from Kafka topics using async context manager
        
        Args:
            topics: List of topics to consume from
            timeout_ms: Consumer timeout in milliseconds
            
        Usage:
            async with adapter.consume_messages(['emby.events']) as consumer:
                async for message in consumer:
                    print(f"Received: {message.value}")
        """
        await self._ensure_initialized()
        consumer = await self._get_consumer()
        
        try:
            # Subscribe to topics
            consumer.subscribe(topics)
            self.logger.debug(f"Subscribed to topics: {topics}")
            
            yield consumer
            
        finally:
            # Unsubscribe to clean up
            consumer.unsubscribe()

    async def consume_single_message(
        self, 
        topics: List[str], 
        timeout_ms: int = 5000
    ) -> Optional[KafkaMessage]:
        """
        Consume a single message from topics
        
        Args:
            topics: List of topics to consume from  
            timeout_ms: Timeout for message consumption
            
        Returns:
            KafkaMessage object or None if timeout
        """
        start_time = self._record_operation_start()
        
        try:
            async with self.consume_messages(topics, timeout_ms) as consumer:
                msg_dict = await consumer.getone()
                
                if msg_dict:
                    message = KafkaMessage(
                        topic=msg_dict.topic,
                        key=msg_dict.key,
                        value=msg_dict.value,
                        partition=msg_dict.partition,
                        offset=msg_dict.offset,
                        timestamp=msg_dict.timestamp,
                        headers=dict(msg_dict.headers) if msg_dict.headers else None
                    )
                    
                    self._record_operation_success(start_time)
                    return message
                else:
                    return None
                    
        except Exception as e:
            self._record_operation_failure(start_time, e)
            raise

    async def get_topic_metadata(self, topic: str) -> Dict[str, Any]:
        """
        Get metadata for a specific topic
        
        Args:
            topic: Topic name
            
        Returns:
            Dictionary with topic metadata
        """
        await self._ensure_initialized()
        
        if self._producers:
            producer = self._producers[0]
            if not hasattr(producer, '_started') or not producer._started:
                await producer.start()
                producer._started = True
                
            metadata = await producer.client.fetch_metadata([topic])
            topic_metadata = metadata.topics.get(topic)
            
            if topic_metadata:
                return {
                    'topic': topic,
                    'partitions': len(topic_metadata.partitions),
                    'partition_info': [
                        {
                            'partition': p_id,
                            'leader': partition.leader,
                            'replicas': partition.replicas,
                            'isr': partition.isr
                        }
                        for p_id, partition in topic_metadata.partitions.items()
                    ]
                }
            else:
                raise ValueError(f"Topic '{topic}' not found")
        else:
            raise RuntimeError("No producers available to fetch metadata")

    async def health_check(self) -> bool:
        """Check Kafka connection health"""
        try:
            await self._ensure_initialized()
            
            # Test producer health
            if self._producers:
                producer = self._producers[0]
                if not hasattr(producer, '_started') or not producer._started:
                    await producer.start()
                    producer._started = True
                    
                # Fetch cluster metadata as health check
                metadata = await producer.client.fetch_metadata()
                if not metadata.brokers:
                    self.logger.warning("No Kafka brokers available")
                    self.metrics.record_health_check(False)
                    return False
            
            # Test consumer health  
            if self._consumers:
                consumer = self._consumers[0]
                if not hasattr(consumer, '_started') or not consumer._started:
                    await consumer.start()  
                    consumer._started = True
                    
                # Quick poll to test consumer health
                await consumer.getmany(timeout_ms=100)
            
            self.metrics.record_health_check(True)
            self.logger.debug(f"Kafka adapter '{self.name}' health check passed")
            return True
            
        except Exception as e:
            self.logger.error(f"Kafka adapter '{self.name}' health check failed: {e}")
            self.metrics.record_health_check(False)
            return False

    async def get_connection_info(self) -> Dict[str, Any]:
        """Get detailed information about Kafka connections"""
        if not self._initialized:
            return {"status": "not_initialized"}
            
        try:
            info = {
                "status": "connected",
                "client_type": self._client_type.value,
                "producer_count": len(self._producers),
                "consumer_count": len(self._consumers),
                "bootstrap_servers": self.config['bootstrap_servers'],
            }
            
            # Add cluster info if available
            if self._producers:
                producer = self._producers[0]
                if hasattr(producer, '_started') and producer._started:
                    metadata = await producer.client.fetch_metadata()
                    info.update({
                        "broker_count": len(metadata.brokers),
                        "brokers": [f"{b.host}:{b.port}" for b in metadata.brokers],
                        "topics_count": len(metadata.topics),
                    })
            
            info["adapter_metrics"] = self.metrics.to_dict()
            return info
            
        except Exception as e:
            self.logger.error(f"Failed to get connection info for adapter '{self.name}': {e}")
            return {"status": "error", "error": str(e)}

    async def close(self):
        """Close all Kafka connections"""
        if self._closed:
            self.logger.debug(f"Kafka adapter '{self.name}' already closed")
            return
            
        try:
            # Cancel background tasks
            for task in self._producer_tasks + self._consumer_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            
            # Close all producers
            for producer in self._producers:
                if hasattr(producer, '_started') and producer._started:
                    await producer.stop()
            
            # Close all consumers  
            for consumer in self._consumers:
                if hasattr(consumer, '_started') and consumer._started:
                    await consumer.stop()
            
            self._producers.clear()
            self._consumers.clear()
            self._producer_tasks.clear()
            self._consumer_tasks.clear()
            
            self._closed = True
            self.logger.info(f"Kafka adapter '{self.name}' closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error closing Kafka adapter '{self.name}': {e}")
            raise


# Convenience functions for creating Kafka adapters

def create_kafka_adapter(
    name: str,
    bootstrap_servers: Union[str, List[str]],
    client_type: str = "both",
    producer_config: Optional[Dict[str, Any]] = None,
    consumer_config: Optional[Dict[str, Any]] = None,
    topics: Optional[List[str]] = None,
    pool_config: Optional[PoolConfig] = None,
) -> KafkaAdapter:
    """
    Create a Kafka adapter with common configuration
    
    Args:
        name: Adapter name
        bootstrap_servers: Kafka bootstrap servers
        client_type: "producer", "consumer", or "both"
        producer_config: Producer-specific configuration
        consumer_config: Consumer-specific configuration  
        topics: Default topics for subscription
        pool_config: Connection pool configuration
        
    Returns:
        Configured Kafka adapter
    """
    config = {
        'bootstrap_servers': bootstrap_servers,
        'client_type': client_type,
    }
    
    if producer_config:
        config['producer_config'] = producer_config
        
    if consumer_config:
        config['consumer_config'] = consumer_config
        
    if topics:
        config['topics'] = topics
        
    if pool_config is None:
        pool_config = PoolConfig(max_connections=3)  # Lower default for Kafka
        
    return KafkaAdapter(
        name=name,
        service_type="kafka", 
        config=config,
        pool_config=pool_config
    )


def create_emby_kafka_adapter(
    name: str,
    bootstrap_servers: Union[str, List[str]], 
    consumer_group: str = "emby-recommendations",
    pool_config: Optional[PoolConfig] = None,
) -> KafkaAdapter:
    """
    Create a Kafka adapter optimized for Emby recommendation services
    
    Args:
        name: Adapter name
        bootstrap_servers: Kafka bootstrap servers
        consumer_group: Consumer group for recommendation service
        pool_config: Connection pool configuration
        
    Returns:
        Kafka adapter configured for Emby streaming
    """
    producer_config = {
        'acks': 'all',  # Ensure reliability for recommendation data
        'retries': 5,
        'batch_size': 16384,
        'linger_ms': 10,
        'compression_type': 'gzip',  # Compress streaming data
        'enable_idempotence': True,
    }
    
    consumer_config = {
        'group_id': consumer_group,
        'auto_offset_reset': 'latest',  # Start from latest for real-time processing
        'enable_auto_commit': True,
        'auto_commit_interval_ms': 5000,
        'session_timeout_ms': 30000,
        'max_poll_records': 100,  # Process smaller batches for lower latency
    }
    
    topics = ['emby.events', 'emby.user_activity', 'emby.playback']
    
    return create_kafka_adapter(
        name=name,
        bootstrap_servers=bootstrap_servers,
        client_type="both",
        producer_config=producer_config,
        consumer_config=consumer_config,
        topics=topics,
        pool_config=pool_config or PoolConfig(max_connections=4)
    )


async def create_kafka_adapter_from_env(
    name: str, 
    pool_config: Optional[PoolConfig] = None
) -> KafkaAdapter:
    """
    Create and initialize a Kafka adapter from environment variables
    
    Environment Variables:
        KAFKA_BOOTSTRAP_SERVERS - Comma-separated list of bootstrap servers
        KAFKA_CLIENT_TYPE - "producer", "consumer", or "both" (default: "both")
        KAFKA_CONSUMER_GROUP - Consumer group ID
        KAFKA_TOPICS - Comma-separated list of topics
        
    Args:
        name: Adapter name
        pool_config: Connection pool configuration
        
    Returns:
        Initialized Kafka adapter
    """
    import os
    
    bootstrap_servers = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    if ',' in bootstrap_servers:
        bootstrap_servers = [s.strip() for s in bootstrap_servers.split(',')]
        
    client_type = os.environ.get('KAFKA_CLIENT_TYPE', 'both')
    consumer_group = os.environ.get('KAFKA_CONSUMER_GROUP', f'{name}-group')
    topics = os.environ.get('KAFKA_TOPICS', '').split(',') if os.environ.get('KAFKA_TOPICS') else None
    
    consumer_config = {'group_id': consumer_group} if consumer_group else {}
    
    adapter = create_kafka_adapter(
        name=name,
        bootstrap_servers=bootstrap_servers,
        client_type=client_type,
        consumer_config=consumer_config,
        topics=topics,
        pool_config=pool_config
    )
    
    await adapter.initialize()
    return adapter