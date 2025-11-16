#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : quota_manager.py
@Desc    : Quota management for rate limiting and resource control
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field

from metagpt.config2 import Config
from metagpt.logs import logger
from metagpt.utils.redis import Redis


class QuotaPeriod(str, Enum):
    """Quota reset period"""

    MINUTE = "minute"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class QuotaConfig(BaseModel):
    """Quota configuration for a user or tenant"""

    max_tokens_per_period: int = 100000  # 每周期最大 token 数
    max_requests_per_period: int = 1000  # 每周期最大请求数
    max_concurrent_sessions: int = 10  # 最大并发会话数
    max_history_length: int = 100  # 最大历史消息数
    max_context_tokens: int = 128000  # 单次请求最大上下文 tokens
    period: QuotaPeriod = QuotaPeriod.DAILY  # 配额重置周期


class QuotaUsage(BaseModel):
    """Quota usage tracking"""

    user_id: str
    period_start: datetime = Field(default_factory=datetime.now)
    tokens_used: int = 0
    requests_made: int = 0
    active_sessions: int = 0
    last_reset: datetime = Field(default_factory=datetime.now)


class QuotaExceeded(Exception):
    """Exception raised when quota is exceeded"""

    pass


class QuotaManager:
    """
    Resource quota management for multi-user scenarios.

    Features:
    - Token usage tracking and limiting
    - Request rate limiting
    - Concurrent session limiting
    - Flexible quota periods (minute/hourly/daily/weekly/monthly)
    - Per-user quota configuration
    - Automatic quota reset

    Usage:
        quota_manager = QuotaManager(config)
        quota_manager.set_user_quota("user123", QuotaConfig(max_tokens_per_period=50000))
        await quota_manager.check_and_consume("user123", tokens=1000)
    """

    def __init__(self, config: Config, default_quota: Optional[QuotaConfig] = None):
        self.config = config
        self.default_quota = default_quota or QuotaConfig()
        self._user_quotas: Dict[str, QuotaConfig] = {}
        self._user_usage: Dict[str, QuotaUsage] = {}
        self._prefix = "metagpt:quota"

    def set_user_quota(self, user_id: str, quota_config: QuotaConfig):
        """
        Set custom quota for a specific user.

        Args:
            user_id: User identifier
            quota_config: Quota configuration
        """
        self._user_quotas[user_id] = quota_config
        logger.info(f"Set quota for user {user_id}: {quota_config.model_dump()}")

    def get_user_quota(self, user_id: str) -> QuotaConfig:
        """
        Get quota configuration for a user.

        Args:
            user_id: User identifier

        Returns:
            QuotaConfig: User's quota configuration (default if not set)
        """
        return self._user_quotas.get(user_id, self.default_quota)

    async def check_quota(
        self, user_id: str, tokens: int = 0, sessions: int = 0, requests: int = 1
    ) -> bool:
        """
        Check if user has enough quota.

        Args:
            user_id: User identifier
            tokens: Tokens to be consumed
            sessions: Number of active sessions
            requests: Number of requests (default: 1)

        Returns:
            bool: True if quota is available, False otherwise
        """
        quota = self.get_user_quota(user_id)
        usage = await self._get_usage(user_id)

        # Auto-reset if period has passed
        await self._check_and_reset_quota(user_id, usage, quota)

        # Check token quota
        if usage.tokens_used + tokens > quota.max_tokens_per_period:
            logger.warning(
                f"User {user_id} token quota exceeded: "
                f"{usage.tokens_used + tokens}/{quota.max_tokens_per_period}"
            )
            return False

        # Check request quota
        if usage.requests_made + requests > quota.max_requests_per_period:
            logger.warning(
                f"User {user_id} request quota exceeded: "
                f"{usage.requests_made + requests}/{quota.max_requests_per_period}"
            )
            return False

        # Check concurrent session quota
        if sessions > 0 and usage.active_sessions + sessions > quota.max_concurrent_sessions:
            logger.warning(
                f"User {user_id} session quota exceeded: "
                f"{usage.active_sessions + sessions}/{quota.max_concurrent_sessions}"
            )
            return False

        # Check single context token limit
        if tokens > quota.max_context_tokens:
            logger.warning(f"User {user_id} single request token limit exceeded: {tokens}/{quota.max_context_tokens}")
            return False

        return True

    async def consume_quota(self, user_id: str, tokens: int = 0, requests: int = 1, sessions: int = 0):
        """
        Consume user quota.

        Args:
            user_id: User identifier
            tokens: Tokens consumed
            requests: Requests made (default: 1)
            sessions: Change in active sessions (can be negative)

        Raises:
            QuotaExceeded: If quota check fails
        """
        if not await self.check_quota(user_id, tokens, sessions, requests):
            raise QuotaExceeded(f"Quota exceeded for user {user_id}")

        usage = await self._get_usage(user_id)
        usage.tokens_used += tokens
        usage.requests_made += requests
        usage.active_sessions = max(0, usage.active_sessions + sessions)

        await self._save_usage(user_id, usage)
        logger.debug(
            f"User {user_id} quota consumed: tokens={tokens}, requests={requests}, "
            f"total_tokens={usage.tokens_used}, total_requests={usage.requests_made}"
        )

    async def check_and_consume(self, user_id: str, tokens: int = 0, requests: int = 1, sessions: int = 0):
        """
        Check and consume quota in one operation.

        Args:
            user_id: User identifier
            tokens: Tokens to consume
            requests: Requests to count (default: 1)
            sessions: Session count change

        Raises:
            QuotaExceeded: If quota check fails
        """
        await self.consume_quota(user_id, tokens, requests, sessions)

    async def get_remaining_quota(self, user_id: str) -> Dict:
        """
        Get remaining quota for a user.

        Args:
            user_id: User identifier

        Returns:
            Dict with remaining quota information
        """
        quota = self.get_user_quota(user_id)
        usage = await self._get_usage(user_id)
        await self._check_and_reset_quota(user_id, usage, quota)

        return {
            "user_id": user_id,
            "period": quota.period.value,
            "period_start": usage.period_start.isoformat(),
            "tokens": {
                "used": usage.tokens_used,
                "limit": quota.max_tokens_per_period,
                "remaining": max(0, quota.max_tokens_per_period - usage.tokens_used),
                "percentage": (usage.tokens_used / quota.max_tokens_per_period * 100)
                if quota.max_tokens_per_period > 0
                else 0,
            },
            "requests": {
                "used": usage.requests_made,
                "limit": quota.max_requests_per_period,
                "remaining": max(0, quota.max_requests_per_period - usage.requests_made),
            },
            "sessions": {
                "active": usage.active_sessions,
                "limit": quota.max_concurrent_sessions,
                "available": max(0, quota.max_concurrent_sessions - usage.active_sessions),
            },
        }

    async def reset_quota(self, user_id: str):
        """
        Manually reset quota for a user.

        Args:
            user_id: User identifier
        """
        usage = QuotaUsage(user_id=user_id)
        await self._save_usage(user_id, usage)
        logger.info(f"Reset quota for user {user_id}")

    async def increment_sessions(self, user_id: str, delta: int = 1):
        """
        Increment active session count.

        Args:
            user_id: User identifier
            delta: Change in session count (positive or negative)
        """
        usage = await self._get_usage(user_id)
        usage.active_sessions = max(0, usage.active_sessions + delta)
        await self._save_usage(user_id, usage)

    async def decrement_sessions(self, user_id: str, delta: int = 1):
        """
        Decrement active session count.

        Args:
            user_id: User identifier
            delta: Number of sessions to remove
        """
        await self.increment_sessions(user_id, -delta)

    # Private helper methods

    async def _get_usage(self, user_id: str) -> QuotaUsage:
        """Get or create usage tracking for a user"""
        if user_id in self._user_usage:
            return self._user_usage[user_id]

        # Try to load from Redis
        if self.config.redis:
            try:
                redis = Redis(self.config.redis)
                usage_key = f"{self._prefix}:usage:{user_id}"
                data = await redis.get(key=usage_key)
                if data:
                    usage = QuotaUsage.model_validate_json(data)
                    self._user_usage[user_id] = usage
                    return usage
            except Exception as e:
                logger.debug(f"Failed to load usage from Redis: {e}")

        # Create new usage tracking
        usage = QuotaUsage(user_id=user_id)
        self._user_usage[user_id] = usage
        return usage

    async def _save_usage(self, user_id: str, usage: QuotaUsage):
        """Save usage tracking to cache and Redis"""
        self._user_usage[user_id] = usage

        if self.config.redis:
            try:
                redis = Redis(self.config.redis)
                usage_key = f"{self._prefix}:usage:{user_id}"
                # Calculate TTL based on quota period
                quota = self.get_user_quota(user_id)
                ttl = self._get_period_ttl(quota.period)
                await redis.set(key=usage_key, data=usage.model_dump_json(), timeout_sec=ttl)
            except Exception as e:
                logger.debug(f"Failed to save usage to Redis: {e}")

    async def _check_and_reset_quota(self, user_id: str, usage: QuotaUsage, quota: QuotaConfig):
        """Check if quota period has passed and reset if needed"""
        period_end = self._calculate_period_end(usage.period_start, quota.period)

        if datetime.now() > period_end:
            logger.info(f"Quota period ended for user {user_id}, resetting...")
            await self.reset_quota(user_id)

    def _calculate_period_end(self, start: datetime, period: QuotaPeriod) -> datetime:
        """Calculate when the quota period ends"""
        if period == QuotaPeriod.MINUTE:
            return start + timedelta(minutes=1)
        elif period == QuotaPeriod.HOURLY:
            return start + timedelta(hours=1)
        elif period == QuotaPeriod.DAILY:
            return start + timedelta(days=1)
        elif period == QuotaPeriod.WEEKLY:
            return start + timedelta(weeks=1)
        elif period == QuotaPeriod.MONTHLY:
            return start + timedelta(days=30)
        return start + timedelta(days=1)  # Default to daily

    def _get_period_ttl(self, period: QuotaPeriod) -> int:
        """Get TTL in seconds for a quota period"""
        if period == QuotaPeriod.MINUTE:
            return 120  # 2 minutes buffer
        elif period == QuotaPeriod.HOURLY:
            return 3600 + 300  # 1 hour + 5 min buffer
        elif period == QuotaPeriod.DAILY:
            return 86400 + 3600  # 1 day + 1 hour buffer
        elif period == QuotaPeriod.WEEKLY:
            return 604800 + 86400  # 1 week + 1 day buffer
        elif period == QuotaPeriod.MONTHLY:
            return 2592000 + 86400  # 30 days + 1 day buffer
        return 86400  # Default to 1 day
