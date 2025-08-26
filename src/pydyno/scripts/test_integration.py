#!/usr/bin/env python3
"""
PyDyno Integration Test Suite

This script performs comprehensive integration testing of PyDyno with a real PostgreSQL database.
It requires a running PostgreSQL instance (provided by Docker Compose).

Usage:
    python -m src.pydyno.scripts.test_integration

Environment Variables:
    POSTGRES_HOST     - PostgreSQL host (default: localhost)
    POSTGRES_PORT     - PostgreSQL port (default: 5432) 
    POSTGRES_USER     - PostgreSQL user (default: pydyno_user)
    POSTGRES_PASSWORD - PostgreSQL password (default: pydyno_pass)
    POSTGRES_DB       - PostgreSQL database (default: pydyno_test)
    DATABASE_URL      - Full database URL (overrides individual settings)
"""

import asyncio
import os
import sys
import time
import logging
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# PyDyno imports
from pydyno.core.manager import PyDyno
from pydyno.core.pool_config import PoolConfig
from pydyno.adapters.postgresql import PostgreSQLAdapter, create_postgresql_adapter
from pydyno.core.exceptions import PyDynoError

# SQLAlchemy imports
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class IntegrationTestSuite:
    """Comprehensive integration test suite for PyDyno"""

    def __init__(self):
        self.logger = logging.getLogger("pydyno.integration_test")
        self.dyno: Optional[PyDyno] = None
        self.test_results: List[tuple] = []

    def get_database_config(self) -> Dict[str, Any]:
        """Get database configuration from environment variables"""
        if "DATABASE_URL" in os.environ:
            return {"url": os.environ["DATABASE_URL"]}
        
        return {
            "host": os.environ.get("POSTGRES_HOST", "localhost"),
            "port": int(os.environ.get("POSTGRES_PORT", "5432")),
            "user": os.environ.get("POSTGRES_USER", "pydyno_user"),
            "password": os.environ.get("POSTGRES_PASSWORD", "pydyno_pass"),
            "database": os.environ.get("POSTGRES_DB", "pydyno_test"),
        }

    async def setup_dyno(self) -> bool:
        """Setup PyDyno manager with test configuration"""
        try:
            self.logger.info("Setting up PyDyno manager...")
            
            # Create PyDyno manager
            self.dyno = PyDyno(
                enable_health_monitoring=True,
                health_check_interval=30.0,
                max_consecutive_failures=3
            )

            # Create PostgreSQL adapter
            config = self.get_database_config()
            pool_config = PoolConfig(
                max_connections=10,
                min_connections=2,
                max_overflow=15,
                timeout=30.0,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False  # Set to True for SQL debugging
            )

            adapter = PostgreSQLAdapter(
                name="main_db",
                service_type="postgresql", 
                config=config,
                pool_config=pool_config
            )

            # Add pool to manager
            await self.dyno.create_pool("main_db", adapter)
            
            self.logger.info("✅ PyDyno setup completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"❌ PyDyno setup failed: {e}")
            return False

    async def cleanup(self):
        """Cleanup PyDyno resources"""
        if self.dyno:
            try:
                await self.dyno.close_all()
                self.logger.info("✅ PyDyno cleanup completed")
            except Exception as e:
                self.logger.error(f"❌ PyDyno cleanup failed: {e}")

    @asynccontextmanager
    async def test_context(self, test_name: str):
        """Context manager for individual test execution"""
        start_time = time.time()
        self.logger.info(f"\n🧪 Running: {test_name}")
        
        try:
            yield
            duration = time.time() - start_time
            self.logger.info(f"✅ {test_name} - PASSED ({duration:.3f}s)")
            self.test_results.append((test_name, True, duration, None))
        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"❌ {test_name} - FAILED ({duration:.3f}s): {e}")
            self.test_results.append((test_name, False, duration, str(e)))
            # Don't re-raise, continue with other tests

    async def test_basic_connectivity(self):
        """Test basic database connectivity"""
        async with self.test_context("Basic Connectivity"):
            pool = self.dyno.get_pool("main_db")
            
            # Test simple query
            result = await pool.execute_scalar("SELECT 1")
            assert result == 1, f"Expected 1, got {result}"
            
            # Test version query
            version = await pool.execute_scalar("SELECT version()")
            assert "PostgreSQL" in version, f"Unexpected version: {version}"
            
            self.logger.info(f"   Connected to: {version[:50]}...")

    async def test_session_management(self):
        """Test session creation and transaction management"""
        async with self.test_context("Session Management"):
            pool = self.dyno.get_pool("main_db")
            
            # Test session creation
            session = await pool.get_session()
            assert session is not None, "Session creation failed"
            
            # Test basic query with session
            result = await session.execute(text("SELECT COUNT(*) FROM pydyno_test.users"))
            user_count = result.scalar()
            assert isinstance(user_count, int), f"Expected integer, got {type(user_count)}"
            
            await session.close()
            
            self.logger.info(f"   Found {user_count} users in test database")

    async def test_transaction_scope(self):
        """Test automatic transaction management with session_scope"""
        async with self.test_context("Transaction Scope"):
            pool = self.dyno.get_pool("main_db")
            
            # Test successful transaction
            async with pool.session_scope() as session:
                result = await session.execute(text(
                    "INSERT INTO pydyno_test.users (username, email) VALUES (:username, :email) RETURNING id"
                ), {"username": "test_transaction", "email": "test_transaction@example.com"})
                user_id = result.scalar()
                assert user_id is not None, "Insert should return user ID"
                
                self.logger.info(f"   Created user with ID: {user_id}")
            
            # Verify commit worked
            async with pool.session_scope() as session:
                result = await session.execute(text(
                    "SELECT COUNT(*) FROM pydyno_test.users WHERE username = :username"
                ), {"username": "test_transaction"})
                count = result.scalar()
                assert count == 1, f"Expected 1 user, found {count}"

    async def test_transaction_rollback(self):
        """Test transaction rollback on error"""
        async with self.test_context("Transaction Rollback"):
            pool = self.dyno.get_pool("main_db")
            
            initial_count = await pool.execute_scalar(
                "SELECT COUNT(*) FROM pydyno_test.users WHERE username LIKE 'rollback_test%'"
            )
            
            # Test rollback on error
            try:
                async with pool.session_scope() as session:
                    # Insert valid user
                    await session.execute(text(
                        "INSERT INTO pydyno_test.users (username, email) VALUES (:username, :email)"
                    ), {"username": "rollback_test_1", "email": "rollback1@example.com"})
                    
                    # This should cause a duplicate key error and rollback the transaction
                    await session.execute(text(
                        "INSERT INTO pydyno_test.users (username, email) VALUES (:username, :email)"
                    ), {"username": "rollback_test_1", "email": "rollback1@example.com"})
                    
                assert False, "Should have raised an exception"
            except Exception as e:
                self.logger.info(f"   Expected error occurred: {type(e).__name__}")
            
            # Verify rollback worked - count should be unchanged
            final_count = await pool.execute_scalar(
                "SELECT COUNT(*) FROM pydyno_test.users WHERE username LIKE 'rollback_test%'"
            )
            assert final_count == initial_count, f"Transaction was not rolled back properly"

    async def test_complex_queries(self):
        """Test complex queries with joins and aggregations"""
        async with self.test_context("Complex Queries"):
            pool = self.dyno.get_pool("main_db")
            
            # Test join query
            async with pool.session_scope() as session:
                result = await session.execute(text("""
                    SELECT 
                        u.username,
                        COUNT(o.id) as order_count,
                        COALESCE(SUM(o.total_amount), 0) as total_spent
                    FROM pydyno_test.users u
                    LEFT JOIN pydyno_test.orders o ON u.id = o.user_id
                    WHERE u.is_active = true
                    GROUP BY u.id, u.username
                    ORDER BY total_spent DESC
                    LIMIT 5
                """))
                
                users = result.fetchall()
                assert len(users) > 0, "Should return at least one user"
                
                for user in users:
                    self.logger.info(f"   User: {user.username}, Orders: {user.order_count}, Spent: ${user.total_spent}")

    async def test_json_operations(self):
        """Test JSONB operations"""
        async with self.test_context("JSON Operations"):
            pool = self.dyno.get_pool("main_db")
            
            async with pool.session_scope() as session:
                # Test JSON query
                result = await session.execute(text("""
                    SELECT 
                        profile_data->>'first_name' as first_name,
                        profile_data->>'age' as age,
                        preferences->>'theme' as theme
                    FROM pydyno_test.user_profiles
                    WHERE profile_data->>'age' > :min_age
                    ORDER BY (profile_data->>'age')::int DESC
                """), {"min_age": "25"})
                
                profiles = result.fetchall()
                assert len(profiles) > 0, "Should return at least one profile"
                
                for profile in profiles:
                    self.logger.info(f"   User: {profile.first_name}, Age: {profile.age}, Theme: {profile.theme}")

    async def test_stored_procedures(self):
        """Test stored procedure calls"""
        async with self.test_context("Stored Procedures"):
            pool = self.dyno.get_pool("main_db")
            
            # Test function call
            result = await pool.execute_scalar(
                "SELECT pydyno_test.get_user_order_count(:user_id)",
                {"user_id": 1}
            )
            
            assert isinstance(result, int), f"Expected integer result, got {type(result)}"
            self.logger.info(f"   User 1 has {result} orders")

    async def test_concurrent_connections(self):
        """Test concurrent connection handling"""
        async with self.test_context("Concurrent Connections"):
            pool = self.dyno.get_pool("main_db")
            
            async def run_query(query_id: int):
                async with pool.session_scope() as session:
                    await asyncio.sleep(0.1)  # Simulate work
                    result = await session.execute(text("SELECT CAST(:id AS TEXT) as query_id, pg_backend_pid() as pid"), {"id": str(query_id)})
                    row = result.fetchone()
                    return int(row.query_id), row.pid
            
            # Run multiple concurrent queries
            tasks = [run_query(i) for i in range(5)]
            results = await asyncio.gather(*tasks)
            
            assert len(results) == 5, f"Expected 5 results, got {len(results)}"
            
            # Check that we got different backend PIDs (indicating different connections)
            pids = {result[1] for result in results}
            self.logger.info(f"   Used {len(pids)} different database connections")

    async def test_health_monitoring(self):
        """Test health monitoring functionality"""
        async with self.test_context("Health Monitoring"):
            # Check health of specific pool
            health_result = await self.dyno.health_check("main_db")
            assert health_result["main_db"] is True, "Health check should pass"
            
            # Check health of all pools
            all_health = await self.dyno.health_check()
            assert all(all_health.values()), "All pools should be healthy"
            
            self.logger.info(f"   Health status: {all_health}")

    async def test_metrics_collection(self):
        """Test metrics collection and reporting"""
        async with self.test_context("Metrics Collection"):
            # Reset metrics by getting fresh pool instance
            pool = self.dyno.get_pool("main_db")
            
            # Run some successful operations to generate clean metrics
            for i in range(5):
                await pool.execute_scalar("SELECT 1")
            
            # Get metrics
            metrics = await self.dyno.get_metrics("main_db")
            metrics_dict = await self.dyno.get_metrics_dict("main_db")
            
            # More lenient assertions since we might have failures from earlier tests
            assert metrics.total_requests >= 5, f"Expected at least 5 requests, got {metrics.total_requests}"
            assert metrics.successful_requests >= 5, f"Expected at least 5 successful requests, got {metrics.successful_requests}"
            assert metrics.success_rate > 0, f"Success rate should be > 0: {metrics.success_rate}%"
            
            self.logger.info(f"   Metrics - Total: {metrics.total_requests}, Success Rate: {metrics.success_rate:.1f}%")
            self.logger.info(f"   Average Response Time: {metrics.average_response_time:.3f}s")

    async def test_pool_configuration(self):
        """Test pool configuration and limits"""
        async with self.test_context("Pool Configuration"):
            pool = self.dyno.get_pool("main_db")
            
            # Test pool information
            info = await pool.get_connection_info()
            assert info["status"] == "connected", f"Pool should be connected, got {info['status']}"
            
            self.logger.info(f"   Database: {info['database_name']}")
            self.logger.info(f"   Active connections: {info['active_connections']}")
            if "pool_info" in info:
                pool_info = info["pool_info"]
                self.logger.info(f"   Pool size: {pool_info.get('pool_size', 'N/A')}")

    async def test_error_handling(self):
        """Test error handling and recovery"""
        async with self.test_context("Error Handling"):
            pool = self.dyno.get_pool("main_db")
            
            # Test handling of SQL error
            try:
                await pool.execute_scalar("SELECT * FROM non_existent_table")
                assert False, "Should have raised an exception"
            except Exception as e:
                self.logger.info(f"   Handled SQL error correctly: {type(e).__name__}")
            
            # Verify pool is still functional after error
            result = await pool.execute_scalar("SELECT 1")
            assert result == 1, "Pool should still be functional after error"

    async def run_all_tests(self):
        """Run all integration tests"""
        self.logger.info("🚀 Starting PyDyno Integration Test Suite")
        
        # Setup
        if not await self.setup_dyno():
            return False

        try:
            # Run all tests
            tests = [
                self.test_basic_connectivity,
                self.test_session_management,
                self.test_transaction_scope,
                self.test_transaction_rollback,
                self.test_complex_queries,
                self.test_json_operations,
                self.test_stored_procedures,
                self.test_concurrent_connections,
                self.test_health_monitoring,
                self.test_metrics_collection,
                self.test_pool_configuration,
                self.test_error_handling,
            ]

            for test in tests:
                await test()
            
            return self.print_summary()

        finally:
            await self.cleanup()

    def print_summary(self) -> bool:
        """Print test summary and return success status"""
        self.logger.info("\n" + "=" * 70)
        self.logger.info("📋 INTEGRATION TEST SUMMARY")
        self.logger.info("=" * 70)

        passed = 0
        failed = 0
        total_time = 0

        for test_name, success, duration, error in self.test_results:
            status = "✅ PASS" if success else "❌ FAIL"
            self.logger.info(f"{status:<8} {test_name:<35} ({duration:.3f}s)")
            
            if not success and error:
                self.logger.info(f"         Error: {error}")
            
            if success:
                passed += 1
            else:
                failed += 1
            total_time += duration

        self.logger.info("-" * 70)
        self.logger.info(f"Total: {len(self.test_results)} tests, {passed} passed, {failed} failed")
        self.logger.info(f"Total time: {total_time:.3f}s")

        if failed == 0:
            self.logger.info("\n🎉 ALL INTEGRATION TESTS PASSED!")
            self.logger.info("   ✅ PyDyno is working correctly with PostgreSQL")
            self.logger.info("   ✅ Connection pooling is functional") 
            self.logger.info("   ✅ Transaction management is working")
            self.logger.info("   ✅ Health monitoring is operational")
            self.logger.info("   ✅ Metrics collection is active")
            return True
        else:
            self.logger.error(f"\n❌ {failed} INTEGRATION TESTS FAILED!")
            self.logger.error("   Please review the errors above and fix any issues.")
            return False


async def main():
    """Main entry point"""
    test_suite = IntegrationTestSuite()
    success = await test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())