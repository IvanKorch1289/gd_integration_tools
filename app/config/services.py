from pathlib import Path
from typing import ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import Field, computed_field, field_validator
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseSettingsWithLoader


__all__ = (
    "FileStorageSettings",
    "fs_settings",
    "LogStorageSettings",
    "log_settings",
    "RedisSettings",
    "CelerySettings",
    "celery_settings",
    "MailSettings",
    "mail_settings",
    "QueueSettings",
    "queue_settings",
    "TasksSettings",
    "tasks_settings",
    "GRPCSettings",
    "grpc_settings",
)


class FileStorageSettings(BaseSettingsWithLoader):
    """Settings for connecting to an S3-compatible object storage."""

    yaml_group: ClassVar[str] = "fs"
    model_config = SettingsConfigDict(env_prefix="FS_", extra="forbid")

    provider: Literal["minio", "aws", "other"] = Field(
        ...,
        description="Type of storage provider",
        example="minio",
    )
    bucket: str = Field(
        default="my-bucket",
        env="FS_BUCKET",
        description="Default bucket name",
        example="my-bucket",
    )
    access_key: str = Field(
        ...,
        description="Access key for the storage",
        example="AKIAIOSFODNN7EXAMPLE",
    )
    secret_key: str = Field(
        ...,
        description="Secret access key for the storage",
        example="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )
    endpoint: str = Field(
        ...,
        description="API endpoint URL of the storage",
        example="https://s3.example.com",
    )
    interface_endpoint: str = Field(
        ...,
        description="Web interface URL of the storage",
        example="https://console.s3.example.com",
    )
    use_ssl: bool = Field(
        ...,
        description="Use HTTPS for connections",
        example=True,
    )
    verify: bool = Field(
        ...,
        description="Verify SSL certificates",
        example=True,
    )
    ca_bundle: Optional[str] = Field(
        default=None,
        env="FS_CA_BUNDLE",
        description="Path to the CA certificate bundle for SSL",
        example="/path/to/ca-bundle.crt",
    )
    timeout: int = Field(
        ...,
        description="Timeout for operations (in seconds)",
        example=30,
    )
    retries: int = Field(
        ...,
        description="Number of retries for failed operations",
        example=3,
    )
    key_prefix: str = Field(
        ...,
        description="Prefix for object keys",
        example="my-prefix/",
    )
    max_pool_connections: int = Field(
        ...,
        description="Maximum number of connections in the pool",
        example=50,
    )
    read_timeout: int = Field(
        ...,
        description="Timeout for reading objects (in seconds)",
        example=30,
    )

    @computed_field
    def normalized_endpoint(self) -> str:
        """Returns the endpoint without the connection scheme (e.g., 'https://')."""
        return str(self.endpoint).split("://")[-1]


class LogStorageSettings(BaseSettingsWithLoader):
    """Settings for the logging and log storage system."""

    yaml_group: ClassVar[str] = "log"
    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        extra="forbid",
    )
    host: str = Field(
        ...,
        description="Log server host",
        example="logs.example.com",
    )
    port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="TCP port of the log server",
        example=514,
    )
    udp_port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="UDP port for sending logs",
        example=514,
    )
    conf_loggers: List[Dict] = Field(
        ...,
        default_factory=list,
        min_items=1,
        description="Configuration for loggers",
        example=[{"name": "application", "facility": "application"}],
    )
    use_tls: bool = Field(
        ...,
        description="Use TLS for secure connections",
        example=True,
    )
    ca_bundle: Optional[str] = Field(
        default=None,
        description="Path to the CA certificate bundle",
        example="/path/to/ca-bundle.crt",
    )
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        ...,
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Logging level of detail",
        example="INFO",
    )
    name_log_file: str = Field(
        ...,
        description="Path to the log file",
        example="app.log",
    )
    dir_log_name: str = Field(
        ...,
        description="Directory name for log files",
        example="/var/logs/myapp",
    )
    required_fields: List[str] = Field(
        ...,
        default_factory=list,
        min_items=1,
        description="Mandatory fields in log messages",
        example={"timestamp", "level", "message"},
    )

    @computed_field
    def base_url(self) -> str:
        """Constructs the normalized endpoint string."""
        return f"{self.host}:{self.port}"


