#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : test_quota_manager.py
"""

import pytest
from datetime import datetime, timedelta

from metagpt.config2 import Config
from metagpt.configs.llm_config import LLMConfig
from metagpt.management.quota_manager import (
    QuotaConfig,
    QuotaExceeded,
    QuotaManager,
    QuotaPeriod,
    QuotaUsage,
)


@pytest.fixture
def config():
    """Create test configuration"""
    return Config(llm=LLMConfig(model="gpt-4"))


@pytest.fixture
def quota_manager(config):
    """Create quota manager instance"""
    default_quota = QuotaConfig(
        max_tokens_per_period=10000,
        max_requests_per_period=100,
        max_concurrent_sessions=5,
        max_context_tokens=4000,
        period=QuotaPeriod.DAILY,
    )
    return QuotaManager(config, default_quota=default_quota)


def test_set_user_quota(quota_manager):
    """Test setting custom user quota"""
    custom_quota = QuotaConfig(
        max_tokens_per_period=50000,
        max_requests_per_period=500,
        max_concurrent_sessions=20,
        period=QuotaPeriod.WEEKLY,
    )

    quota_manager.set_user_quota("vip_user", custom_quota)

    retrieved = quota_manager.get_user_quota("vip_user")
    assert retrieved.max_tokens_per_period == 50000
    assert retrieved.max_requests_per_period == 500
    assert retrieved.period == QuotaPeriod.WEEKLY


def test_get_user_quota_default(quota_manager):
    """Test getting default quota for user without custom quota"""
    quota = quota_manager.get_user_quota("new_user")

    assert quota.max_tokens_per_period == 10000
    assert quota.max_requests_per_period == 100


@pytest.mark.asyncio
async def test_check_quota_success(quota_manager):
    """Test successful quota check"""
    result = await quota_manager.check_quota("test_user", tokens=100, requests=1)
    assert result is True


@pytest.mark.asyncio
async def test_check_quota_token_exceeded(quota_manager):
    """Test quota check failure due to token limit"""
    # Consume most of the quota
    await quota_manager.consume_quota("test_user", tokens=9500)

    # Try to use more than remaining
    result = await quota_manager.check_quota("test_user", tokens=1000)
    assert result is False


@pytest.mark.asyncio
async def test_check_quota_request_exceeded(quota_manager):
    """Test quota check failure due to request limit"""
    # Consume most of the quota
    await quota_manager.consume_quota("test_user", tokens=0, requests=99)

    # Try to exceed request limit
    result = await quota_manager.check_quota("test_user", tokens=0, requests=2)
    assert result is False


@pytest.mark.asyncio
async def test_check_quota_session_exceeded(quota_manager):
    """Test quota check failure due to session limit"""
    # Set active sessions to max
    usage = await quota_manager._get_usage("test_user")
    usage.active_sessions = 5
    await quota_manager._save_usage("test_user", usage)

    # Try to add another session
    result = await quota_manager.check_quota("test_user", sessions=1)
    assert result is False


@pytest.mark.asyncio
async def test_check_quota_context_exceeded(quota_manager):
    """Test quota check failure due to context token limit"""
    result = await quota_manager.check_quota("test_user", tokens=5000)
    assert result is False  # Exceeds max_context_tokens of 4000


@pytest.mark.asyncio
async def test_consume_quota_success(quota_manager):
    """Test successful quota consumption"""
    await quota_manager.consume_quota("test_user", tokens=1000, requests=1)

    remaining = await quota_manager.get_remaining_quota("test_user")
    assert remaining["tokens"]["used"] == 1000
    assert remaining["requests"]["used"] == 1


@pytest.mark.asyncio
async def test_consume_quota_failure(quota_manager):
    """Test quota consumption failure"""
    # Try to consume more than allowed
    with pytest.raises(QuotaExceeded):
        await quota_manager.consume_quota("test_user", tokens=15000, requests=1)


@pytest.mark.asyncio
async def test_check_and_consume(quota_manager):
    """Test combined check and consume"""
    await quota_manager.check_and_consume("test_user", tokens=500, requests=1)

    remaining = await quota_manager.get_remaining_quota("test_user")
    assert remaining["tokens"]["used"] == 500
    assert remaining["requests"]["used"] == 1


@pytest.mark.asyncio
async def test_get_remaining_quota(quota_manager):
    """Test getting remaining quota"""
    # Consume some quota
    await quota_manager.consume_quota("test_user", tokens=2000, requests=10)

    remaining = await quota_manager.get_remaining_quota("test_user")

    assert remaining["user_id"] == "test_user"
    assert remaining["tokens"]["used"] == 2000
    assert remaining["tokens"]["remaining"] == 8000
    assert remaining["requests"]["used"] == 10
    assert remaining["requests"]["remaining"] == 90


@pytest.mark.asyncio
async def test_reset_quota(quota_manager):
    """Test manual quota reset"""
    # Consume some quota
    await quota_manager.consume_quota("test_user", tokens=5000, requests=50)

    # Reset
    await quota_manager.reset_quota("test_user")

    # Verify reset
    remaining = await quota_manager.get_remaining_quota("test_user")
    assert remaining["tokens"]["used"] == 0
    assert remaining["requests"]["used"] == 0


@pytest.mark.asyncio
async def test_increment_decrement_sessions(quota_manager):
    """Test session count management"""
    # Increment
    await quota_manager.increment_sessions("test_user", delta=3)

    remaining = await quota_manager.get_remaining_quota("test_user")
    assert remaining["sessions"]["active"] == 3

    # Decrement
    await quota_manager.decrement_sessions("test_user", delta=2)

    remaining = await quota_manager.get_remaining_quota("test_user")
    assert remaining["sessions"]["active"] == 1


@pytest.mark.asyncio
async def test_auto_reset_quota(quota_manager):
    """Test automatic quota reset after period"""
    # Create usage with old period start
    usage = QuotaUsage(user_id="test_user")
    usage.period_start = datetime.now() - timedelta(days=2)
    usage.tokens_used = 5000
    usage.requests_made = 50
    quota_manager._user_usage["test_user"] = usage

    # Check quota - should trigger auto-reset
    await quota_manager.check_quota("test_user", tokens=100)

    # Verify reset
    remaining = await quota_manager.get_remaining_quota("test_user")
    assert remaining["tokens"]["used"] == 0
    assert remaining["requests"]["used"] == 0


def test_quota_period_values():
    """Test quota period enum values"""
    assert QuotaPeriod.MINUTE.value == "minute"
    assert QuotaPeriod.HOURLY.value == "hourly"
    assert QuotaPeriod.DAILY.value == "daily"
    assert QuotaPeriod.WEEKLY.value == "weekly"
    assert QuotaPeriod.MONTHLY.value == "monthly"


def test_calculate_period_end(quota_manager):
    """Test period end calculation"""
    start = datetime(2025, 1, 1, 12, 0, 0)

    # Minute
    end = quota_manager._calculate_period_end(start, QuotaPeriod.MINUTE)
    assert end == start + timedelta(minutes=1)

    # Hourly
    end = quota_manager._calculate_period_end(start, QuotaPeriod.HOURLY)
    assert end == start + timedelta(hours=1)

    # Daily
    end = quota_manager._calculate_period_end(start, QuotaPeriod.DAILY)
    assert end == start + timedelta(days=1)

    # Weekly
    end = quota_manager._calculate_period_end(start, QuotaPeriod.WEEKLY)
    assert end == start + timedelta(weeks=1)

    # Monthly
    end = quota_manager._calculate_period_end(start, QuotaPeriod.MONTHLY)
    assert end == start + timedelta(days=30)


def test_get_period_ttl(quota_manager):
    """Test TTL calculation for different periods"""
    assert quota_manager._get_period_ttl(QuotaPeriod.MINUTE) == 120
    assert quota_manager._get_period_ttl(QuotaPeriod.HOURLY) == 3900
    assert quota_manager._get_period_ttl(QuotaPeriod.DAILY) == 90000
    assert quota_manager._get_period_ttl(QuotaPeriod.WEEKLY) == 691200
    assert quota_manager._get_period_ttl(QuotaPeriod.MONTHLY) == 2678400
