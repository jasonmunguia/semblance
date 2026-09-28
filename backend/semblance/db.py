import time
import uuid
from sqlalchemy import JSON, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class BrowserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    touched: Mapped[float] = mapped_column(Float, default=time.time)


class Monitor(Base):
    __tablename__ = "monitors"
    address: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    last_checked: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cursor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cursor_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    history_partial: Mapped[bool] = mapped_column(default=False)


class Watch(Base):
    __tablename__ = "watches"
    __table_args__ = (UniqueConstraint("session_id", "address"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    address: Mapped[str] = mapped_column(ForeignKey("monitors.address", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String)


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("session_id", "address"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    address: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)


class Transfer(Base):
    __tablename__ = "transfers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    address: Mapped[str] = mapped_column(ForeignKey("monitors.address", ondelete="CASCADE"), index=True)
    block: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    address: Mapped[str] = mapped_column(ForeignKey("monitors.address", ondelete="CASCADE"), index=True)
    block: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)


class Acknowledgement(Base):
    __tablename__ = "acknowledgements"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True)


def database(url: str):
    options = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, **options)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_config(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
