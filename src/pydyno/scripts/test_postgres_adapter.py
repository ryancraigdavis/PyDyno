import asyncio
import os
from pydyno.adapters.postgresql import PostgreSQLAdapter
from pydyno.core.pool_config import PoolConfig


async def test_adapter():
    config = {
        "host": "localhost",
        "port": 5432,
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "password"),
        "database": os.getenv("POSTGRES_DB", "test_db"),
    }

    adapter = PostgreSQLAdapter(
        name="test", service_type="postgresql", config=config, pool_config=PoolConfig()
    )

    print(f"Created adapter: {adapter}")

    try:
        await adapter.initialize()
        print("✅ Initialization successful")
    except Exception as e:
        print(f"❌ Initialization failed: {e}")

    try:
        await adapter.close()
        print("✅ Close successful")
    except Exception as e:
        print(f"❌ Close failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_adapter())
