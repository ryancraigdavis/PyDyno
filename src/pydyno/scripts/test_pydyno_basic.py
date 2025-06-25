#!/usr/bin/env python3
"""
Basic test script for PyDyno functionality

This script tests the core PyDyno components without requiring a database connection.
Run this to make sure your PyDyno setup is working correctly.

Usage:
    python test_pydyno_basic.py
"""

import asyncio
import os
import sys
import logging
from typing import Dict, Any

from pydyno.core.pool_config import PoolConfig
from pydyno.core.utils import ConnectionMetrics
from pydyno.core.exceptions import PyDynoError, PoolNotFoundError
from pydyno.core.adapters import ConnectionAdapter
from pydyno.core.manager import PyDyno
from pydyno.adapters.postgresql import (
    PostgreSQLAdapter,
    create_postgresql_adapter,
)

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def test_imports():
    """Test that all PyDyno components can be imported"""
    print("🔍 Testing imports...")

    try:
        # Test core imports
        from pydyno.core.pool_config import PoolConfig
        from pydyno.core.utils import ConnectionMetrics
        from pydyno.core.exceptions import PyDynoError, PoolNotFoundError
        from pydyno.core.adapters import ConnectionAdapter
        from pydyno.core.manager import PyDyno

        # Test adapter imports
        from pydyno.adapters.postgresql import (
            PostgreSQLAdapter,
            create_postgresql_adapter,
        )

        print("✅ All imports successful!")
        return True

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False


async def test_pool_config():
    """Test PoolConfig creation and validation"""
    print("\n🔧 Testing PoolConfig...")

    try:
        # Test default config
        config = PoolConfig()
        print(f"   Default config: max_connections={config.max_connections}")

        # Test custom config
        config = PoolConfig(max_connections=20, timeout=60.0, pool_pre_ping=True)
        print(
            f"   Custom config: max_connections={config.max_connections}, timeout={config.timeout}"
        )

        # Test validation (should raise error)
        try:
            bad_config = PoolConfig(max_connections=0)  # Should fail
            print("❌ Validation failed - bad config was accepted")
            return False
        except ValueError as e:
            print(f"   ✅ Validation working: {e}")

        print("✅ PoolConfig tests passed!")
        return True

    except Exception as e:
        print(f"❌ PoolConfig test failed: {e}")
        return False


async def test_connection_metrics():
    """Test ConnectionMetrics functionality"""
    print("\n📊 Testing ConnectionMetrics...")

    try:
        # Create metrics
        metrics = ConnectionMetrics(pool_name="test_pool", service_type="test")
        print(f"   Created metrics for pool: {metrics.pool_name}")

        # Test request tracking
        start_time = metrics.record_request_start()
        print(f"   Started request at: {start_time}")

        # Simulate some work
        await asyncio.sleep(0.01)

        # Record success
        metrics.record_request_success(start_time)
        print(f"   Success rate: {metrics.success_rate:.1f}%")
        print(f"   Average response time: {metrics.average_response_time:.3f}s")

        # Test serialization
        metrics_dict = metrics.to_dict()
        print(f"   Serialized keys: {list(metrics_dict.keys())}")

        print("✅ ConnectionMetrics tests passed!")
        return True

    except Exception as e:
        print(f"❌ ConnectionMetrics test failed: {e}")
        return False


async def test_postgresql_adapter_creation():
    """Test PostgreSQL adapter creation (without connecting)"""
    print("\n🐘 Testing PostgreSQL adapter creation...")

    try:
        # Test with valid config
        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test_user",
            "password": "test_password",
            "database": "test_db",
        }

        pool_config = PoolConfig(max_connections=5)

        adapter = PostgreSQLAdapter(
            name="test_db",
            service_type="postgresql",
            config=config,
            pool_config=pool_config,
        )

        print(f"   Created adapter: {adapter}")
        print(f"   Adapter name: {adapter.name}")
        print(f"   Service type: {adapter.service_type}")
        print(f"   Is initialized: {adapter.is_initialized()}")
        print(f"   Is closed: {adapter.is_closed()}")

        # Test configuration validation
        try:
            bad_adapter = PostgreSQLAdapter(
                name="bad_db",
                service_type="postgresql",
                config={},  # Missing required fields
                pool_config=pool_config,
            )
            print("❌ Config validation failed - bad config was accepted")
            return False
        except Exception as e:
            print(f"   ✅ Config validation working: {type(e).__name__}")

        print("✅ PostgreSQL adapter creation tests passed!")
        return True

    except Exception as e:
        print(f"❌ PostgreSQL adapter creation test failed: {e}")
        return False


