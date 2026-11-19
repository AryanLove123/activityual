"""Start the worker:  python -m tracking_service.worker   (Ctrl+C to stop)."""

import logging
import signal
import threading

from activityual_common.db import make_engine, make_session_factory
from activityual_common.logging import configure_logging

from ..settings import WorkerSettings
from .loops import (
    ActivityEventConsumer,
    Loop,
    OccurrenceGenerator,
    OutboxRelay,
    OverdueProcessor,
)

log = logging.getLogger("activityual.worker")


def main() -> int:
    s = WorkerSettings()
    configure_logging(s.service_name, s.log_level)
    if s.tracking_db_url is None or s.publisher_db_url is None:
        raise SystemExit("TRACKING_DB_URL and PUBLISHER_DB_URL are required")
    kw = {
        "pool_size": s.db_pool_size,
        "max_overflow": s.db_max_overflow,
        "pool_timeout": s.db_pool_timeout,
    }
    tracking_engine = make_engine(
        s.tracking_db_url.get_secret_value(),
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_timeout=s.db_pool_timeout,
    )
    publisher_engine = make_engine(s.publisher_db_url.get_secret_value(), **kw)
    tracking, publisher = (
        make_session_factory(tracking_engine),
        make_session_factory(publisher_engine),
    )

    wake = (
        threading.Event()
    )  # the consumer sets it so the generator runs right after a new event
    stop = threading.Event()
    loops = [
        Loop("relay", s.relay_poll_seconds, OutboxRelay(publisher, s).step),
        Loop("overdue", s.overdue_period_seconds, OverdueProcessor(tracking, s).step),
        Loop(
            "generator",
            s.generation_period_seconds,
            OccurrenceGenerator(tracking, s).step,
            wake,
        ),
        Loop(
            "consumer",
            s.consumer_idle_pause_seconds,
            ActivityEventConsumer(tracking, s, wake).step,
        ),
    ]
    signal.signal(signal.SIGINT, lambda *_: stop.set())  # a handler only sets a flag
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threads = [
        threading.Thread(target=lp.run, args=(stop,), name=lp.name, daemon=True)
        for lp in loops
    ]
    for t in threads:
        t.start()
    log.info("worker started")
    stop.wait()  # main thread just waits for Ctrl+C
    for t in threads:
        t.join(timeout=30)
    tracking_engine.dispose()
    publisher_engine.dispose()
    log.info("worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
