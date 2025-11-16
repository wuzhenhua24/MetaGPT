#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : metrics_collector.py
@Desc    : Metrics collection for monitoring and observability
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from metagpt.config2 import Config
from metagpt.logs import logger
from metagpt.utils.redis import Redis


class CompressionMetrics(BaseModel):
    """Metrics for message compression"""

    total_compressions: int = 0
    total_original_tokens: int = 0
    total_compressed_tokens: int = 0

    @property
    def average_compression_ratio(self) -> float:
        """Calculate average compression ratio"""
        if self.total_original_tokens == 0:
            return 0.0
        return (self.total_original_tokens - self.total_compressed_tokens) / self.total_original_tokens


class CacheMetrics(BaseModel):
    """Metrics for cache operations"""

    hits: int = 0
    misses: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total


class TokenMetrics(BaseModel):
    """Metrics for token usage"""

    total_tokens: int = 0
    total_requests: int = 0
    per_user_tokens: Dict[str, int] = Field(default_factory=dict)
    per_session_tokens: Dict[str, int] = Field(default_factory=dict)

    @property
    def average_tokens_per_request(self) -> float:
        """Calculate average tokens per request"""
        if self.total_requests == 0:
            return 0.0
        return self.total_tokens / self.total_requests


class LatencyMetrics(BaseModel):
    """Metrics for latency tracking"""

    total_requests: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0

    @property
    def average_latency_ms(self) -> float:
        """Calculate average latency"""
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests

    def record(self, latency_ms: float):
        """Record a latency measurement"""
        self.total_requests += 1
        self.total_latency_ms += latency_ms
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)


class SessionMetrics(BaseModel):
    """Metrics for session management"""

    total_sessions_created: int = 0
    total_sessions_deleted: int = 0
    active_sessions: int = 0
    expired_sessions: int = 0


class SummaryMetrics(BaseModel):
    """Metrics for summarization operations"""

    total_summaries: int = 0
    total_original_messages: int = 0
    total_summary_tokens: int = 0

    @property
    def average_messages_per_summary(self) -> float:
        """Calculate average messages per summary"""
        if self.total_summaries == 0:
            return 0.0
        return self.total_original_messages / self.total_summaries


class MetricsSnapshot(BaseModel):
    """Snapshot of all metrics at a point in time"""

    timestamp: datetime = Field(default_factory=datetime.now)
    compression: CompressionMetrics = Field(default_factory=CompressionMetrics)
    cache: CacheMetrics = Field(default_factory=CacheMetrics)
    tokens: TokenMetrics = Field(default_factory=TokenMetrics)
    latency: LatencyMetrics = Field(default_factory=LatencyMetrics)
    sessions: SessionMetrics = Field(default_factory=SessionMetrics)
    summaries: SummaryMetrics = Field(default_factory=SummaryMetrics)


