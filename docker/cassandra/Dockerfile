FROM cassandra:4.1.3

# Enable CDC
RUN echo "cdc_enabled: true" >> /etc/cassandra/cassandra.yaml
RUN echo "cdc_raw_directory: /var/lib/cassandra/cdc_raw" >> /etc/cassandra/cassandra.yaml

# Copy initialization scripts
COPY init-schema.cql /docker-entrypoint-initdb.d/
COPY enable-cdc.sh /docker-entrypoint-initdb.d/

RUN chmod +x /docker-entrypoint-initdb.d/enable-cdc.sh

EXPOSE 9042 9160
