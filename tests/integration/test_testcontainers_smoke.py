"""Smoke test для testcontainers infrastructure (P2: audit 2026-09-21).

Проверяет, что testcontainers PostgreSQL + Redis fixtures запускаются
и доступны. Это минимальный proof-of-life для CI/CD pipeline.

Запуск:
    sg docker -c ".venv/bin/python -m pytest tests/integration/test_testcontainers_smoke.py -v"

Требования:
- Docker daemon доступен (через sg docker или membership в docker group)
- testcontainers[postgres,redis]>=4.7.2 установлен
- pytest может поднять контейнер (timeout 60s на pull image)
"""

from __future__ import annotations

import time

import pytest


@pytest.mark.integration
@pytest.mark.testcontainers
@pytest.mark.timeout(180)  # first pull может занять время
class TestTestcontainersSmoke:
    """Verify testcontainers поднимают PostgreSQL + Redis."""

    def test_postgres_container_starts(self) -> None:
        """PostgresContainer должен start за разумное время."""
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError:
            pytest.skip("testcontainers[postgres] не установлен")

        start = time.time()
        with PostgresContainer("postgres:16-alpine") as pg:
            elapsed = time.time() - start
            url = pg.get_connection_url()
            assert url.startswith("postgresql"), f"unexpected URL: {url}"
            # Smoke check: не длиннее 120s на первый pull + start
            assert elapsed < 120, f"container start took {elapsed:.1f}s"

    def test_redis_container_starts(self) -> None:
        """RedisContainer должен start."""
        try:
            from testcontainers.redis import RedisContainer
        except ImportError:
            pytest.skip("testcontainers[redis] не установлен")

        start = time.time()
        with RedisContainer() as redis_c:
            elapsed = time.time() - start
            # RedisContainer.get_client() возвращает redis.Redis instance
            client = redis_c.get_client()
            assert client.ping() is True
            assert elapsed < 120, f"container start took {elapsed:.1f}s"

    def test_postgres_can_execute_query(self) -> None:
        """PostgresContainer — реальный SQL round-trip."""
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError:
            pytest.skip("testcontainers[postgres] не установлен")

        with PostgresContainer("postgres:16-alpine") as pg:
            # get_connection_url() возвращает postgresql+psycopg2:// — для psycopg.
            url = pg.get_connection_url()
            # strip driver prefix для psycopg2.connect
            psycopg_url = url.replace("postgresql+psycopg2://", "postgresql://")
            import psycopg2

            conn = psycopg2.connect(psycopg_url)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 + 1 AS sum")
                    row = cur.fetchone()
                    assert row is not None
                    assert row[0] == 2
            finally:
                conn.close()

    def test_redis_can_ping(self) -> None:
        """RedisContainer — реальный PING round-trip."""
        try:
            from testcontainers.redis import RedisContainer
        except ImportError:
            pytest.skip("testcontainers[redis] не установлен")

        with RedisContainer() as redis_c:
            client = redis_c.get_client()
            assert client.ping() is True
            client.set("test_key", "test_value", ex=10)
            assert client.get("test_key") == b"test_value"

    def test_rabbitmq_container_starts(self) -> None:
        """RabbitMQContainer должен start + accept AMQP connection."""
        try:
            from testcontainers.rabbitmq import RabbitMqContainer
        except ImportError:
            pytest.skip("testcontainers[rabbitmq] не установлен")

        start = time.time()
        with RabbitMqContainer("rabbitmq:3.13-management-alpine") as rabbit:
            elapsed = time.time() - start
            assert elapsed < 180, f"container start took {elapsed:.1f}s"
            # Connection params доступны (RabbitMqContainer.get_connection_params())
            params = rabbit.get_connection_params()
            assert params.host is not None
            assert params.port > 0

    def test_rabbitmq_publish_consume(self) -> None:
        """RabbitMQContainer — publish + consume round-trip."""
        try:
            from testcontainers.rabbitmq import RabbitMqContainer
        except ImportError:
            pytest.skip("testcontainers[rabbitmq] не установлен")

        with RabbitMqContainer("rabbitmq:3.13-management-alpine") as rabbit:
            import pika

            # Use explicit AMQP 0-9-1 (default) с правильным хостом
            params = pika.ConnectionParameters(
                host=rabbit.get_container_host_ip(),
                port=rabbit.get_exposed_port(5672),
                connection_attempts=3,
                retry_delay=1,
            )
            conn = pika.BlockingConnection(params)
            try:
                ch = conn.channel()
                ch.queue_declare(queue="test_queue", durable=False)
                ch.basic_publish(exchange="", routing_key="test_queue", body=b"hello")
                method, props, body = ch.basic_get(queue="test_queue", auto_ack=True)
                assert body == b"hello"
            finally:
                conn.close()

    def test_kafka_container_starts(self) -> None:
        """KafkaContainer должен start + accept bootstrap connection."""
        try:
            from testcontainers.kafka import KafkaContainer
        except ImportError:
            pytest.skip("testcontainers[kafka] не установлен")

        start = time.time()
        with KafkaContainer() as kafka:
            elapsed = time.time() - start
            assert elapsed < 180, f"container start took {elapsed:.1f}s"
            bootstrap = kafka.get_bootstrap_server()
            assert bootstrap.startswith("PLAINTEXT://") or ":" in bootstrap

    def test_kafka_produce_consume(self) -> None:
        """KafkaContainer — produce + consume round-trip."""
        try:
            from testcontainers.kafka import KafkaContainer
        except ImportError:
            pytest.skip("testcontainers[kafka] не установлен")

        try:
            from kafka import KafkaConsumer, KafkaProducer
        except ImportError:
            pytest.skip("kafka-python не установлен")

        with KafkaContainer() as kafka:
            bootstrap = kafka.get_bootstrap_server()
            # KafkaContainer returns "PLAINTEXT://host:port" — strip scheme
            if bootstrap.startswith("PLAINTEXT://"):
                bootstrap = bootstrap[len("PLAINTEXT://") :]

            producer = KafkaProducer(bootstrap_servers=bootstrap)
            future = producer.send("test_topic", b"hello-kafka")
            future.get(timeout=10)
            producer.flush(timeout=10)
            producer.close()

            consumer = KafkaConsumer(
                "test_topic",
                bootstrap_servers=bootstrap,
                group_id="test-group",
                auto_offset_reset="earliest",
                consumer_timeout_ms=10000,
            )
            messages = list(consumer)
            consumer.close()
            assert len(messages) >= 1
            assert messages[0].value == b"hello-kafka"