class MetricsCollector:
    """
    Comprehensive metrics collection for multi-user scenarios.

    Features:
    - Compression metrics (compression ratio, tokens saved)
    - Cache metrics (hit rate, miss rate)
    - Token usage metrics (per user, per session, total)
    - Latency metrics (average, min, max)
    - Session metrics (created, deleted, active)
    - Summarization metrics (summaries created, messages summarized)
    - Time-series metrics with snapshots
    - Redis persistence for distributed systems

    Usage:
        collector = MetricsCollector(config)
        collector.record_compression(original=1000, compressed=500)
        collector.record_token_usage("user123", 250)
        summary = collector.get_summary()
    """

    def __init__(self, config: Config, snapshot_interval: int = 300):
        """
        Initialize metrics collector.

        Args:
            config: MetaGPT configuration
            snapshot_interval: Interval in seconds between metric snapshots (default: 5 minutes)
        """
        self.config = config
        self.snapshot_interval = snapshot_interval
        self._metrics = MetricsSnapshot()
        self._snapshots: List[MetricsSnapshot] = []
        self._last_snapshot = datetime.now()
        self._prefix = "metagpt:metrics"

    def record_compression(self, original_tokens: int, compressed_tokens: int):
        """
        Record a compression event.

        Args:
            original_tokens: Original token count
            compressed_tokens: Compressed token count
        """
        self._metrics.compression.total_compressions += 1
        self._metrics.compression.total_original_tokens += original_tokens
        self._metrics.compression.total_compressed_tokens += compressed_tokens

        saved = original_tokens - compressed_tokens
        ratio = saved / original_tokens if original_tokens > 0 else 0
        logger.debug(
            f"Compression recorded: {original_tokens} -> {compressed_tokens} " f"(saved: {saved}, ratio: {ratio:.2%})"
        )
        self._check_snapshot()

    def record_cache_hit(self, hit: bool = True):
        """
        Record a cache hit or miss.

        Args:
            hit: True for cache hit, False for cache miss
        """
        if hit:
            self._metrics.cache.hits += 1
        else:
            self._metrics.cache.misses += 1
        self._check_snapshot()

    def record_token_usage(self, user_id: str, tokens: int, session_id: Optional[str] = None):
        """
        Record token usage.

        Args:
            user_id: User identifier
            tokens: Number of tokens used
            session_id: Optional session identifier
        """
        self._metrics.tokens.total_tokens += tokens
        self._metrics.tokens.total_requests += 1

        # Track per-user usage
        if user_id not in self._metrics.tokens.per_user_tokens:
            self._metrics.tokens.per_user_tokens[user_id] = 0
        self._metrics.tokens.per_user_tokens[user_id] += tokens

        # Track per-session usage
        if session_id:
            if session_id not in self._metrics.tokens.per_session_tokens:
                self._metrics.tokens.per_session_tokens[session_id] = 0
            self._metrics.tokens.per_session_tokens[session_id] += tokens

        logger.debug(f"Token usage recorded: user={user_id}, tokens={tokens}, session={session_id}")
        self._check_snapshot()

    def record_latency(self, latency_ms: float):
        """
        Record request latency.

        Args:
            latency_ms: Latency in milliseconds
        """
        self._metrics.latency.record(latency_ms)
        logger.debug(f"Latency recorded: {latency_ms:.2f}ms")
        self._check_snapshot()

    def record_session_created(self):
        """Record a session creation event"""
        self._metrics.sessions.total_sessions_created += 1
        self._metrics.sessions.active_sessions += 1
        self._check_snapshot()

    def record_session_deleted(self, expired: bool = False):
        """
        Record a session deletion event.

        Args:
            expired: True if session was deleted due to expiration
        """
        self._metrics.sessions.total_sessions_deleted += 1
        self._metrics.sessions.active_sessions = max(0, self._metrics.sessions.active_sessions - 1)
        if expired:
            self._metrics.sessions.expired_sessions += 1
        self._check_snapshot()

    def record_summary(self, original_messages: int, summary_tokens: int):
        """
        Record a summarization event.

        Args:
            original_messages: Number of messages summarized
            summary_tokens: Number of tokens in summary
        """
        self._metrics.summaries.total_summaries += 1
        self._metrics.summaries.total_original_messages += original_messages
        self._metrics.summaries.total_summary_tokens += summary_tokens
        logger.debug(f"Summary recorded: {original_messages} messages -> {summary_tokens} tokens")
        self._check_snapshot()

    def get_summary(self) -> Dict:
        """
        Get current metrics summary.

        Returns:
            Dict with all current metrics
        """
        return {
            "timestamp": self._metrics.timestamp.isoformat(),
            "compression": {
                "total_compressions": self._metrics.compression.total_compressions,
                "average_ratio": f"{self._metrics.compression.average_compression_ratio:.2%}",
                "tokens_saved": self._metrics.compression.total_original_tokens
                - self._metrics.compression.total_compressed_tokens,
            },
            "cache": {
                "hits": self._metrics.cache.hits,
                "misses": self._metrics.cache.misses,
                "hit_rate": f"{self._metrics.cache.hit_rate:.2%}",
            },
            "tokens": {
                "total": self._metrics.tokens.total_tokens,
                "requests": self._metrics.tokens.total_requests,
                "average_per_request": f"{self._metrics.tokens.average_tokens_per_request:.2f}",
                "top_users": self._get_top_users(5),
            },
            "latency": {
                "average_ms": f"{self._metrics.latency.average_latency_ms:.2f}",
                "min_ms": f"{self._metrics.latency.min_latency_ms:.2f}",
                "max_ms": f"{self._metrics.latency.max_latency_ms:.2f}",
                "total_requests": self._metrics.latency.total_requests,
            },
            "sessions": {
                "created": self._metrics.sessions.total_sessions_created,
                "deleted": self._metrics.sessions.total_sessions_deleted,
                "active": self._metrics.sessions.active_sessions,
                "expired": self._metrics.sessions.expired_sessions,
            },
            "summaries": {
                "total": self._metrics.summaries.total_summaries,
                "average_messages": f"{self._metrics.summaries.average_messages_per_summary:.2f}",
                "total_summary_tokens": self._metrics.summaries.total_summary_tokens,
            },
        }

    def get_user_metrics(self, user_id: str) -> Dict:
        """
        Get metrics for a specific user.

        Args:
            user_id: User identifier

        Returns:
            Dict with user-specific metrics
        """
        return {
            "user_id": user_id,
            "tokens_used": self._metrics.tokens.per_user_tokens.get(user_id, 0),
            "percentage_of_total": (
                self._metrics.tokens.per_user_tokens.get(user_id, 0) / self._metrics.tokens.total_tokens * 100
                if self._metrics.tokens.total_tokens > 0
                else 0
            ),
        }

    def get_snapshots(self, count: int = 10) -> List[Dict]:
        """
        Get recent metric snapshots.

        Args:
            count: Number of snapshots to return

        Returns:
            List of recent snapshots
        """
        recent = self._snapshots[-count:] if len(self._snapshots) > count else self._snapshots
        return [
            {"timestamp": s.timestamp.isoformat(), "compression_ratio": s.compression.average_compression_ratio}
            for s in recent
        ]

    def reset(self):
        """Reset all metrics to zero"""
        self._metrics = MetricsSnapshot()
        self._snapshots.clear()
        self._last_snapshot = datetime.now()
        logger.info("Metrics reset")

    async def persist(self):
        """Persist metrics to Redis"""
        if not self.config.redis:
            return

        try:
            redis = Redis(self.config.redis)
            metrics_key = f"{self._prefix}:current"
            await redis.set(key=metrics_key, data=self._metrics.model_dump_json(), timeout_sec=3600)
            logger.debug("Metrics persisted to Redis")
        except Exception as e:
            logger.warning(f"Failed to persist metrics: {e}")

    async def load(self):
        """Load metrics from Redis"""
        if not self.config.redis:
            return

        try:
            redis = Redis(self.config.redis)
            metrics_key = f"{self._prefix}:current"
            data = await redis.get(key=metrics_key)
            if data:
                self._metrics = MetricsSnapshot.model_validate_json(data)
                logger.debug("Metrics loaded from Redis")
        except Exception as e:
            logger.debug(f"Failed to load metrics: {e}")

    # Private helper methods

    def _check_snapshot(self):
        """Check if it's time to take a snapshot"""
        if (datetime.now() - self._last_snapshot).total_seconds() >= self.snapshot_interval:
            self._take_snapshot()

    def _take_snapshot(self):
        """Take a snapshot of current metrics"""
        snapshot = self._metrics.model_copy(deep=True)
        snapshot.timestamp = datetime.now()
        self._snapshots.append(snapshot)
        self._last_snapshot = datetime.now()

        # Keep only last 100 snapshots to prevent memory bloat
        if len(self._snapshots) > 100:
            self._snapshots = self._snapshots[-100:]

        logger.debug(f"Metrics snapshot taken at {snapshot.timestamp}")

    def _get_top_users(self, count: int = 5) -> List[Dict]:
        """Get top users by token usage"""
        sorted_users = sorted(
            self._metrics.tokens.per_user_tokens.items(), key=lambda x: x[1], reverse=True
        )[:count]
        return [{"user_id": user_id, "tokens": tokens} for user_id, tokens in sorted_users]


class LatencyTracker:
    """
    Context manager for automatic latency tracking.

    Usage:
        collector = MetricsCollector(config)
        with LatencyTracker(collector):
            # Do some work
            await llm.acompletion(...)
        # Latency automatically recorded
    """

    def __init__(self, collector: MetricsCollector):
        self.collector = collector
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            latency_ms = (time.time() - self.start_time) * 1000
            self.collector.record_latency(latency_ms)
