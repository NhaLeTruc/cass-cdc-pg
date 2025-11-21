#!/bin/bash
# Enable CDC on Cassandra tables

echo "Waiting for Cassandra to be ready..."
sleep 30

echo "CDC is enabled via cassandra.yaml configuration"
echo "CDC directory: /var/lib/cassandra/cdc_raw"