class RedisSettings(BaseSettingsWithLoader):
    """Redis connection configuration settings."""

    yaml_group: ClassVar[str] = "redis"
    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        extra="forbid",
    )

    host: str = Field(
        ...,
        description="Redis server hostname or IP address",
        example="redis.example.com",
    )
    port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Redis server port number",
        example=6379,
    )
    db_cache: int = Field(
        ...,
        ge=0,
        description="Database number for caching operations",
        example=0,
    )
    db_queue: int = Field(
        ...,
        ge=0,
        description="Database number for queue management",
        example=1,
    )
    db_limits: int = Field(
        ..., ge=0, description="Database number for rate limiting", example=2
    )
    db_tasks: int = Field(
        ..., ge=0, description="Database number for Celery backend", example=3
    )
    name_tasks_queue: str = Field(
        ...,
        description="Name of the list for storing tasks in the queue",
        example="tasks",
    )
    password: Optional[str] = Field(
        ...,
        description="Password for Redis authentication",
        example="securepassword123",
    )
    encoding: str = Field(
        ...,
        description="Character encoding for data serialization",
        example="utf-8",
    )
    cache_expire_seconds: int = Field(
        ...,
        ge=60,
        description="Default expiration time for cached values in seconds",
        example=300,
    )
    max_connections: int = Field(
        ...,
        ge=1,
        description="Maximum number of connections in the connection pool",
        example=20,
    )
    use_ssl: bool = Field(
        ..., description="Enable SSL/TLS for secure connections", example=False
    )
    ca_bundle: Optional[str] = Field(
        ...,
        description="Path to CA certificate bundle for SSL verification",
        example="/path/to/ca_bundle.crt",
    )
    socket_timeout: Optional[int] = Field(
        ...,
        ge=1,
        description="Socket operation timeout in seconds",
        example=10,
    )
    socket_connect_timeout: Optional[int] = Field(
        ...,
        ge=1,
        description="Connection establishment timeout in seconds",
        example=5,
    )
    retry_on_timeout: Optional[bool] = Field(
        ...,
        description="Enable automatic retry on connection timeout",
        example=False,
    )
    socket_keepalive: Optional[bool] = Field(
        ..., description="Enable TCP keepalive for connections", example=True
    )
    main_stream: Optional[str] = Field(
        ..., description="Name of main Redis stream", example="example-stream"
    )
    dlq_stream: Optional[str] = Field(
        ...,
        description="Name of DLQ Redis stream",
        example="dlq-example-stream",
    )
    max_stream_len: int = Field(
        ..., description="Max size of Redis stream", example=100000
    )
    approximate_trimming_stream: bool = Field(
        ...,
        description="Enable approximate trimming for Redis streams",
        example=True,
    )
    retention_hours_stream: int = Field(
        ...,
        description="Retention time for Redis streams in hours",
        example=24,
    )
    max_retries: int = Field(
        ..., description="Max retries for reading message in stream", example=1
    )
    ttl_hours: int = Field(
        ..., description="Time to live messages in stream", example=1
    )
    health_check_interval: int = Field(
        ..., description="Healthchecking timer", example=600
    )
    streams: List[Dict[str, str]] = Field(
        ...,
        min_items=1,
        description="Redis streams list",
        example=[
            {
                "name": "stream1",
                "value": "creating-stream",
            },
            {
                "name": "stream2",
                "value": "updating-stream",
            },
        ],
    )

    @computed_field(description="Construct Redis connection URL")
    def redis_url(self) -> str:
        """Construct Redis connection URL."""
        protocol = "rediss" if self.use_ssl else "redis"
        auth = f":{self.password}@" if self.password else ""
        return f"{protocol}://{auth}{self.host}:{self.port}"

    @field_validator("port", "db_cache", "db_queue", "db_limits", "db_tasks")
    @classmethod
    def validate_redis_numbers(cls, v):
        if isinstance(v, int) and v < 0:
            raise ValueError("Value must be non-negative integer")
        return v

    def get_stream_name(self, stream_key: str) -> str:
        stream = next(
            (
                stream
                for stream in self.streams
                if stream.get("name", None) == stream_key
            ),
            None,
        )

        if not stream:
            raise ValueError(f"No stream configured for key: {stream_key}")

        return stream["value"]


