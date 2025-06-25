<div align="center">
  <img src="https://raw.githubusercontent.com/ryancraigdavis/pydyno/main/assets/logo.png" alt="PyDyno Logo" width="200"/>
</div>

# PyDyno

> Unified connection pooling for Python, inspired by Netflix's Dyno

**PyDyno** is a modern, async-first connection pooling library that provides a unified interface for managing connections to databases, caches, and HTTP services. Built with `attrs` and designed for production use.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Built with attrs](https://img.shields.io/badge/built%20with-attrs-orange.svg)](https://www.attrs.org/)

## 🚀 Quick Start

```python
import asyncio
from pydyno import PyDyno, PoolConfig
from pydyno.adapters.postgresql import PostgreSQLAdapter

async def main():
    # Create PyDyno manager
    dyno = PyDyno()
    
    # Configure PostgreSQL pool
    config = {
        'host': 'localhost',
        'user': 'postgres',
        'password': 'password',
        'database': 'mydb'
    }
    
    adapter = PostgreSQLAdapter(
        name="main_db",
        service_type="postgresql",
        config=config,
        pool_config=PoolConfig(max_connections=20)
    )
    
    # Add pool to manager
    await dyno.create_pool("main_db", adapter)
    
    # Use the pool
    pool = dyno.get_pool("main_db")
    async with pool.session_scope() as session:
        result = await session.execute(text("SELECT version()"))
        print(result.scalar())
    
    # Cleanup
    await dyno.close_all()

asyncio.run(main())
```

## ✨ Features

- **🔄 Unified Interface**: One consistent API for all service types
- **⚡ Async-First**: Built for modern async Python applications
- **📊 Built-in Metrics**: Track requests, response times, and health
- **🏥 Health Monitoring**: Automatic background health checks
- **🛡️ Production Ready**: Robust error handling and connection recovery
- **🔧 Highly Configurable**: Fine-tune connection pools for your needs
- **📦 Clean Architecture**: Easy to extend with new adapters

## 📋 Supported Services

| Service | Status | Adapter |
|---------|--------|---------|
| **PostgreSQL** | ✅ Ready | `PostgreSQLAdapter` |
| **Redis** | 🚧 Planned | `RedisAdapter` |
| **HTTP APIs** | 🚧 Planned | `HTTPAdapter` |
| **Kafka** | 🚧 Planned | `KafkaAdapter` |

## 🛠️ Installation

```bash
# Basic installation
pip install pydyno

# With PostgreSQL support
pip install pydyno[postgresql]

# Development installation
git clone https://github.com/yourusername/pydyno.git
cd pydyno
pip install -e .
```

## 📖 Documentation

### Basic Concepts

**PyDyno Manager**: Central coordinator that manages multiple connection pools
**Adapters**: Service-specific implementations (PostgreSQL, Redis, etc.)
**Pool Config**: Configuration for connection pool behavior
**Metrics**: Built-in monitoring and performance tracking

### Configuration

```python
from pydyno.core.pool_config import PoolConfig

# Customize pool behavior
pool_config = PoolConfig(
    max_connections=20,        # Maximum connections in pool
    min_connections=2,         # Minimum connections to maintain
    max_overflow=30,           # Additional connections beyond max
    timeout=30.0,              # Connection timeout in seconds
    pool_recycle=3600,         # Recycle connections after 1 hour
    pool_pre_ping=True,        # Verify connections before use
    retry_attempts=3,          # Retry failed operations
    health_check_interval=60.0, # Health check frequency
    echo=False                 # Log SQL queries (PostgreSQL)
)
```

### PostgreSQL Adapter

```python
from pydyno.adapters.postgresql import PostgreSQLAdapter, create_postgresql_adapter

# Method 1: Direct creation
adapter = PostgreSQLAdapter(
    name="my_db",
    service_type="postgresql",
    config={
        'host': 'localhost',
        'port': 5432,
        'user': 'postgres',
        'password': 'password',
        'database': 'myapp'
    },
    pool_config=PoolConfig(max_connections=10)
)

# Method 2: From environment variables
# Set: POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
adapter = create_postgresql_adapter("my_db")

# Method 3: From DATABASE_URL
# Set: DATABASE_URL=postgresql://user:pass@host:5432/db
adapter = create_postgresql_adapter("my_db")
```

### Usage Examples

#### FastAPI Integration

```python
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydyno import PyDyno
from pydyno.adapters.postgresql import create_postgresql_adapter

# Global PyDyno instance
dyno = PyDyno()

async def startup_event():
    """Initialize database pool on startup"""
    adapter = create_postgresql_adapter("main_db")
    await dyno.create_pool("main_db", adapter)

async def shutdown_event():
    """Cleanup on shutdown"""
    await dyno.close_all()

# FastAPI dependency
async def get_db_session() -> AsyncSession:
    """Get database session for routes"""
    pool = dyno.get_pool("main_db")
    return await pool.get_session()

# Use in routes
@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

# FastAPI app setup
app = FastAPI()
app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)
```

#### Session Management

```python
# Automatic transaction management
async with adapter.session_scope() as session:
    # Create user
    user = User(name="John", email="john@example.com")
    session.add(user)
    
    # Update user (same transaction)
    user.last_login = datetime.utcnow()
    
    # Automatically commits on success, rolls back on error

# Raw SQL queries
result = await adapter.execute_scalar("SELECT COUNT(*) FROM users")
print(f"Total users: {result}")

# Query with parameters
users = await adapter.execute_query(
    "SELECT * FROM users WHERE created_at > :date",
    {"date": datetime(2024, 1, 1)}
)
```

#### Health Monitoring

```python
# Check health of all pools
health_results = await dyno.health_check()
print(health_results)  # {'main_db': True, 'cache': True}

# Check specific pool
is_healthy = await dyno.health_check("main_db")

# Get detailed metrics
metrics = await dyno.get_metrics_dict()
for pool_name, pool_metrics in metrics.items():
    print(f"Pool: {pool_name}")
    print(f"  Total requests: {pool_metrics['total_requests']}")
    print(f"  Success rate: {pool_metrics['success_rate']:.1f}%")
    print(f"  Avg response time: {pool_metrics['average_response_time']:.3f}s")
    print(f"  Health: {pool_metrics['health_status']}")
```

#### Multiple Database Pools

```python
async def setup_multiple_databases():
    dyno = PyDyno()
    
    # Primary database
    primary_adapter = PostgreSQLAdapter(
        name="primary",
        service_type="postgresql",
        config={"url": "postgresql://user:pass@primary-db:5432/app"},
        pool_config=PoolConfig(max_connections=20)
    )
    
    # Analytics database (read-only)
    analytics_adapter = PostgreSQLAdapter(
        name="analytics",
        service_type="postgresql", 
        config={"url": "postgresql://user:pass@analytics-db:5432/analytics"},
        pool_config=PoolConfig(max_connections=5, echo=True)
    )
    
    # Add both pools
    await dyno.create_pool("primary", primary_adapter)
    await dyno.create_pool("analytics", analytics_adapter)
    
    return dyno

# Use different databases
async def get_user_analytics(dyno: PyDyno, user_id: int):
    # Write to primary
    primary = dyno.get_pool("primary")
    async with primary.session_scope() as session:
        user = User(id=user_id, name="John")
        session.add(user)
    
    # Read from analytics
    analytics = dyno.get_pool("analytics")
    result = await analytics.execute_scalar(
        "SELECT COUNT(*) FROM user_events WHERE user_id = :user_id",
        {"user_id": user_id}
    )
    
    return result
```

## 🧪 Testing

```bash
# Run basic functionality tests (no database required)
python test_pydyno_basic.py

# Run database tests (requires PostgreSQL)
export POSTGRES_HOST=localhost
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=password
export POSTGRES_DB=test_db
python test_pydyno_database.py
```

## 🏗️ Architecture

PyDyno follows a clean, extensible architecture:

```
pydyno/
├── core/
│   ├── manager.py          # PyDyno main manager
│   ├── adapters.py         # Base adapter interface
│   ├── pool_config.py      # Configuration classes
│   ├── utils.py            # Metrics and utilities
│   └── exceptions.py       # Custom exceptions
└── adapters/
    ├── postgresql.py       # PostgreSQL adapter
    ├── redis.py           # Redis adapter (planned)
    └── http.py            # HTTP adapter (planned)
```

### Creating Custom Adapters

```python
from pydyno.core.adapters import ConnectionAdapter

class CustomAdapter(ConnectionAdapter):
    """Custom service adapter"""
    
    async def initialize(self):
        """Set up your service connection pool"""
        # Initialize your client/connection pool
        self._client = YourServiceClient(
            **self.config,
            max_connections=self.pool_config.max_connections
        )
        self._initialized = True
    
    async def health_check(self) -> bool:
        """Check service health"""
        try:
            await self._client.ping()
            self.metrics.record_health_check(True)
            return True
        except Exception:
            self.metrics.record_health_check(False)
            return False
    
    async def close(self):
        """Clean up resources"""
        if self._client:
            await self._client.close()
        self._closed = True
```

## 🎯 Why PyDyno?

### The Problem
Modern applications often need to connect to multiple services:
- Primary database (PostgreSQL)
- Cache layer (Redis)
- External APIs (HTTP)
- Message queues (Kafka)

Each service has its own connection pooling mechanism, configuration format, and management approach. This leads to:
- **Inconsistent APIs** across your codebase
- **Scattered configuration** and monitoring
- **Duplicate connection management** logic
- **No unified health checking**

### The Solution
PyDyno provides a **single, unified interface** for all your connection pools:
- ✅ **One API** for all services
- ✅ **Consistent configuration** patterns
- ✅ **Unified metrics** and monitoring
- ✅ **Centralized health checking**
- ✅ **Production-ready** error handling

### Inspired by Netflix
Netflix's [Dyno](https://github.com/Netflix/dyno) library solved this problem for Java applications at massive scale. PyDyno brings these same architectural patterns to Python, adapted for modern async applications.

## 🔮 Roadmap

### v0.2.0 - Redis Support
- Redis connection adapter
- Pub/Sub support
- Redis Cluster support

### v0.3.0 - HTTP Client Pooling
- HTTP adapter for API calls
- Load balancing strategies
- Circuit breaker pattern

### v0.4.0 - Advanced Features
- Kafka adapter
- Service discovery integration
- Prometheus metrics export

### v1.0.0 - Production Ready
- Comprehensive test suite
- Performance optimizations
- Full documentation
- Stability guarantees

## 🤝 Contributing

We welcome contributions! Areas where help is needed:

1. **New Adapters**: Redis, HTTP, Kafka, MongoDB
2. **Testing**: More test cases and edge cases
3. **Documentation**: Examples and tutorials
4. **Performance**: Benchmarks and optimizations

```bash
# Development setup
git clone https://github.com/yourusername/pydyno.git
cd pydyno
pip install -e ".[dev]"

# Run tests
python test_pydyno_basic.py

# Code formatting
black src/
isort src/
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Inspired by Netflix's [Dyno](https://github.com/Netflix/dyno) library
- Built with [attrs](https://www.attrs.org/) for clean Python classes
- Uses [SQLAlchemy](https://www.sqlalchemy.org/) for PostgreSQL support

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/ryancraigdavis/pydyno/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ryancraigdavis/pydyno/discussions)

---

**PyDyno** - Making connection pooling simple, unified, and powerful. 🚀
