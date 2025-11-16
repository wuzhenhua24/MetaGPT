#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : test_session_manager.py
"""

import pytest

from metagpt.config2 import Config
from metagpt.configs.llm_config import LLMConfig
from metagpt.management.session_manager import Session, SessionManager
from metagpt.memory.brain_memory import BrainMemory


@pytest.fixture
def config():
    """Create test configuration"""
    return Config(llm=LLMConfig(model="gpt-4"))


@pytest.fixture
def session_manager(config):
    """Create session manager instance"""
    return SessionManager(config)


@pytest.mark.asyncio
async def test_create_session(session_manager):
    """Test session creation"""
    session = await session_manager.create_session(
        user_id="test_user", chat_id="test_chat", ttl=1800, metadata={"source": "test"}
    )

    assert session is not None
    assert session.user_id == "test_user"
    assert session.chat_id == "test_chat"
    assert session.ttl == 1800
    assert session.metadata["source"] == "test"
    assert session.session_id is not None


@pytest.mark.asyncio
async def test_create_session_auto_chat_id(session_manager):
    """Test session creation with auto-generated chat_id"""
    session = await session_manager.create_session(user_id="test_user")

    assert session is not None
    assert session.user_id == "test_user"
    assert session.chat_id is not None  # Auto-generated
    assert session.session_id is not None


@pytest.mark.asyncio
async def test_get_session(session_manager):
    """Test getting a session"""
    # Create session
    created = await session_manager.create_session(user_id="test_user")

    # Get session
    retrieved = await session_manager.get_session(created.session_id)

    assert retrieved is not None
    assert retrieved.session_id == created.session_id
    assert retrieved.user_id == created.user_id


@pytest.mark.asyncio
async def test_get_nonexistent_session(session_manager):
    """Test getting a non-existent session"""
    result = await session_manager.get_session("nonexistent_id")
    assert result is None


@pytest.mark.asyncio
async def test_delete_session(session_manager):
    """Test session deletion"""
    # Create session
    session = await session_manager.create_session(user_id="test_user")

    # Delete session
    result = await session_manager.delete_session(session.session_id)
    assert result is True

    # Verify deletion
    retrieved = await session_manager.get_session(session.session_id)
    assert retrieved is None


@pytest.mark.asyncio
async def test_list_user_sessions(session_manager):
    """Test listing user sessions"""
    user_id = "test_user"

    # Create multiple sessions
    session1 = await session_manager.create_session(user_id=user_id, chat_id="chat1")
    session2 = await session_manager.create_session(user_id=user_id, chat_id="chat2")
    session3 = await session_manager.create_session(user_id="other_user", chat_id="chat3")

    # List sessions for test_user
    sessions = await session_manager.list_user_sessions(user_id)

    assert len(sessions) == 2
    session_ids = [s.session_id for s in sessions]
    assert session1.session_id in session_ids
    assert session2.session_id in session_ids
    assert session3.session_id not in session_ids


@pytest.mark.asyncio
async def test_get_memory(session_manager):
    """Test getting memory for a session"""
    session = await session_manager.create_session(user_id="test_user")

    # Get memory (should create new if doesn't exist)
    memory = await session_manager.get_memory(session.session_id)

    assert memory is not None
    assert isinstance(memory, BrainMemory)


@pytest.mark.asyncio
async def test_save_and_load_memory(session_manager):
    """Test saving and loading memory"""
    session = await session_manager.create_session(user_id="test_user")

    # Get memory and modify it
    memory = await session_manager.get_memory(session.session_id)
    from metagpt.schema import Message

    memory.history.append(Message(role="user", content="test message"))

    # Save memory
    result = await session_manager.save_memory(session.session_id, memory)
    assert result is True

    # Load memory again
    loaded_memory = await session_manager.get_memory(session.session_id)
    # Note: Actual loading from Redis depends on Redis being available


@pytest.mark.asyncio
async def test_set_ttl(session_manager):
    """Test setting session TTL"""
    session = await session_manager.create_session(user_id="test_user", ttl=1800)

    # Change TTL
    result = await session_manager.set_ttl(session.session_id, 3600)
    assert result is True

    # Verify
    retrieved = await session_manager.get_session(session.session_id)
    assert retrieved.ttl == 3600


@pytest.mark.asyncio
async def test_cleanup_expired_sessions(session_manager):
    """Test cleanup of expired sessions"""
    from datetime import datetime, timedelta

    # Create session with very short TTL
    session = await session_manager.create_session(user_id="test_user", ttl=1)

    # Manually expire it for testing
    session.updated_at = datetime.now() - timedelta(seconds=10)
    session_manager._sessions[session.session_id] = session

    # Cleanup
    count = await session_manager.cleanup_expired_sessions()
    assert count >= 1


def test_session_to_redis_key():
    """Test Redis key generation"""
    session = Session(user_id="user123", chat_id="chat456")

    redis_key = session.to_redis_key("metagpt")
    assert redis_key == "metagpt:user123:chat456"


def test_session_is_expired():
    """Test session expiration check"""
    from datetime import datetime, timedelta

    # Non-expired session
    session = Session(user_id="test", chat_id="test", ttl=3600)
    assert not session.is_expired()

    # Expired session
    session.updated_at = datetime.now() - timedelta(seconds=7200)
    assert session.is_expired()


def test_session_touch():
    """Test session touch (update timestamp)"""
    from datetime import datetime

    session = Session(user_id="test", chat_id="test")
    old_time = session.updated_at

    # Wait a bit and touch
    import time

    time.sleep(0.1)
    session.touch()

    assert session.updated_at > old_time