class CelerySettings(BaseSettingsWithLoader):
    """Configuration for Celery task queue and worker management."""

    yaml_group: ClassVar[str] = "celery"
    model_config = SettingsConfigDict(
        env_prefix="CELERY_",
        extra="forbid",
    )

    redis_db: int = Field(
        ...,
        ge=0,
        description="Redis database number for Celery broker",
        example=0,
    )
    task_default_queue: str = Field(
        "default",
        description="Default queue name for task routing",
        example="default",
    )
    task_serializer: Literal["json", "pickle", "yaml", "msgpack"] = Field(
        ..., description="Serialization format for tasks", example="json"
    )
    task_time_limit: int = Field(
        ...,
        ge=60,
        description="Maximum time (seconds) a task can execute before being terminated",
        example=300,
    )
    task_soft_time_limit: int = Field(
        ...,
        ge=60,
        description="Time (seconds) after which task receives SIGTERM for graceful shutdown",
        example=240,
    )
    task_max_retries: int = Field(
        ...,
        ge=0,
        description="Maximum number of automatic retry attempts for failed tasks",
        example=3,
    )
    task_min_retries: int = Field(
        ...,
        ge=0,
        description="Minimum number of automatic retry attempts for failed tasks",
        example=1,
    )
    task_default_retry_delay: int = Field(
        ...,
        ge=0,
        description="Default delay (seconds) before retrying failed tasks",
        example=60,
    )
    task_retry_backoff: int = Field(
        ...,
        ge=0,
        description="Base backoff time (seconds) for retry delay calculations",
        example=10,
    )
    task_retry_jitter: bool = Field(
        ...,
        description="Enable random jitter to prevent retry stampedes",
        example=True,
    )
    countdown_time: int = Field(
        ...,
        ge=0,
        description="Initial delay (seconds) before task execution after submission",
        example=0,
    )
    worker_concurrency: int = Field(
        ...,
        ge=1,
        description="Number of concurrent worker processes/threads",
        example=4,
    )
    worker_prefetch_multiplier: int = Field(
        ...,
        ge=1,
        description="Multiplier for worker prefetch count (concurrency * multiplier)",
        example=4,
    )
    worker_max_tasks_per_child: int = Field(
        ...,
        ge=1,
        description="Maximum tasks a worker process executes before recycling",
        example=100,
    )
    worker_disable_rate_limits: bool = Field(
        ...,
        description="Disable task rate limiting for workers",
        example=False,
    )
    flower_url: str = Field(
        ...,
        description="URL endpoint for Flower monitoring dashboard",
        example="http://flower.example.com:5555",
    )
    flower_basic_auth: Optional[Tuple[str, str]] = Field(
        ...,
        description="Basic authentication credentials for Flower (username, password)",
        example=("admin", "secret"),
    )
    task_track_started: bool = Field(
        ..., description="Enable tracking of task STARTED state", example=True
    )
    broker_pool_limit: int = Field(
        ...,
        ge=1,
        description="Maximum number of broker connections in the pool",
        example=10,
    )
    result_extended: bool = Field(
        ...,
        description="Enable extended result metadata storage",
        example=True,
    )
    worker_send_events: bool = Field(
        ...,
        description="Enable sending task-related events for monitoring",
        example=True,
    )

    @field_validator("flower_basic_auth")
    @classmethod
    def validate_auth(cls, v):
        if v and (len(v) != 2 or not all(isinstance(i, str) for i in v)):
            raise ValueError(
                "Auth must be tuple of two strings (username, password)"
            )
        return v


