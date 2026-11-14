from collections.abc import Callable, Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str, *, pool_size: int = 2, max_overflow: int = 1, pool_timeout: float = 5.0) -> Engine:
    return create_engine(
        url, pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout,
        pool_pre_ping=True,
        pool_recycle=1800, 
    )

def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def session_dependency(factory: Callable[[], sessionmaker[Session]]):
    """FastAPI dependency: one transaction per request. Commit on success, roll back on any error."""
    def dep() -> Iterator[Session]:
        with factory().begin() as session:   # begin() commits at exit, rolls back on exception
            yield session
    return dep