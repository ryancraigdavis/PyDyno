# PyDyno Integration Testing

This directory contains comprehensive integration tests for PyDyno that test real database connectivity and functionality using Docker.

## Overview

The integration test suite provides:

- **Real Database Testing**: Tests against actual PostgreSQL instances
- **Docker-based Setup**: Automatic PostgreSQL container setup and teardown  
- **Comprehensive Coverage**: Tests all major PyDyno features
- **CI/CD Ready**: Easy integration with continuous integration systems

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Python 3.12+ (for local development)

### Running Integration Tests

The easiest way to run the complete integration test suite:

```bash
./run_integration_tests.sh
```

This will:
1. Start a PostgreSQL container with test data
2. Build and run the test suite
3. Report results
4. Clean up containers

### Test Options

```bash
# Full test suite (default)
./run_integration_tests.sh

# Setup test environment only (for manual testing)
./run_integration_tests.sh --setup-only

# Run tests against existing environment
./run_integration_tests.sh --tests-only

# Cleanup test environment
./run_integration_tests.sh --cleanup

# Show container logs
./run_integration_tests.sh --logs

# Show help
./run_integration_tests.sh --help
```

## Test Architecture

### Components

1. **PostgreSQL Container** (`postgres:15`)
   - Pre-loaded with test schema and sample data
   - Exposed on port 5433 to avoid conflicts
   - Health checks ensure readiness before tests

2. **Test Runner Container** (Python 3.12)
   - Contains PyDyno and all dependencies
   - Runs comprehensive integration test suite
   - Reports detailed results

3. **Test Database Schema** (`tests/sql/init.sql`)
   - Sample tables with relationships
   - Test data for various scenarios
   - JSONB data for advanced testing
   - Stored procedures and views

### Test Categories

The integration test suite covers:

- **Basic Connectivity**: Connection establishment and simple queries
- **Session Management**: Session creation and lifecycle management
- **Transaction Management**: Commit/rollback behavior
- **Complex Queries**: Joins, aggregations, and advanced SQL
- **JSON Operations**: JSONB queries and operations  
- **Stored Procedures**: Function calls and complex operations
- **Concurrent Access**: Multiple simultaneous connections
- **Health Monitoring**: Health check functionality
- **Metrics Collection**: Performance and usage metrics
- **Error Handling**: Graceful error recovery
- **Pool Configuration**: Connection pool behavior

## Manual Testing

For development and debugging, you can set up a persistent test environment:

```bash
# Setup PostgreSQL container
./run_integration_tests.sh --setup-only

# Connect to database manually
psql -h localhost -p 5433 -U pydyno_user -d pydyno_test

# Run specific tests in development
cd /path/to/pydyno
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5433  
export POSTGRES_USER=pydyno_user
export POSTGRES_PASSWORD=pydyno_pass
export POSTGRES_DB=pydyno_test

python -m src.pydyno.scripts.test_integration

# Cleanup when done
./run_integration_tests.sh --cleanup
```

## Environment Variables

The test suite can be configured with these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | `pydyno_user` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `pydyno_pass` | PostgreSQL password |
| `POSTGRES_DB` | `pydyno_test` | PostgreSQL database |
| `DATABASE_URL` | - | Full database URL (overrides individual settings) |

## CI/CD Integration

### GitHub Actions

```yaml
name: Integration Tests
on: [push, pull_request]

jobs:
  integration-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Run Integration Tests
        run: ./run_integration_tests.sh
```

### Docker Compose Services

The test suite uses these services:

- **postgres**: PostgreSQL 15 with test schema
- **test-runner**: Python application container

Services are networked together and use health checks to ensure proper startup order.

## Test Data

The test database includes:

### Tables

- **users**: Sample user accounts with authentication info
- **orders**: E-commerce orders linked to users  
- **user_profiles**: JSONB data for complex queries

### Sample Queries Tested

```sql
-- Basic connectivity
SELECT 1;
SELECT version();

-- Complex joins  
SELECT u.username, COUNT(o.id) as order_count
FROM users u LEFT JOIN orders o ON u.id = o.user_id  
GROUP BY u.username;

-- JSON operations
SELECT profile_data->>'first_name', preferences->>'theme'
FROM user_profiles 
WHERE profile_data->>'age' > '25';

-- Stored procedures
SELECT get_user_order_count(1);
```

## Troubleshooting

### Common Issues

1. **Port Conflicts**: PostgreSQL uses port 5433 to avoid conflicts with local instances

2. **Docker Issues**: Ensure Docker is running and you have sufficient disk space

3. **Permission Issues**: Make sure the test script is executable:
   ```bash
   chmod +x run_integration_tests.sh
   ```

4. **Container Cleanup**: If containers are stuck, force cleanup:
   ```bash
   docker-compose -f docker-compose.test.yml down --volumes --remove-orphans
   ```

### Debugging

Enable detailed logging:

```bash
# Show all container logs
./run_integration_tests.sh --logs

# Check PostgreSQL logs specifically  
docker logs pydyno_test_db

# Check test runner logs
docker logs pydyno_test_runner
```

### Test Database Access

Connect directly to the test database:

```bash
# After running --setup-only
psql -h localhost -p 5433 -U pydyno_user -d pydyno_test

# List tables
\dt pydyno_test.*

# Check sample data
SELECT * FROM pydyno_test.users LIMIT 5;
```

## Contributing

When adding new integration tests:

1. Add test methods to `IntegrationTestSuite` class
2. Include them in the `tests` list in `run_all_tests()`  
3. Follow the existing async/await patterns
4. Use the `test_context()` manager for consistent logging
5. Test both success and failure scenarios
6. Update this documentation

## Performance

The integration test suite typically runs in under 60 seconds:

- PostgreSQL startup: ~20 seconds
- Test execution: ~30 seconds  
- Cleanup: ~10 seconds

Times may vary based on hardware and Docker performance.