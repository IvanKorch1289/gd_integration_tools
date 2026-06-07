"""Unit tests for cert SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from src.backend.infrastructure.database.models.cert import CertHistory, CertRecord


class TestCertRecord:
    """Tests for CertRecord model."""

    @pytest.fixture
    def engine(self):
        engine = create_engine("sqlite:///:memory:")
        CertRecord.metadata.create_all(engine)
        yield engine
        engine.dispose()

    @pytest.fixture
    def db_session(self, engine):
        session_local = sessionmaker(bind=engine)
        session = session_local()
        yield session
        session.close()

    @pytest.mark.unit
    def test_tablename(self) -> None:
        """CertRecord has correct tablename."""
        assert CertRecord.__tablename__ == "certs"

    @pytest.mark.unit
    def test_table_has_index_on_expires_at(self, engine) -> None:
        """Index idx_certs_expires exists on expires_at column."""
        inspector = inspect(engine)
        indexes = inspector.get_indexes("certs")
        index_names = {idx["name"] for idx in indexes}
        assert "idx_certs_expires" in index_names

    @pytest.mark.unit
    def test_create_with_valid_data(self, db_session: Session) -> None:
        """CertRecord can be created with valid data."""
        now = datetime.now(timezone.utc)
        cert = CertRecord(
            service_id="svc-1",
            pem="-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----",
            fingerprint="aa:bb:cc",
            expires_at=now,
            uploaded_at=now,
            description="test cert",
            version=1,
        )
        db_session.add(cert)
        db_session.commit()

        fetched = db_session.query(CertRecord).filter_by(service_id="svc-1").first()
        assert fetched is not None
        assert fetched.service_id == "svc-1"
        assert (
            fetched.pem
            == "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----"
        )
        assert fetched.fingerprint == "aa:bb:cc"
        assert fetched.expires_at is not None
        assert fetched.uploaded_at is not None
        assert fetched.description == "test cert"
        assert fetched.version == 1

    @pytest.mark.unit
    def test_nullable_description(self, db_session: Session) -> None:
        """CertRecord allows description to be NULL."""
        now = datetime.now(timezone.utc)
        cert = CertRecord(
            service_id="svc-no-desc",
            pem="pem",
            fingerprint="fp",
            expires_at=now,
            uploaded_at=now,
            description=None,
            version=1,
        )
        db_session.add(cert)
        db_session.commit()

        fetched = (
            db_session.query(CertRecord).filter_by(service_id="svc-no-desc").first()
        )
        assert fetched is not None
        assert fetched.description is None

    @pytest.mark.unit
    def test_default_version(self, db_session: Session) -> None:
        """CertRecord defaults version to 1 when not provided."""
        now = datetime.now(timezone.utc)
        cert = CertRecord(
            service_id="svc-default-version",
            pem="pem",
            fingerprint="fp",
            expires_at=now,
            uploaded_at=now,
        )
        db_session.add(cert)
        db_session.commit()

        fetched = (
            db_session.query(CertRecord)
            .filter_by(service_id="svc-default-version")
            .first()
        )
        assert fetched is not None
        assert fetched.version == 1

    @pytest.mark.unit
    def test_primary_key_is_service_id(self) -> None:
        """Primary key is service_id, not id."""
        pk_columns = [col.name for col in CertRecord.__table__.primary_key.columns]
        assert pk_columns == ["service_id"]


class TestCertHistory:
    """Tests for CertHistory model."""

    @pytest.fixture
    def engine(self):
        engine = create_engine("sqlite:///:memory:")
        CertHistory.metadata.create_all(engine)
        yield engine
        engine.dispose()

    @pytest.fixture
    def db_session(self, engine):
        session_local = sessionmaker(bind=engine)
        session = session_local()
        yield session
        session.close()

    @pytest.mark.unit
    def test_tablename(self) -> None:
        """CertHistory has correct tablename."""
        assert CertHistory.__tablename__ == "cert_history"

    @pytest.mark.unit
    def test_table_has_index_on_service_id(self, engine) -> None:
        """Index idx_cert_history_service exists on service_id column."""
        inspector = inspect(engine)
        indexes = inspector.get_indexes("cert_history")
        index_names = {idx["name"] for idx in indexes}
        assert "idx_cert_history_service" in index_names

    @pytest.mark.unit
    def test_create_with_valid_data(self, db_session: Session) -> None:
        """CertHistory can be created with valid data."""
        now = datetime.now(timezone.utc)
        record = CertHistory(
            service_id="svc-1",
            version=1,
            pem="pem-data",
            uploaded_at=now,
            uploaded_by="user@example.com",
        )
        db_session.add(record)
        db_session.commit()

        fetched = db_session.query(CertHistory).order_by(CertHistory.id.desc()).first()
        assert fetched is not None
        assert fetched.service_id == "svc-1"
        assert fetched.version == 1
        assert fetched.pem == "pem-data"
        assert fetched.uploaded_at is not None
        assert fetched.uploaded_by == "user@example.com"
        assert fetched.id is not None

    @pytest.mark.unit
    def test_nullable_uploaded_by(self, db_session: Session) -> None:
        """CertHistory allows uploaded_by to be NULL."""
        now = datetime.now(timezone.utc)
        record = CertHistory(
            service_id="svc-null-user",
            version=2,
            pem="pem-data",
            uploaded_at=now,
            uploaded_by=None,
        )
        db_session.add(record)
        db_session.commit()

        fetched = (
            db_session.query(CertHistory).filter_by(service_id="svc-null-user").first()
        )
        assert fetched is not None
        assert fetched.uploaded_by is None

    @pytest.mark.unit
    def test_autoincrement_id(self, db_session: Session) -> None:
        """CertHistory id auto-increments."""
        now = datetime.now(timezone.utc)
        for i in range(3):
            record = CertHistory(
                service_id=f"svc-{i}", version=i, pem="pem", uploaded_at=now
            )
            db_session.add(record)
        db_session.commit()

        records = db_session.query(CertHistory).order_by(CertHistory.id).all()
        assert len(records) == 3
        assert records[0].id == 1
        assert records[1].id == 2
        assert records[2].id == 3

    @pytest.mark.unit
    def test_primary_key_is_id(self) -> None:
        """Primary key is id with autoincrement."""
        pk_columns = [col.name for col in CertHistory.__table__.primary_key.columns]
        assert pk_columns == ["id"]
        assert CertHistory.__table__.c.id.autoincrement is True