async def test_pydyno_manager():
    """Test PyDyno manager functionality"""
    print("\n🎯 Testing PyDyno manager...")

    try:
        # Create manager
        dyno = PyDyno(enable_health_monitoring=False)  # Disable for testing
        print(f"   Created PyDyno manager: {dyno}")

        # Test pool listing (should be empty)
        pools = dyno.list_pools()
        print(f"   Initial pools: {pools}")

        # Create a test adapter (don't initialize it)
        config = {
            "host": "localhost",
            "user": "test_user",
            "password": "test_password",
            "database": "test_db",
        }

        adapter = PostgreSQLAdapter(
            name="test_pool",
            service_type="postgresql",
            config=config,
            pool_config=PoolConfig(max_connections=3),
        )

        # Add pool to manager (without initializing)
        await dyno.create_pool("test_pool", adapter, auto_initialize=False)
        print("   ✅ Added pool to manager")

        # Test pool retrieval
        retrieved_adapter = dyno.get_pool("test_pool")
        print(f"   Retrieved adapter: {retrieved_adapter.name}")

        # Test pool listing
        pools = dyno.list_pools()
        print(f"   Pools after adding: {pools}")

        # Test error handling
        try:
            dyno.get_pool("nonexistent_pool")
            print("❌ Error handling failed - nonexistent pool was found")
            return False
        except Exception as e:
            print(f"   ✅ Error handling working: {type(e).__name__}")

        # Clean up
        await dyno.close_all()
        print("   ✅ Manager closed successfully")

        print("✅ PyDyno manager tests passed!")
        return True

    except Exception as e:
        print(f"❌ PyDyno manager test failed: {e}")
        return False


async def test_convenience_functions():
    """Test convenience functions"""
    print("\n🛠️ Testing convenience functions...")

    try:
        # Set some fake environment variables
        os.environ["POSTGRES_HOST"] = "test_host"
        os.environ["POSTGRES_USER"] = "test_user"
        os.environ["POSTGRES_PASSWORD"] = "test_pass"
        os.environ["POSTGRES_DB"] = "test_db"

        # Test create_postgresql_adapter function
        from pydyno.adapters.postgresql import create_postgresql_adapter

        adapter = create_postgresql_adapter("env_test")
        print(f"   Created adapter from env: {adapter.name}")
        print(f"   Config host: {adapter.config.get('host')}")

        # Test with DATABASE_URL
        os.environ["DATABASE_URL"] = "postgresql://user:pass@host:5432/db"
        adapter2 = create_postgresql_adapter("url_test")
        print(f"   Created adapter from URL: {adapter2.name}")

        # Clean up env vars
        for key in [
            "POSTGRES_HOST",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "DATABASE_URL",
        ]:
            if key in os.environ:
                del os.environ[key]

        print("✅ Convenience function tests passed!")
        return True

    except Exception as e:
        print(f"❌ Convenience function test failed: {e}")
        return False


async def run_all_tests():
    """Run all tests and report results"""
    print("🚀 Starting PyDyno basic functionality tests...\n")

    tests = [
        ("Import Test", test_imports),
        ("PoolConfig Test", test_pool_config),
        ("ConnectionMetrics Test", test_connection_metrics),
        ("PostgreSQL Adapter Creation Test", test_postgresql_adapter_creation),
        ("PyDyno Manager Test", test_pydyno_manager),
        ("Convenience Functions Test", test_convenience_functions),
    ]

    results = []

    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} crashed: {e}")
            results.append((test_name, False))

    # Print summary
    print("\n" + "=" * 50)
    print("📋 TEST SUMMARY")
    print("=" * 50)

    passed = 0
    failed = 0

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:<8} {test_name}")
        if result:
            passed += 1
        else:
            failed += 1

    print("-" * 50)
    print(f"Total: {len(results)} tests, {passed} passed, {failed} failed")

    if failed == 0:
        print("\n🎉 All tests passed! PyDyno is working correctly.")
        print("   You can now try connecting to a real database.")
        return True
    else:
        print(f"\n⚠️  {failed} tests failed. Please fix the issues before proceeding.")
        return False


if __name__ == "__main__":
    # Run the tests
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
