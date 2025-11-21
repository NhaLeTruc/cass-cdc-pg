#!/usr/bin/env python3

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cassandra.cluster import Cluster
from cassandra.query import BatchStatement, ConsistencyLevel
from faker import Faker

fake = Faker()


def connect_to_cassandra(host: str = "localhost", port: int = 9042) -> Any:
    try:
        cluster = Cluster([host], port=port)
        session = cluster.connect("warehouse")
        print(f"✓ Connected to Cassandra at {host}:{port}")
        return session
    except Exception as e:
        print(f"✗ Failed to connect to Cassandra: {e}")
        sys.exit(1)


def generate_users(session: Any, count: int, batch_size: int = 100) -> list[uuid.UUID]:
    user_ids = []
    print(f"Generating {count} users...")

    prepare_insert = session.prepare(
        """
        INSERT INTO users (
            id, username, email, age, balance, is_active,
            preferences, tags, phone_numbers, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    )

    for i in range(0, count, batch_size):
        batch = BatchStatement(consistency_level=ConsistencyLevel.ONE)
        batch_count = min(batch_size, count - i)

        for _ in range(batch_count):
            user_id = uuid.uuid4()
            user_ids.append(user_id)

            preferences = {
                fake.word(): fake.word() for _ in range(fake.random_int(min=1, max=5))
            }
            tags = {fake.word() for _ in range(fake.random_int(min=1, max=5))}
            phone_numbers = [fake.phone_number() for _ in range(fake.random_int(min=1, max=3))]
            created_at = fake.date_time_between(start_date="-2y", end_date="now")
            updated_at = fake.date_time_between(start_date=created_at, end_date="now")

            batch.add(
                prepare_insert,
                (
                    user_id,
                    fake.user_name(),
                    fake.email(),
                    fake.random_int(min=18, max=80),
                    Decimal(str(fake.random_int(min=0, max=100000))),
                    fake.boolean(),
                    preferences,
                    tags,
                    phone_numbers,
                    created_at,
                    updated_at,
                ),
            )

        session.execute(batch)
        completed = i + batch_count
        print(f"  Progress: {completed}/{count} users ({completed * 100 // count}%)")

    print(f"✓ Generated {count} users")
    return user_ids


def generate_orders(
    session: Any, user_ids: list[uuid.UUID], count: int, batch_size: int = 100
) -> list[uuid.UUID]:
    order_ids = []
    print(f"Generating {count} orders...")

    prepare_insert = session.prepare(
        """
        INSERT INTO orders (
            id, user_id, order_number, total_amount, status,
            items, metadata, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    )

    statuses = ["pending", "processing", "shipped", "delivered", "cancelled"]

    for i in range(0, count, batch_size):
        batch = BatchStatement(consistency_level=ConsistencyLevel.ONE)
        batch_count = min(batch_size, count - i)

        for _ in range(batch_count):
            order_id = uuid.uuid4()
            order_ids.append(order_id)

            user_id = fake.random_element(elements=user_ids)
            items = [
                f"{fake.word()}-{fake.random_int(min=1, max=999)}"
                for _ in range(fake.random_int(min=1, max=10))
            ]
            metadata = {fake.word(): fake.word() for _ in range(fake.random_int(min=1, max=5))}
            created_at = fake.date_time_between(start_date="-1y", end_date="now")
            updated_at = fake.date_time_between(start_date=created_at, end_date="now")

            batch.add(
                prepare_insert,
                (
                    order_id,
                    user_id,
                    fake.random_int(min=1000000, max=9999999),
                    Decimal(str(fake.random_int(min=10, max=10000))),
                    fake.random_element(elements=statuses),
                    items,
                    metadata,
                    created_at,
                    updated_at,
                ),
            )

        session.execute(batch)
        completed = i + batch_count
        print(f"  Progress: {completed}/{count} orders ({completed * 100 // count}%)")

    print(f"✓ Generated {count} orders")
    return order_ids


def generate_sessions(
    session: Any, user_ids: list[uuid.UUID], count: int, batch_size: int = 100
) -> None:
    print(f"Generating {count} sessions...")

    prepare_insert = session.prepare(
        """
        INSERT INTO sessions (session_id, user_id, token, created_at)
        VALUES (?, ?, ?, ?)
        """
    )

    for i in range(0, count, batch_size):
        batch = BatchStatement(consistency_level=ConsistencyLevel.ONE)
        batch_count = min(batch_size, count - i)

        for _ in range(batch_count):
            session_id = uuid.uuid4()
            user_id = fake.random_element(elements=user_ids)
            token = fake.sha256()
            created_at = fake.date_time_between(start_date="-7d", end_date="now")

            batch.add(prepare_insert, (session_id, user_id, token, created_at))

        session.execute(batch)
        completed = i + batch_count
        print(f"  Progress: {completed}/{count} sessions ({completed * 100 // count}%)")

    print(f"✓ Generated {count} sessions")


def verify_data_counts(session: Any) -> None:
    print("\nVerifying data counts...")

    tables = ["users", "orders", "sessions"]
    for table in tables:
        result = session.execute(f"SELECT COUNT(*) FROM {table}")
        count = result.one()[0]
        print(f"  {table}: {count} records")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate realistic test data for Cassandra CDC pipeline"
    )
    parser.add_argument(
        "--host", default="localhost", help="Cassandra host (default: localhost)"
    )
    parser.add_argument("--port", type=int, default=9042, help="Cassandra port (default: 9042)")
    parser.add_argument(
        "--users", type=int, default=10000, help="Number of users to generate (default: 10000)"
    )
    parser.add_argument(
        "--orders", type=int, default=10000, help="Number of orders to generate (default: 10000)"
    )
    parser.add_argument(
        "--sessions",
        type=int,
        default=1000,
        help="Number of sessions to generate (default: 1000)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=100, help="Batch size for inserts (default: 100)"
    )
    parser.add_argument(
        "--clear", action="store_true", help="Clear existing data before generating"
    )

    args = parser.parse_args()

    if args.users < 10000:
        print(
            f"⚠ Warning: Generating {args.users} users. SC-001 correctness requirement "
            "specifies minimum 10,000 records per table."
        )

    if args.orders < 10000:
        print(
            f"⚠ Warning: Generating {args.orders} orders. SC-001 correctness requirement "
            "specifies minimum 10,000 records per table."
        )

    session = connect_to_cassandra(args.host, args.port)

    if args.clear:
        print("\nClearing existing data...")
        session.execute("TRUNCATE users")
        session.execute("TRUNCATE orders")
        session.execute("TRUNCATE sessions")
        print("✓ Cleared existing data")

    print("\n" + "=" * 60)
    print("GENERATING TEST DATA")
    print("=" * 60)

    user_ids = generate_users(session, args.users, args.batch_size)
    generate_orders(session, user_ids, args.orders, args.batch_size)
    generate_sessions(session, user_ids, args.sessions, args.batch_size)

    print("\n" + "=" * 60)
    verify_data_counts(session)
    print("=" * 60)
    print("\n✓ Test data generation complete!")


if __name__ == "__main__":
    main()
