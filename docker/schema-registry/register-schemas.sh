#!/bin/bash
set -e

SCHEMA_REGISTRY_URL="${SCHEMA_REGISTRY_URL:-http://schema-registry:8081}"
SCHEMAS_DIR="${SCHEMAS_DIR:-/schemas}"

MAX_RETRIES=30
RETRY_DELAY=5

echo "========================================"
echo "Schema Registry Configuration"
echo "========================================"
echo "Schema Registry URL: $SCHEMA_REGISTRY_URL"
echo "Schemas Directory: $SCHEMAS_DIR"
echo ""

wait_for_schema_registry() {
    echo "Waiting for Schema Registry to be ready..."

    for i in $(seq 1 $MAX_RETRIES); do
        if curl -s "$SCHEMA_REGISTRY_URL" > /dev/null 2>&1; then
            echo "Schema Registry is ready!"
            return 0
        fi

        echo "Attempt $i/$MAX_RETRIES: Schema Registry not ready. Retrying in ${RETRY_DELAY}s..."
        sleep $RETRY_DELAY
    done

    echo "ERROR: Schema Registry did not become ready after $MAX_RETRIES attempts"
    exit 1
}

register_schema() {
    local subject=$1
    local schema_file=$2

    echo "----------------------------------------"
    echo "Registering schema: $subject"
    echo "----------------------------------------"

    if [ ! -f "$schema_file" ]; then
        echo "ERROR: Schema file not found: $schema_file"
        return 1
    fi

    schema=$(cat "$schema_file" | jq -c '.')

    payload=$(jq -n \
        --arg schema "$schema" \
        '{schema: $schema}')

    echo "Posting schema to $SCHEMA_REGISTRY_URL/subjects/$subject/versions"

    response=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Content-Type: application/vnd.schemaregistry.v1+json" \
        --data "$payload" \
        "$SCHEMA_REGISTRY_URL/subjects/$subject/versions")

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -eq 200 ] || [ "$http_code" -eq 201 ]; then
        schema_id=$(echo "$body" | jq -r '.id')
        echo "✓ Schema registered successfully (ID: $schema_id)"
    else
        echo "✗ Failed to register schema (HTTP $http_code)"
        echo "$body" | jq '.' 2>/dev/null || echo "$body"
        return 1
    fi

    echo ""
}

set_compatibility() {
    local subject=$1
    local compatibility=$2

    echo "Setting compatibility mode for $subject to $compatibility..."

    response=$(curl -s -w "\n%{http_code}" -X PUT \
        -H "Content-Type: application/vnd.schemaregistry.v1+json" \
        --data "{\"compatibility\": \"$compatibility\"}" \
        "$SCHEMA_REGISTRY_URL/config/$subject")

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -eq 200 ]; then
        echo "✓ Compatibility mode set successfully"
    else
        echo "✗ Failed to set compatibility mode (HTTP $http_code)"
        echo "$body" | jq '.' 2>/dev/null || echo "$body"
    fi

    echo ""
}

list_registered_schemas() {
    echo "========================================"
    echo "Registered Schemas Summary"
    echo "========================================"

    subjects=$(curl -s "$SCHEMA_REGISTRY_URL/subjects")

    if [ $? -eq 0 ]; then
        echo "$subjects" | jq -r '.[]' 2>/dev/null || echo "$subjects"
    else
        echo "Failed to retrieve schema list"
    fi

    echo ""
}

wait_for_schema_registry

mkdir -p "$SCHEMAS_DIR"

cat > "$SCHEMAS_DIR/change-event-key.avsc" << 'EOF'
{
  "type": "record",
  "name": "ChangeEventKey",
  "namespace": "com.cdc.events",
  "fields": [
    {
      "name": "event_id",
      "type": "string"
    },
    {
      "name": "partition_key_hash",
      "type": ["null", "string"],
      "default": null
    }
  ]
}
EOF

cat > "$SCHEMAS_DIR/change-event-value.avsc" << 'EOF'
{
  "type": "record",
  "name": "ChangeEventValue",
  "namespace": "com.cdc.events",
  "fields": [
    {
      "name": "event_id",
      "type": "string"
    },
    {
      "name": "source_table",
      "type": "string"
    },
    {
      "name": "operation_type",
      "type": {
        "type": "enum",
        "name": "OperationType",
        "symbols": ["CREATE", "UPDATE", "DELETE", "TRUNCATE"]
      }
    },
    {
      "name": "timestamp_micros",
      "type": "long"
    },
    {
      "name": "before",
      "type": [
        "null",
        {
          "type": "map",
          "values": ["null", "string", "long", "double"]
        }
      ],
      "default": null
    },
    {
      "name": "after",
      "type": [
        "null",
        {
          "type": "map",
          "values": ["null", "string", "long", "double"]
        }
      ],
      "default": null
    },
    {
      "name": "schema_version",
      "type": "int"
    },
    {
      "name": "ttl_seconds",
      "type": ["null", "int"],
      "default": null
    },
    {
      "name": "is_tombstone",
      "type": "boolean",
      "default": false
    }
  ]
}
EOF

echo "Registering Change Event schemas..."
echo ""

register_schema "cdc-events-users-key" "$SCHEMAS_DIR/change-event-key.avsc"
register_schema "cdc-events-users-value" "$SCHEMAS_DIR/change-event-value.avsc"

register_schema "cdc-events-orders-key" "$SCHEMAS_DIR/change-event-key.avsc"
register_schema "cdc-events-orders-value" "$SCHEMAS_DIR/change-event-value.avsc"

echo "Setting compatibility modes..."
echo ""

set_compatibility "cdc-events-users-value" "BACKWARD"
set_compatibility "cdc-events-orders-value" "BACKWARD"

list_registered_schemas

echo "========================================"
echo "Schema registration complete!"
echo "========================================"
