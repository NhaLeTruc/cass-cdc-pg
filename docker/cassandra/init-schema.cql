-- Create keyspace for CDC pipeline testing
CREATE KEYSPACE IF NOT EXISTS warehouse
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE warehouse;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username TEXT,
    email TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY,
    user_id UUID,
    total_amount DECIMAL,
    status TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Enable CDC on tables
ALTER TABLE users WITH cdc = true;
ALTER TABLE orders WITH cdc = true;
