-- PyDyno Integration Test Database Setup
-- This script initializes the test database with tables and sample data

-- Create test schemas
CREATE SCHEMA IF NOT EXISTS pydyno_test;
SET search_path TO pydyno_test, public;

-- Test table for basic operations
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true
);

-- Test table for complex operations
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    order_number VARCHAR(50) UNIQUE NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Test table for JSON/JSONB operations
CREATE TABLE user_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    profile_data JSONB NOT NULL DEFAULT '{}',
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert sample test data
INSERT INTO users (username, email) VALUES
    ('testuser1', 'user1@example.com'),
    ('testuser2', 'user2@example.com'),
    ('testuser3', 'user3@example.com'),
    ('inactive_user', 'inactive@example.com');

-- Update one user to be inactive
UPDATE users SET is_active = false WHERE username = 'inactive_user';

-- Insert sample orders
INSERT INTO orders (user_id, order_number, total_amount, status) VALUES
    (1, 'ORD-001', 99.99, 'completed'),
    (1, 'ORD-002', 149.50, 'pending'),
    (2, 'ORD-003', 75.25, 'completed'),
    (3, 'ORD-004', 200.00, 'shipped');

-- Insert sample profiles with JSONB data
INSERT INTO user_profiles (user_id, profile_data, preferences) VALUES
    (1, '{"first_name": "John", "last_name": "Doe", "age": 30}', '{"theme": "dark", "notifications": true}'),
    (2, '{"first_name": "Jane", "last_name": "Smith", "age": 28}', '{"theme": "light", "notifications": false}'),
    (3, '{"first_name": "Bob", "last_name": "Wilson", "age": 35}', '{"theme": "auto", "notifications": true}');

-- Create indexes for testing
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_user_profiles_data ON user_profiles USING GIN(profile_data);

-- Create a function for testing stored procedure calls
CREATE OR REPLACE FUNCTION pydyno_test.get_user_order_count(user_id_param INTEGER)
RETURNS INTEGER AS $$
BEGIN
    RETURN (SELECT COUNT(*) FROM pydyno_test.orders WHERE user_id = user_id_param);
END;
$$ LANGUAGE plpgsql;

-- Create a view for testing complex queries
CREATE VIEW user_order_summary AS
SELECT 
    u.id,
    u.username,
    u.email,
    COUNT(o.id) as order_count,
    COALESCE(SUM(o.total_amount), 0) as total_spent,
    MAX(o.created_at) as last_order_date
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
WHERE u.is_active = true
GROUP BY u.id, u.username, u.email;

-- Grant permissions to test user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA pydyno_test TO pydyno_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA pydyno_test TO pydyno_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pydyno_test TO pydyno_user;