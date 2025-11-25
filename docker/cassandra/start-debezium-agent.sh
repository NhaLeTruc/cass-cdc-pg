#!/bin/bash
# Debezium Cassandra CDC Agent Startup Script
# This script waits for Cassandra to be ready, then starts the Debezium agent
# to monitor CDC commit logs and publish events to Kafka.

set -e

echo "[Debezium Agent] Waiting for Cassandra to be ready..."

# Wait for Cassandra to be fully started
until cqlsh -e "describe cluster" > /dev/null 2>&1; do
    echo "[Debezium Agent] Waiting for Cassandra CQL to be available..."
    sleep 5
done

echo "[Debezium Agent] Cassandra is ready!"

# Wait for Kafka to be available
echo "[Debezium Agent] Waiting for Kafka to be ready..."
until timeout 5 bash -c 'cat < /dev/null > /dev/tcp/kafka/9092' 2>/dev/null; do
    echo "[Debezium Agent] Waiting for Kafka to be available..."
    sleep 5
done

echo "[Debezium Agent] Kafka is ready!"

# Give services a moment to stabilize
sleep 10

echo "[Debezium Agent] Starting Debezium Cassandra CDC Agent..."

# Start the Debezium agent
cd /opt/debezium

java -jar debezium-cassandra-agent.jar \
    --config-file=conf/debezium-cassandra.properties \
    --log-level=INFO

echo "[Debezium Agent] Agent stopped"
