from activityual_common.config import ApiSettings, CommonSettings
from pydantic import SecretStr


class TrackingApiSettings(ApiSettings):
    service_name: str = "tracking-api"


class WorkerSettings(CommonSettings):
    service_name: str = "tracking-worker"
    tracking_db_url: SecretStr | None = None
    publisher_db_url: SecretStr | None = None
    event_bus_name: str = "activityual-bus"
    sqs_tracking_activity_queue_url: str = ""
    aws_region: str = "ap-south-1"
    aws_endpoint_url: str | None = None

    relay_batch_size: int = 25
    relay_lease_seconds: int = 60
    relay_max_attempts: int = 25
    relay_poll_seconds: float = 2.0
    relay_cleanup_interval_seconds: int = 3600
    relay_retention_days: int = 7

    overdue_batch_size: int = 100
    overdue_period_seconds: float = 30.0

    generation_horizon_days: int = 6
    generation_batch_schedules: int = 50
    generation_batch_days: int = 31
    generation_max_lookback_days: int = 60
    generation_period_seconds: float = 300.0

    consumer_wait_seconds: int = 20
    consumer_idle_pause_seconds: float = 0.0
    consumer_max_messages: int = 10

    db_pool_size: int = 2
    db_max_overflow: int = 1
    db_pool_timeout: float = 5.0