class MailSettings(BaseSettingsWithLoader):
    """Email service configuration settings."""

    yaml_group: ClassVar[str] = "mail"
    model_config = SettingsConfigDict(
        env_prefix="MAIL_",
        extra="forbid",
    )

    host: str = Field(
        ..., description="SMTP server hostname", example="smtp.example.com"
    )
    port: int = Field(
        ..., ge=1, le=65535, description="SMTP server port number", example=587
    )
    connection_pool_size: int = Field(
        ..., ge=1, le=20, description="Size of SMTP connection pool", example=5
    )
    connect_timeout: int = Field(
        ...,
        ge=5,
        le=30,
        description="Timeout for connection in seconds",
        example=30,
    )
    command_timeout: int = Field(
        ...,
        ge=5,
        le=300,
        description="Network operation timeout in seconds",
        example=30,
    )
    username: str = Field(
        ...,
        description="SMTP authentication username",
        example="user@example.com",
    )
    password: str = Field(
        ...,
        description="SMTP authentication password",
        example="securepassword123",
    )
    use_tls: bool = Field(
        ..., description="Enable STARTTLS for secure connections", example=True
    )
    validate_certs: bool = Field(
        ..., description="Validate server SSL/TLS certificates", example=True
    )
    ca_bundle: Optional[Path] = Field(
        ...,
        description="Path to custom CA certificate bundle",
        example="/path/to/ca_bundle.crt",
    )
    sender: str = Field(
        ...,
        description="Default sender email address",
        example="noreply@example.com",
    )
    template_folder: Optional[Path] = Field(
        ...,
        description="Path to email template directory",
        example="/app/email_templates",
    )
    circuit_breaker_max_failures: int = Field(
        ...,
        ge=0,
        description="Maximum number of failures before circuit breaker trips",
        example=5,
    )
    circuit_breaker_reset_timeout: int = Field(
        ...,
        ge=0,
        description="Time (seconds) to wait before resetting circuit breaker",
        example=60,
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v, values):
        if v == 465 and not values.data.get("use_tls"):
            raise ValueError("Port 465 requires SSL/TLS to be enabled")
        return v

    @field_validator("ca_bundle")
    @classmethod
    def validate_ca_path(cls, v):
        if v and not v.exists():
            raise ValueError(f"CA bundle file not found: {v}")
        return v


