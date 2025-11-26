FROM cassandra:4.1.3

# Install required packages for Debezium agent
RUN apt-get update && \
    apt-get install -y wget curl openjdk-11-jre-headless && \
    rm -rf /var/lib/apt/lists/*

# Enable CDC in Cassandra configuration
RUN echo "cdc_enabled: true" >> /etc/cassandra/cassandra.yaml && \
    echo "cdc_raw_directory: /var/lib/cassandra/cdc_raw" >> /etc/cassandra/cassandra.yaml && \
    mkdir -p /var/lib/cassandra/cdc_raw && \
    mkdir -p /var/lib/cassandra/cdc_offsets

# Download Debezium Cassandra 4 connector agent (2.7.0.Final)
# This is a standalone agent that monitors Cassandra CDC and publishes to Kafka
RUN mkdir -p /opt/debezium && \
    cd /opt/debezium && \
    wget -q https://repo1.maven.org/maven2/io/debezium/debezium-connector-cassandra-4/2.7.0.Final/debezium-connector-cassandra-4-2.7.0.Final-jar-with-dependencies.jar && \
    mv debezium-connector-cassandra-4-2.7.0.Final-jar-with-dependencies.jar debezium-cassandra-agent.jar

# Create directory for Debezium configuration
RUN mkdir -p /opt/debezium/conf

# Copy Debezium agent configuration
COPY debezium-cassandra.properties /opt/debezium/conf/
COPY cassandra-driver.conf /opt/debezium/conf/
COPY start-debezium-agent.sh /opt/debezium/

# Copy Cassandra initialization scripts
COPY init-schema.cql /docker-entrypoint-initdb.d/
COPY enable-cdc.sh /docker-entrypoint-initdb.d/

# Make scripts executable
RUN chmod +x /docker-entrypoint-initdb.d/enable-cdc.sh && \
    chmod +x /opt/debezium/start-debezium-agent.sh

# Note: The Debezium agent will be started manually or via a separate process manager
# after Cassandra is fully initialized. For production use, consider using supervisord
# or a similar process manager to run both Cassandra and the agent.

EXPOSE 9042 9160
