from unittest.mock import MagicMock, Mock

import pytest

from app.db import session as db_session


def test_build_engine_enables_connection_pre_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = object()
    create_engine = Mock(return_value=engine)
    monkeypatch.setattr(db_session, "create_engine", create_engine)

    assert db_session.build_engine("postgresql+psycopg://user:pass@localhost:5432/db") is engine

    create_engine.assert_called_once_with(
        "postgresql+psycopg://user:pass@localhost:5432/db",
        pool_pre_ping=True,
    )


def test_build_session_factory_disables_implicit_session_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = object()
    factory = object()
    sessionmaker = Mock(return_value=factory)
    monkeypatch.setattr(db_session, "sessionmaker", sessionmaker)

    assert db_session.build_session_factory(engine) is factory

    sessionmaker.assert_called_once_with(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def test_get_db_session_yields_context_managed_session(monkeypatch: pytest.MonkeyPatch) -> None:
    session = object()
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    session_local = Mock(return_value=session_context)
    monkeypatch.setattr(db_session, "SessionLocal", session_local)

    generator = db_session.get_db_session()

    assert next(generator) is session
    with pytest.raises(StopIteration):
        next(generator)

    session_local.assert_called_once_with()
    session_context.__enter__.assert_called_once_with()
    session_context.__exit__.assert_called_once()
