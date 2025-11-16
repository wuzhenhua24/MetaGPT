#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : test_metrics_collector.py
"""

import pytest
import time

from metagpt.config2 import Config
from metagpt.configs.llm_config import LLMConfig
from metagpt.management.metrics_collector import (
    LatencyTracker,
    MetricsCollector,
)


@pytest.fixture
def config():
    """Create test configuration"""
    return Config(llm=LLMConfig(model="gpt-4"))


@pytest.fixture
def collector(config):
    """Create metrics collector instance"""
    return MetricsCollector(config, snapshot_interval=1)  # 1 second for testing


def test_record_compression(collector):
    """Test recording compression metrics"""
    collector.record_compression(original_tokens=1000, compressed_tokens=600)

    summary = collector.get_summary()
    assert summary["compression"]["total_compressions"] == 1
    assert summary["compression"]["tokens_saved"] == 400


def test_compression_ratio(collector):
    """Test compression ratio calculation"""
    collector.record_compression(1000, 500)
    collector.record_compression(2000, 1000)

    summary = collector.get_summary()
    # Average ratio should be 50%
    assert "50.00%" in summary["compression"]["average_ratio"]


def test_record_cache_hit(collector):
    """Test recording cache hits and misses"""
    collector.record_cache_hit(hit=True)
    collector.record_cache_hit(hit=True)
    collector.record_cache_hit(hit=False)

    summary = collector.get_summary()
    assert summary["cache"]["hits"] == 2
    assert summary["cache"]["misses"] == 1
    assert "66.67%" in summary["cache"]["hit_rate"]  # 2/3


def test_record_token_usage(collector):
    """Test recording token usage"""
    collector.record_token_usage("user1", tokens=100, session_id="sess1")
    collector.record_token_usage("user1", tokens=200, session_id="sess2")
    collector.record_token_usage("user2", tokens=150, session_id="sess3")

    summary = collector.get_summary()
    assert summary["tokens"]["total"] == 450
    assert summary["tokens"]["requests"] == 3

    user_metrics = collector.get_user_metrics("user1")
    assert user_metrics["tokens_used"] == 300


def test_record_latency(collector):
    """Test recording latency metrics"""
    collector.record_latency(100.0)
    collector.record_latency(200.0)
    collector.record_latency(150.0)

    summary = collector.get_summary()
    assert "150.00" in summary["latency"]["average_ms"]
    assert "100.00" in summary["latency"]["min_ms"]
    assert "200.00" in summary["latency"]["max_ms"]


def test_latency_tracker(collector):
    """Test automatic latency tracking with context manager"""
    with LatencyTracker(collector):
        time.sleep(0.1)  # Simulate work

    summary = collector.get_summary()
    assert summary["latency"]["total_requests"] == 1
    # Should be around 100ms
    avg_latency = float(summary["latency"]["average_ms"])
    assert 90 < avg_latency < 200  # Allow some margin


def test_record_session_events(collector):
    """Test recording session creation and deletion"""
    collector.record_session_created()
    collector.record_session_created()
    collector.record_session_deleted()
    collector.record_session_deleted(expired=True)

    summary = collector.get_summary()
    assert summary["sessions"]["created"] == 2
    assert summary["sessions"]["deleted"] == 2
    assert summary["sessions"]["active"] == 0  # 2 created - 2 deleted
    assert summary["sessions"]["expired"] == 1


def test_record_summary(collector):
    """Test recording summarization metrics"""
    collector.record_summary(original_messages=50, summary_tokens=200)
    collector.record_summary(original_messages=30, summary_tokens=150)

    summary = collector.get_summary()
    assert summary["summaries"]["total"] == 2
    assert "40.00" in summary["summaries"]["average_messages"]  # (50+30)/2


def test_get_user_metrics(collector):
    """Test getting user-specific metrics"""
    collector.record_token_usage("user1", 1000)
    collector.record_token_usage("user2", 500)
    collector.record_token_usage("user1", 500)

    metrics = collector.get_user_metrics("user1")
    assert metrics["user_id"] == "user1"
    assert metrics["tokens_used"] == 1500
    assert metrics["percentage_of_total"] == 75.0  # 1500/2000


def test_snapshots(collector):
    """Test metric snapshots"""
    collector.record_compression(1000, 500)

    # Wait for snapshot interval
    time.sleep(1.1)

    collector.record_compression(2000, 1000)

    snapshots = collector.get_snapshots(count=10)
    assert len(snapshots) >= 1


def test_reset(collector):
    """Test resetting metrics"""
    collector.record_token_usage("user1", 1000)
    collector.record_compression(1000, 500)

    collector.reset()

    summary = collector.get_summary()
    assert summary["tokens"]["total"] == 0
    assert summary["compression"]["total_compressions"] == 0


def test_top_users(collector):
    """Test getting top users by token usage"""
    collector.record_token_usage("user1", 1000)
    collector.record_token_usage("user2", 3000)
    collector.record_token_usage("user3", 2000)
    collector.record_token_usage("user4", 500)

    summary = collector.get_summary()
    top_users = summary["tokens"]["top_users"]

    # Should be sorted by tokens descending
    assert len(top_users) <= 5
    assert top_users[0]["user_id"] == "user2"
    assert top_users[0]["tokens"] == 3000
    assert top_users[1]["user_id"] == "user3"
    assert top_users[1]["tokens"] == 2000
