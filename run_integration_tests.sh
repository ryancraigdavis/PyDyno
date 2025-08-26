#!/bin/bash

# PyDyno Integration Test Runner
# This script sets up PostgreSQL via Docker and runs comprehensive integration tests

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.test.yml"
POSTGRES_CONTAINER="pydyno_test_db"
TEST_CONTAINER="pydyno_test_runner"

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
}

# Function to check if Docker Compose is available
check_docker_compose() {
    if ! command -v docker-compose >/dev/null 2>&1 && ! docker compose version >/dev/null 2>&1; then
        log_error "Docker Compose is not available. Please install Docker Compose."
        exit 1
    fi
    
    # Determine which docker compose command to use
    if docker compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
    else
        DOCKER_COMPOSE="docker-compose"
    fi
}

# Function to cleanup containers
cleanup() {
    log_info "Cleaning up test containers..."
    $DOCKER_COMPOSE -f $COMPOSE_FILE down --volumes --remove-orphans
    log_success "Cleanup completed"
}

# Function to wait for PostgreSQL to be ready
wait_for_postgres() {
    log_info "Waiting for PostgreSQL to be ready..."
    
    max_attempts=30
    attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if docker exec $POSTGRES_CONTAINER pg_isready -U pydyno_user -d pydyno_test >/dev/null 2>&1; then
            log_success "PostgreSQL is ready!"
            return 0
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep 2
    done
    
    echo
    log_error "PostgreSQL failed to become ready within $((max_attempts * 2)) seconds"
    return 1
}

# Function to show usage
show_usage() {
    echo "PyDyno Integration Test Runner"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --setup-only    Only setup the test environment (don't run tests)"
    echo "  --tests-only    Only run tests (assumes environment is already setup)"
    echo "  --cleanup       Cleanup test environment and exit"
    echo "  --logs          Show logs from test containers"
    echo "  --help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                    # Run full test suite with setup and cleanup"
    echo "  $0 --setup-only       # Just setup PostgreSQL for manual testing"
    echo "  $0 --tests-only       # Run tests against existing setup"
    echo "  $0 --cleanup          # Cleanup test environment"
    echo ""
}

# Function to run the integration tests
run_tests() {
    log_info "Running PyDyno integration tests..."
    
    # Build and run the test container
    if $DOCKER_COMPOSE -f $COMPOSE_FILE up --build test-runner; then
        log_success "Integration tests completed successfully!"
        return 0
    else
        log_error "Integration tests failed!"
        return 1
    fi
}

# Function to setup test environment
setup_environment() {
    log_info "Setting up test environment..."
    
    # Start PostgreSQL container
    $DOCKER_COMPOSE -f $COMPOSE_FILE up -d postgres
    
    # Wait for PostgreSQL to be ready
    if wait_for_postgres; then
        log_success "Test environment setup completed!"
        
        # Show connection information
        echo ""
        log_info "PostgreSQL is running with the following configuration:"
        echo "  Host: localhost"
        echo "  Port: 5433"
        echo "  Database: pydyno_test"
        echo "  User: pydyno_user"
        echo "  Password: pydyno_pass"
        echo ""
        echo "You can connect manually using:"
        echo "  psql -h localhost -p 5433 -U pydyno_user -d pydyno_test"
        echo ""
        
        return 0
    else
        log_error "Failed to setup test environment"
        cleanup
        return 1
    fi
}

# Function to show logs
show_logs() {
    log_info "Showing container logs..."
    $DOCKER_COMPOSE -f $COMPOSE_FILE logs -f
}

# Main execution
main() {
    # Parse command line arguments
    case "${1:-}" in
        --help)
            show_usage
            exit 0
            ;;
        --cleanup)
            cleanup
            exit 0
            ;;
        --logs)
            show_logs
            exit 0
            ;;
        --setup-only)
            check_docker
            check_docker_compose
            setup_environment
            exit $?
            ;;
        --tests-only)
            check_docker
            check_docker_compose
            run_tests
            exit $?
            ;;
        "")
            # Full test run
            ;;
        *)
            log_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
    
    # Full integration test run
    check_docker
    check_docker_compose
    
    log_info "Starting PyDyno integration test suite..."
    
    # Ensure clean state
    cleanup 2>/dev/null || true
    
    # Setup environment
    if setup_environment; then
        # Run tests
        if run_tests; then
            log_success "🎉 All integration tests passed!"
            EXIT_CODE=0
        else
            log_error "❌ Some integration tests failed!"
            EXIT_CODE=1
        fi
        
        # Show final logs for debugging if tests failed
        if [ $EXIT_CODE -ne 0 ]; then
            log_info "Test container logs (last 50 lines):"
            $DOCKER_COMPOSE -f $COMPOSE_FILE logs --tail=50 test-runner
        fi
        
        # Cleanup
        cleanup
        
        exit $EXIT_CODE
    else
        log_error "Failed to setup test environment"
        exit 1
    fi
}

# Handle Ctrl+C gracefully
trap cleanup INT

# Run main function
main "$@"