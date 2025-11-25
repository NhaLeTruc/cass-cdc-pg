FROM confluentinc/cp-kafka-connect:7.5.2

USER root

# Install JDBC Sink Connector from Confluent Hub (for PostgreSQL sink)
# This is the critical connector needed for Kafka -> PostgreSQL replication
RUN confluent-hub install --no-prompt confluentinc/kafka-connect-jdbc:10.7.4

# Note: For Cassandra CDC (Change Data Capture), this project likely uses one of:
# 1. Cassandra native CDC with custom Kafka producer
# 2. Debezium Server (standalone) configured separately
# 3. DataStax CDC connector (commercial)
#
# The "cassandra-source" connector mentioned in tests may be:
# - A custom implementation in this project
# - A placeholder for future implementation
# - Configuration for an external CDC tool
#
# For now, we install the JDBC connector which enables the postgres-sink tests

# Set proper permissions
RUN chown -R appuser:appuser /usr/share/confluent-hub-components

USER appuser

# The CONNECT_PLUGIN_PATH environment variable in docker-compose.yml already includes:
# /usr/share/java,/usr/share/confluent-hub-components,/opt/transforms
# So the installed connectors will be discovered automatically
