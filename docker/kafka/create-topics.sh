#!/bin/bash
# Create Kafka topics for CDC pipeline

kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists \
  --topic cdc-events-users --partitions 8 --replication-factor 1 \
  --config retention.ms=604800000

kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists \
  --topic cdc-events-orders --partitions 8 --replication-factor 1 \
  --config retention.ms=604800000

kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists \
  --topic dlq-events --partitions 1 --replication-factor 1 \
  --config retention.ms=2592000000

kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists \
  --topic schema-changes --partitions 1 --replication-factor 1 \
  --config retention.ms=31536000000

echo "Kafka topics created successfully"
