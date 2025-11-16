#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : test_graceful_degradation.py
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from metagpt.config2 import Config
from metagpt.configs.llm_config import LLMConfig
from metagpt.management.graceful_degradation import (
    AdaptiveDegradationStrategy,
    ContextOverflowError,
    DegradationLevel,
    DegradationStrategy,
)
from metagpt.memory.brain_memory import BrainMemory
from metagpt.schema import Message


@pytest.fixture
def config():
    """Create test configuration"""
    return Config(llm=LLMConfig(model="gpt-4"))


@pytest.fixture
def mock_llm():
    """Create mock LLM"""
    llm = MagicMock()
    llm.model = "gpt-4"
    llm.compress_messages = MagicMock(return_value=[])
    return llm


@pytest.fixture
def strategy(mock_llm):
    """Create degradation strategy instance"""
    return DegradationStrategy(
        llm=mock_llm, max_tokens=1000, threshold=0.8, min_messages=2, summarize_max_words=100
    )


def create_messages(count: int) -> list:
    """Helper to create test messages"""
    messages = [Message(role="system", content="You are a helpful assistant.")]
    for i in range(count):
        messages.append(Message(role="user", content=f"User message {i}"))
        messages.append(Message(role="assistant", content=f"Assistant response {i}"))
    return messages


def test_degradation_levels():
    """Test degradation level enum"""
    assert DegradationLevel.NONE < DegradationLevel.COMPRESS
    assert DegradationLevel.COMPRESS < DegradationLevel.SUMMARIZE
    assert DegradationLevel.SUMMARIZE < DegradationLevel.TRUNCATE
    assert DegradationLevel.TRUNCATE < DegradationLevel.REJECT


def test_assess_degradation_level_none(strategy):
    """Test degradation level assessment - no degradation needed"""
    # Small number of messages
    messages = create_messages(2)

    # Mock token counting to return low value
    strategy._count_tokens = MagicMock(return_value=500)

    level = strategy.get_current_level(messages)
    assert level == DegradationLevel.NONE


def test_assess_degradation_level_compress(strategy):
    """Test degradation level assessment - compression needed"""
    messages = create_messages(10)

    # Mock token counting to return value requiring compression
    strategy._count_tokens = MagicMock(return_value=900)

    level = strategy.get_current_level(messages)
    assert level == DegradationLevel.COMPRESS


def test_assess_degradation_level_reject(strategy):
    """Test degradation level assessment - must reject"""
    messages = create_messages(20)

    # Mock token counting to return extremely high value
    strategy._count_tokens = MagicMock(return_value=10000)
    strategy.estimate_tokens_after_degradation = MagicMock(return_value=5000)

    level = strategy.get_current_level(messages)
    assert level == DegradationLevel.REJECT


@pytest.mark.asyncio
async def test_handle_overflow_none(strategy):
    """Test handling overflow when no degradation needed"""
    messages = create_messages(2)
    strategy._count_tokens = MagicMock(return_value=500)

    result = await strategy.handle_overflow(messages)
    assert len(result) == len(messages)


@pytest.mark.asyncio
async def test_handle_overflow_compress(strategy, mock_llm):
    """Test handling overflow with compression"""
    messages = create_messages(10)
    strategy._count_tokens = MagicMock(return_value=900)

    # Mock compression result
    compressed = create_messages(5)
    compressed_dicts = [{"role": m.role, "content": m.content} for m in compressed]
    mock_llm.compress_messages.return_value = compressed_dicts

    result = await strategy.handle_overflow(messages)
    assert mock_llm.compress_messages.called


@pytest.mark.asyncio
async def test_handle_overflow_summarize(strategy, mock_llm, config):
    """Test handling overflow with summarization"""
    messages = create_messages(20)

    # Mock to require summarization
    strategy._assess_degradation_level = MagicMock(return_value=DegradationLevel.SUMMARIZE)

    # Create mock brain_memory
    brain_memory = BrainMemory(config=config)
    brain_memory.summarize = AsyncMock()
    brain_memory.historical_summary = "This is a summary of the conversation."

    result = await strategy.handle_overflow(messages, brain_memory)

    # Should have called summarize
    assert brain_memory.summarize.called