class QueueSettings(BaseSettingsWithLoader):
    """Message queue broker configuration settings."""

    yaml_group: ClassVar[str] = "queue"
    model_config = SettingsConfigDict(
        env_prefix="QUEUE_",
        extra="forbid",
    )

    type: Literal["kafka", "rabbitmq"] = Field(
        ..., description="Message broker type", example="kafka"
    )
    host: str = Field(
        ...,
        description="Broker hostname",
        example="broker.example.com",
    )
    port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Broker port number",
    )
    ui_port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Broker UI port number",
        example=9121,
    )
    timeout: int = Field(
        ...,
        ge=5,
        le=300,
        description="Broker connection timeout in seconds",
        example=30,
    )
    reconnect_interval: int = Field(
        ...,
        ge=5,
        le=300,
        description="Interval between reconnection attempts in seconds",
        example=60,
    )
    max_consumers: int = Field(
        ...,
        ge=1,
        description="Maximum number of consumer instances",
        example=10,
    )
    graceful_timeout: int = Field(
        ...,
        ge=5,
        le=300,
        description="Graceful shutdown timeout in seconds",
        example=60,
    )
    use_ssl: bool = Field(
        ..., description="Enable SSL/TLS for secure connections", example=True
    )
    ca_bundle: Optional[Path] = Field(
        ...,
        description="Path to CA certificate file",
        example="/path/to/ca.pem",
    )
    username: Optional[str] = Field(
        ..., description="Authentication username", example="kafka-user"
    )
    password: Optional[str] = Field(
        ...,
        description="authentication password",
        example="securepassword123",
    )
    topics: List[Dict[str, str]] = Field(
        ...,
        min_items=1,
        description="Topic list",
        example=[
            {
                "name": "topic1",
                "value": "creating-topic",
            },
            {
                "name": "topic2",
                "value": "updating-topic",
            },
        ],
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v, values):
        if v == 465 and not values.data.get("use_tls"):
            raise ValueError("Port 465 requires SSL/TLS to be enabled")
        return v

    @field_validator("ca_bundle")
    @classmethod
    def validate_ca_path(cls, v):
        if v and not v.exists():
            raise ValueError(f"CA bundle file not found: {v}")
        return v

    @computed_field(description="Construct Queue connection URL")
    def queue_url(self) -> str:
        """Construct Queue connection URL."""
        return (
            f"amqp://{self.username}:{self.password}@{self.host}:{self.port}/"
        )

    @computed_field(description="Construct Queue connection URL")
    def queue_ui_url(self) -> str:
        """Construct Queue connection URL."""
        return f"{self.host}:{self.ui_port}"

    def get_topic_name(self, topic_key: str) -> str:
        # Optimized lookup using generator expression
        topic = next(
            (
                topic
                for topic in self.topics
                if topic.get("name", None) == topic_key
            ),
            None,
        )

        if not topic:
            raise ValueError(f"No topic configured for key: {topic_key}")

        return topic["value"]


class TasksSettings(BaseSettingsWithLoader):
    """Configuration for TaskiQ task queue and worker management."""

    yaml_group: ClassVar[str] = "tasks"
    model_config = SettingsConfigDict(
        env_prefix="TASKS_",
        extra="forbid",
    )

    task_max_attempts: int = Field(
        ...,
        description="Maximum number of attempts for a task",
        example=5,
    )
    task_seconds_delay: int = Field(
        ...,
        description="Initial delay in seconds for a task",
        example=60,
    )
    task_retry_jitter_factor: float = Field(
        ...,
        description="Jitter factor for exponential backoff",
        example=0.5,
    )
    task_timeout_seconds: int = Field(
        ...,
        description="Maximum execution time in seconds for a task",
        example=3600,
    )
    flow_max_attempts: int = Field(
        ...,
        description="Maximum number of attempts for a flow",
        example=5,
    )
    flow_seconds_delay: int = Field(
        ...,
        description="Initial delay in seconds for a flow",
        example=60,
    )
    flow_retry_jitter_factor: float = Field(
        ...,
        description="Jitter factor for exponential backoff",
        example=0.5,
    )
    flow_timeout_seconds: int = Field(
        ...,
        description="Maximum execution time in seconds for a flow",
        example=3600,
    )


class GRPCSettings(BaseSettingsWithLoader):
    """Configuration for gRPC services."""

    yaml_group: ClassVar[str] = "grpc"
    model_config = SettingsConfigDict(
        env_prefix="GRPC_",
        extra="forbid",
    )

    socket_path: str = Field(
        ...,
        description="Path to the gRPC socket file",
        example="/tmp/grpc.sock",
    )
    max_workers: int = Field(
        ...,
        description="Maximum number of gRPC worker processes",
        example=10,
    )

    @computed_field(description="Construct Socket connection")
    def socket_uri(self) -> str:
        return f"unix://{self.socket_path}"


# Instantiate settings for immediate use
fs_settings = FileStorageSettings()
log_settings = LogStorageSettings()
redis_settings = RedisSettings()
celery_settings = CelerySettings()
mail_settings = MailSettings()
queue_settings = QueueSettings()
tasks_settings = TasksSettings()
grpc_settings = GRPCSettings()
