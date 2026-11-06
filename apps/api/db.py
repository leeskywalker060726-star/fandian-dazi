from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
if os.getenv('FANDIAN_DESKTOP')!='1':
    load_dotenv(ROOT / '.env')
DATA_DIR=Path(os.getenv('FANDIAN_DATA_DIR',str(ROOT/'.runtime')))
DATA_DIR.mkdir(parents=True,exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite:///{(DATA_DIR / "fandian.db").as_posix()}')
if os.getenv('USE_MYSQL', 'false').lower() == 'true':
    DATABASE_URL = URL.create('mysql+pymysql', username=os.getenv('MYSQL_USER', 'root'), password=os.getenv('MYSQL_PASSWORD', ''), host=os.getenv('MYSQL_HOST', '127.0.0.1'), port=int(os.getenv('MYSQL_PORT', '3306')), database=os.getenv('MYSQL_DATABASE', 'fandian'), query={'charset': 'utf8mb4'})
engine = create_engine(DATABASE_URL, pool_pre_ping=True, **({'connect_args': {'check_same_thread': False}} if str(DATABASE_URL).startswith('sqlite') else {}))
Session = sessionmaker(engine, expire_on_commit=False)


def uid() -> str:
    return uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(Text, default='')
    guest: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Memory(Base):
    __tablename__ = 'memory_facts'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[object] = mapped_column(JSON)
    scope: Mapped[str] = mapped_column(String(20), default='persistent')
    source: Mapped[str] = mapped_column(String(40), default='设置')
    quote: Mapped[str] = mapped_column(Text, default='')
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SkillSnapshot(Base):
    __tablename__ = 'skill_snapshots'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    bundle: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))


class NarrativeMemory(Base):
    __tablename__ = 'narrative_memories'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(40), default='本人填写')
    scope: Mapped[str] = mapped_column(String(20), default='persistent')
    status: Mapped[str] = mapped_column(String(20), default='active')
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Food(Base):
    __tablename__ = 'foods'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class Conversation(Base):
    __tablename__ = 'conversations'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=0)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Turn(Base):
    __tablename__ = 'chat_turns'
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


class Meal(Base):
    __tablename__ = 'meal_events'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    conversation_id: Mapped[str] = mapped_column(String(32), unique=True)
    food: Mapped[dict] = mapped_column(JSON)
    eaten: Mapped[bool] = mapped_column(Boolean, default=False)
    actual_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