@pytest.mark.asyncio
async def test_handle_overflow_truncate(strategy):
    """Test handling overflow with truncation"""
    messages = create_messages(30)

    # Mock to require truncation
    strategy._assess_degradation_level = MagicMock(return_value=DegradationLevel.TRUNCATE)
    strategy._count_tokens = MagicMock(return_value=100)

    result = await strategy.handle_overflow(messages)

    # Should keep system message + min_messages
    # 1 system + 2*2 (user+assistant pairs) = 5 messages max
    assert len(result) <= 1 + (strategy.min_messages * 2)


@pytest.mark.asyncio
async def test_handle_overflow_reject(strategy):
    """Test handling overflow with rejection"""
    messages = create_messages(50)

    # Mock to require rejection
    strategy._assess_degradation_level = MagicMock(return_value=DegradationLevel.REJECT)

    with pytest.raises(ContextOverflowError):
        await strategy.handle_overflow(messages)


def test_estimate_tokens_after_degradation(strategy):
    """Test token estimation after degradation"""
    messages = create_messages(20)

    # Mock token counting
    strategy._count_tokens = MagicMock(return_value=2000)

    # Test different levels
    estimate_none = strategy.estimate_tokens_after_degradation(messages, DegradationLevel.NONE)
    assert estimate_none == 2000

    estimate_compress = strategy.estimate_tokens_after_degradation(messages, DegradationLevel.COMPRESS)
    assert estimate_compress == int(2000 * 0.8)  # threshold

    estimate_truncate = strategy.estimate_tokens_after_degradation(messages, DegradationLevel.TRUNCATE)
    # Should be much smaller
    assert estimate_truncate < estimate_compress


def test_adaptive_strategy_learning():
    """Test adaptive strategy learning from degradations"""
    mock_llm = MagicMock()
    mock_llm.model = "gpt-4"

    adaptive = AdaptiveDegradationStrategy(llm=mock_llm, max_tokens=1000)

    # Record some degradations
    adaptive._record_degradation(DegradationLevel.COMPRESS)
    adaptive._record_degradation(DegradationLevel.COMPRESS)
    adaptive._record_degradation(DegradationLevel.SUMMARIZE)

    stats = adaptive.get_degradation_stats()
    assert stats["total"] == 3
    assert stats["by_level"]["COMPRESS"] == 2
    assert stats["by_level"]["SUMMARIZE"] == 1


def test_adaptive_strategy_recommend_new_conversation():
    """Test adaptive strategy recommendation for new conversation"""
    mock_llm = MagicMock()
    mock_llm.model = "gpt-4"

    adaptive = AdaptiveDegradationStrategy(llm=mock_llm, max_tokens=1000)

    # Should not recommend initially
    assert not adaptive._should_recommend_new_conversation()

    # Record many degradations
    for _ in range(15):
        adaptive._record_degradation(DegradationLevel.COMPRESS)

    # Should recommend now
    assert adaptive._should_recommend_new_conversation()


def test_adaptive_strategy_recommend_on_truncate():
    """Test recommendation on TRUNCATE level degradation"""
    mock_llm = MagicMock()
    adaptive = AdaptiveDegradationStrategy(llm=mock_llm, max_tokens=1000)

    # Record some normal degradations
    for _ in range(5):
        adaptive._record_degradation(DegradationLevel.NONE)

    # Record a TRUNCATE degradation
    adaptive._record_degradation(DegradationLevel.TRUNCATE)

    # Should recommend new conversation
    assert adaptive._should_recommend_new_conversation()


def test_count_tokens_fallback(strategy):
    """Test token counting fallback when tokenizer fails"""
    messages = [Message(role="user", content="Hello world! " * 100)]

    # Make count_message_tokens fail
    import metagpt.management.graceful_degradation as gd_module

    original_count = gd_module.count_message_tokens
    gd_module.count_message_tokens = MagicMock(side_effect=Exception("Tokenizer error"))

    try:
        count = strategy._count_tokens(messages)
        # Should use fallback (chars / 4)
        assert count > 0
    finally:
        # Restore
        gd_module.count_message_tokens = original_count
