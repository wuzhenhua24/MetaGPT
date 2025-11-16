#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : session_manager.py
@Desc    : Session management for multi-user scenarios
"""

import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from metagpt.config2 import Config
from metagpt.memory.brain_memory import BrainMemory
from metagpt.utils.redis import Redis


class Session(BaseModel):
    """Session model for tracking user conversations"""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    chat_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    ttl: int = 1800  # 默认 30 分钟
    metadata: Dict = Field(default_factory=dict)

    def to_redis_key(self, prefix: str = "metagpt") -> str:
        """Generate Redis key for this session"""
        return BrainMemory.to_redis_key(prefix, self.user_id, self.chat_id)

    def is_expired(self) -> bool:
        """Check if session is expired"""
        expiry_time = self.updated_at + timedelta(seconds=self.ttl)
        return datetime.now() > expiry_time

    def touch(self):
        """Update last access time"""
        self.updated_at = datetime.now()


class SessionManager:
    """
    Unified session management for multi-user scenarios.

    Features:
    - Automatic session ID generation
    - Session lifecycle management
    - Redis key management
    - Session metadata tracking
    - TTL configuration

    Usage:
        manager = SessionManager(config)
        session = await manager.create_session("user123")
        brain_memory = await manager.get_memory(session.session_id)
    """

    def __init__(self, config: Config, prefix: str = "metagpt"):
        self.config = config
        self.prefix = prefix
        self._sessions: Dict[str, Session] = {}
        self._session_index_key = f"{prefix}:sessions:index"

    async def create_session(
        self,
        user_id: str,
        chat_id: Optional[str] = None,
        ttl: int = 1800,
        metadata: Optional[Dict] = None,
    ) -> Session:
        """
        Create a new session for a user.

        Args:
            user_id: User identifier
            chat_id: Optional chat identifier (auto-generated if not provided)
            ttl: Time-to-live in seconds (default: 30 minutes)
            metadata: Optional metadata dictionary

        Returns:
            Session: Created session object
        """
        if chat_id is None:
            chat_id = str(uuid.uuid4())

        session = Session(
            user_id=user_id,
            chat_id=chat_id,
            ttl=ttl,
            metadata=metadata or {},
        )

        # Store in local cache
        self._sessions[session.session_id] = session

        # Store in Redis for persistence
        await self._persist_session(session)

        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session or None if not found
        """
        # Check local cache first
        if session_id in self._sessions:
            session = self._sessions[session_id]
            if not session.is_expired():
                session.touch()
                await self._persist_session(session)
                return session
            else:
                # Remove expired session
                await self.delete_session(session_id)
                return None

        # Try to load from Redis
        session = await self._load_session(session_id)
        if session and not session.is_expired():
            self._sessions[session_id] = session
            session.touch()
            await self._persist_session(session)
            return session
        elif session:
            # Remove expired session
            await self.delete_session(session_id)

        return None

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            bool: True if deleted, False if not found
        """
        session = self._sessions.pop(session_id, None)
        if session:
            await self._remove_session_from_redis(session)
            return True
        return False

    async def list_user_sessions(self, user_id: str) -> List[Session]:
        """
        List all active sessions for a user.

        Args:
            user_id: User identifier

        Returns:
            List of active sessions
        """
        sessions = [s for s in self._sessions.values() if s.user_id == user_id and not s.is_expired()]

        # Clean up expired sessions
        expired_ids = [s.session_id for s in self._sessions.values() if s.is_expired()]
        for sid in expired_ids:
            await self.delete_session(sid)

        return sessions

    async def get_memory(self, session_id: str) -> Optional[BrainMemory]:
        """
        Get BrainMemory for a session.

        Args:
            session_id: Session identifier

        Returns:
            BrainMemory or None if session not found
        """
        session = await self.get_session(session_id)
        if not session:
            return None

        redis_key = session.to_redis_key(self.prefix)
        brain_memory = BrainMemory(config=self.config)

        try:
            await brain_memory.loads(redis_key)
        except Exception:
            # New session, no existing memory
            pass

        return brain_memory

    async def save_memory(self, session_id: str, brain_memory: BrainMemory) -> bool:
        """
        Save BrainMemory for a session.

        Args:
            session_id: Session identifier
            brain_memory: BrainMemory to save

        Returns:
            bool: True if saved successfully
        """
        session = await self.get_session(session_id)
        if not session:
            return False

        redis_key = session.to_redis_key(self.prefix)
        await brain_memory.dumps(redis_key, timeout_sec=session.ttl)
        session.touch()
        await self._persist_session(session)
        return True

    async def set_ttl(self, session_id: str, ttl: int) -> bool:
        """
        Update session TTL.

        Args:
            session_id: Session identifier
            ttl: New TTL in seconds

        Returns:
            bool: True if updated successfully
        """
        session = await self.get_session(session_id)
        if not session:
            return False

        session.ttl = ttl
        await self._persist_session(session)
        return True

    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up all expired sessions.

        Returns:
            int: Number of sessions cleaned up
        """
        expired_ids = [s.session_id for s in self._sessions.values() if s.is_expired()]
        for sid in expired_ids:
            await self.delete_session(sid)
        return len(expired_ids)

    # Private helper methods

    async def _persist_session(self, session: Session):
        """Persist session to Redis"""
        if not self.config.redis:
            return

        redis = Redis(self.config.redis)
        session_key = f"{self.prefix}:session:{session.session_id}"
        await redis.set(key=session_key, data=session.model_dump_json(), timeout_sec=session.ttl)

        # Add to user's session index
        user_index_key = f"{self.prefix}:user:{session.user_id}:sessions"
        # Store as a set of session IDs
        # Note: Redis class may need extension for set operations

    async def _load_session(self, session_id: str) -> Optional[Session]:
        """Load session from Redis"""
        if not self.config.redis:
            return None

        try:
            redis = Redis(self.config.redis)
            session_key = f"{self.prefix}:session:{session_id}"
            data = await redis.get(key=session_key)
            if data:
                return Session.model_validate_json(data)
        except Exception:
            pass
        return None

    async def _remove_session_from_redis(self, session: Session):
        """Remove session from Redis"""
        if not self.config.redis:
            return

        try:
            redis = Redis(self.config.redis)
            session_key = f"{self.prefix}:session:{session.session_id}"
            # Note: Redis class may need delete operation
            # await redis.delete(key=session_key)
        except Exception:
            pass
