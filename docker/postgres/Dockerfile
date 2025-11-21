FROM postgres:16.1

# Install extensions
RUN apt-get update && apt-get install -y postgresql-16-partman

COPY init-db.sql /docker-entrypoint-initdb.d/

EXPOSE 5432
