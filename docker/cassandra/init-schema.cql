-- Create keyspace for CDC pipeline testing
CREATE KEYSPACE IF NOT EXISTS warehouse
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE warehouse;

-- Users table with comprehensive column types for testing
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username TEXT,
    email TEXT,
    age INT,
    balance DECIMAL,
    is_active BOOLEAN,
    preferences MAP<TEXT, TEXT>,
    tags SET<TEXT>,
    phone_numbers LIST<TEXT>,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Orders table with collection types
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY,
    user_id UUID,
    order_number BIGINT,
    total_amount DECIMAL,
    status TEXT,
    items LIST<TEXT>,
    metadata MAP<TEXT, TEXT>,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Sessions table for TTL testing
CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY,
    user_id UUID,
    token TEXT,
    created_at TIMESTAMP
) WITH default_time_to_live = 0;

-- Enable CDC on all tables
ALTER TABLE users WITH cdc = {'enabled': true};
ALTER TABLE orders WITH cdc = {'enabled': true};
ALTER TABLE sessions WITH cdc = {'enabled': true};
