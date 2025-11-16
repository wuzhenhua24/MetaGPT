#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : graceful_degradation.py
@Desc    : Graceful degradation strategies for context overflow handling
"""

from enum import IntEnum
from typing import List, Optional

from metagpt.configs.compress_msg_config import CompressType
from metagpt.logs import logger
from metagpt.memory.brain_memory import BrainMemory
from metagpt.provider.base_llm import BaseLLM
from metagpt.schema import Message
from metagpt.utils.token_counter import count_message_tokens


class DegradationLevel(IntEnum):
    """Degradation levels for handling context overflow"""

    NONE = 0  # No degradation needed
    COMPRESS = 1  # Apply message compression
    SUMMARIZE = 2  # Summarize history
    TRUNCATE = 3  # Aggressive truncation
    REJECT = 4  # Reject request


class ContextOverflowError(Exception):
    """Raised when context cannot fit within model limits even after degradation"""

    pass


class DegradationStrategy:
    """
    Strategy for handling context overflow with multiple degradation levels.

    Degradation hierarchy:
    1. Level 0 (NONE): No action needed, context within limits
    2. Level 1 (COMPRESS): Apply POST_CUT_BY_TOKEN compression
    3. Level 2 (SUMMARIZE): Summarize history into a compact form
    4. Level 3 (TRUNCATE): Keep only system message + recent N messages
    5. Level 4 (REJECT): Cannot handle, reject request

    Usage:
        strategy = DegradationStrategy(llm, max_tokens=8000)
        messages = await strategy.handle_overflow(messages, brain_memory)
    """

    def __init__(
        self,
        llm: BaseLLM,
        max_tokens: int = 8000,
        threshold: float = 0.8,
        min_messages: int = 3,
        summarize_max_words: int = 200,
    ):
        """
        Initialize degradation strategy.

        Args:
            llm: LLM instance for token counting and summarization
            max_tokens: Maximum token limit for context
            threshold: Token usage threshold (default: 0.8 = 80% for input)
            min_messages: Minimum messages to keep during truncation
            summarize_max_words: Maximum words for summary
        """
        self.llm = llm
        self.max_tokens = max_tokens
        self.threshold = threshold
        self.min_messages = min_messages
        self.summarize_max_words = summarize_max_words

    async def handle_overflow(
        self, messages: List[Message], brain_memory: Optional[BrainMemory] = None
    ) -> List[Message]:
        """
        Handle context overflow by applying degradation strategies.

        Args:
            messages: List of messages (history + current)
            brain_memory: Optional BrainMemory for summarization

        Returns:
            List[Message]: Processed messages within token limit

        Raises:
            ContextOverflowError: If cannot fit within limits
        """
        level = self._assess_degradation_level(messages)

        if level == DegradationLevel.NONE:
            logger.debug("No degradation needed")
            return messages

        logger.info(f"Applying degradation level: {level.name}")

        if level == DegradationLevel.COMPRESS:
            return await self._apply_compression(messages)

        elif level == DegradationLevel.SUMMARIZE:
            if brain_memory:
                return await self._apply_summarization(messages, brain_memory)
            else:
                # Fallback to compression if no brain_memory
                logger.warning("No BrainMemory provided, falling back to compression")
                return await self._apply_compression(messages)

        elif level == DegradationLevel.TRUNCATE:
            return self._apply_truncation(messages)

        else:  # REJECT
            raise ContextOverflowError(
                f"Context too large ({self._count_tokens(messages)} tokens) "
                f"and cannot be reduced to fit {self.max_tokens} tokens. "
                "Please start a new conversation."
            )

    def get_current_level(self, messages: List[Message]) -> DegradationLevel:
        """
        Get current degradation level without applying it.

        Args:
            messages: List of messages

        Returns:
            DegradationLevel: Current required degradation level
        """
        return self._assess_degradation_level(messages)

    def estimate_tokens_after_degradation(self, messages: List[Message], level: DegradationLevel) -> int:
        """
        Estimate token count after applying a degradation level.

        Args:
            messages: List of messages
            level: Degradation level to apply

        Returns:
            int: Estimated token count
        """
        if level == DegradationLevel.NONE:
            return self._count_tokens(messages)

        elif level == DegradationLevel.COMPRESS:
            # Estimate: keep ~80% based on threshold
            return int(self._count_tokens(messages) * self.threshold)

        elif level == DegradationLevel.SUMMARIZE:
            # Estimate: system message + summary (~200 words = ~300 tokens) + recent messages
            return 300 + self._count_tokens(messages[-self.min_messages :])

        elif level == DegradationLevel.TRUNCATE:
            # Only system message + min messages
            system_msgs = [m for m in messages if m.role == "system"]
            recent_msgs = [m for m in messages if m.role != "system"][-self.min_messages :]
            return self._count_tokens(system_msgs + recent_msgs)

        return 0

    # Private methods for degradation strategies

    def _assess_degradation_level(self, messages: List[Message]) -> DegradationLevel:
        """Assess which degradation level is needed"""
        current_tokens = self._count_tokens(messages)
        limit = int(self.max_tokens * self.threshold)

        logger.debug(f"Token assessment: {current_tokens}/{limit} (threshold: {self.threshold})")

        # No degradation needed
        if current_tokens <= limit:
            return DegradationLevel.NONE

        # Try compression (aim for ~80% reduction)
        estimated_after_compress = current_tokens * 0.8
        if estimated_after_compress <= limit:
            return DegradationLevel.COMPRESS

        # Try summarization (more aggressive)
        estimated_after_summarize = self.estimate_tokens_after_degradation(messages, DegradationLevel.SUMMARIZE)
        if estimated_after_summarize <= limit:
            return DegradationLevel.SUMMARIZE

        # Try truncation (most aggressive)
        estimated_after_truncate = self.estimate_tokens_after_degradation(messages, DegradationLevel.TRUNCATE)
        if estimated_after_truncate <= limit:
            return DegradationLevel.TRUNCATE

        # Cannot handle, must reject
        return DegradationLevel.REJECT

    async def _apply_compression(self, messages: List[Message]) -> List[Message]:
        """Apply message compression"""
        logger.info("Applying POST_CUT_BY_TOKEN compression")

        # Convert to dict format for LLM compression
        msg_dicts = [m.to_dict() if hasattr(m, "to_dict") else {"role": m.role, "content": m.content} for m in messages]

        compressed_dicts = self.llm.compress_messages(
            messages=msg_dicts,
            compress_type=CompressType.POST_CUT_BY_TOKEN,
            max_token=self.max_tokens,
            threshold=self.threshold,
        )

        # Convert back to Message objects
        compressed_messages = []
        for md in compressed_dicts:
            # Find original message or create new one
            matching = [m for m in messages if m.role == md.get("role") and m.content == md.get("content")]
            if matching:
                compressed_messages.append(matching[0])
            else:
                compressed_messages.append(Message(role=md.get("role"), content=md.get("content")))

        original_count = self._count_tokens(messages)
        compressed_count = self._count_tokens(compressed_messages)
        logger.info(f"Compression: {original_count} -> {compressed_count} tokens " f"({len(messages)} -> {len(compressed_messages)} messages)")

        return compressed_messages

    async def _apply_summarization(self, messages: List[Message], brain_memory: BrainMemory) -> List[Message]:
        """Apply history summarization using BrainMemory"""
        logger.info("Applying history summarization")

        # Separate system messages from history
        system_messages = [m for m in messages if m.role == "system"]
        user_assistant_messages = [m for m in messages if m.role in ("user", "assistant")]

        # Keep recent messages, summarize older ones
        recent_count = min(self.min_messages, len(user_assistant_messages))
        to_summarize = user_assistant_messages[:-recent_count] if recent_count > 0 else user_assistant_messages
        recent_messages = user_assistant_messages[-recent_count:] if recent_count > 0 else []

        if to_summarize:
            # Update brain_memory history and summarize
            brain_memory.history = to_summarize
            await brain_memory.summarize(self.llm, max_words=self.summarize_max_words)

            # Create summary message
            summary_msg = Message(
                role="system",
                content=f"[Previous conversation summary]\n{brain_memory.historical_summary}",
            )

            result = system_messages + [summary_msg] + recent_messages
        else:
            result = system_messages + recent_messages

        original_count = self._count_tokens(messages)
        summarized_count = self._count_tokens(result)
        logger.info(
            f"Summarization: {original_count} -> {summarized_count} tokens "
            f"({len(messages)} -> {len(result)} messages)"
        )

        return result

    def _apply_truncation(self, messages: List[Message]) -> List[Message]:
        """Apply aggressive truncation (keep only system + recent messages)"""
        logger.warning(f"Applying aggressive truncation, keeping only {self.min_messages} recent messages")

        system_messages = [m for m in messages if m.role == "system"]
        non_system_messages = [m for m in messages if m.role != "system"]

        # Keep only the most recent messages
        recent_messages = non_system_messages[-self.min_messages :]

        result = system_messages + recent_messages

        original_count = self._count_tokens(messages)
        truncated_count = self._count_tokens(result)
        logger.warning(
            f"Truncation: {original_count} -> {truncated_count} tokens "
            f"({len(messages)} -> {len(result)} messages)"
        )

        return result

    def _count_tokens(self, messages: List[Message]) -> int:
        """Count tokens in messages"""
        # Convert to dict format for token counting
        msg_dicts = [m.to_dict() if hasattr(m, "to_dict") else {"role": m.role, "content": m.content} for m in messages]

        try:
            return count_message_tokens(msg_dicts, model=self.llm.model)
        except Exception as e:
            logger.warning(f"Failed to count tokens: {e}, using character estimate")
            # Fallback: rough estimate (1 token ≈ 4 characters)
            total_chars = sum(len(str(md.get("content", ""))) for md in msg_dicts)
            return total_chars // 4


class AdaptiveDegradationStrategy(DegradationStrategy):
    """
    Adaptive degradation strategy that learns from previous degradations.

    Features:
    - Tracks degradation frequency
    - Adjusts threshold automatically
    - Suggests when to start new conversation
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._degradation_history: List[DegradationLevel] = []
        self._max_history = 100

    async def handle_overflow(
        self, messages: List[Message], brain_memory: Optional[BrainMemory] = None
    ) -> List[Message]:
        """Handle overflow with adaptive learning"""
        level = self._assess_degradation_level(messages)
        self._record_degradation(level)

        # Check if we're degrading too frequently
        if self._should_recommend_new_conversation():
            logger.warning(
                "Frequent degradations detected. Consider starting a new conversation " "for better performance."
            )

        return await super().handle_overflow(messages, brain_memory)

    def _record_degradation(self, level: DegradationLevel):
        """Record degradation event"""
        self._degradation_history.append(level)
        if len(self._degradation_history) > self._max_history:
            self._degradation_history = self._degradation_history[-self._max_history :]

    def _should_recommend_new_conversation(self) -> bool:
        """Check if should recommend starting a new conversation"""
        if len(self._degradation_history) < 10:
            return False

        recent = self._degradation_history[-10:]

        # If more than 70% of recent interactions required degradation
        degraded_count = sum(1 for level in recent if level > DegradationLevel.NONE)
        if degraded_count > 7:
            return True

        # If any recent TRUNCATE level degradations
        if any(level >= DegradationLevel.TRUNCATE for level in recent[-5:]):
            return True

        return False

    def get_degradation_stats(self) -> dict:
        """Get statistics about degradation history"""
        if not self._degradation_history:
            return {"total": 0}

        level_counts = {level: self._degradation_history.count(level) for level in DegradationLevel}

        return {
            "total": len(self._degradation_history),
            "by_level": {level.name: count for level, count in level_counts.items()},
            "degradation_rate": sum(1 for l in self._degradation_history if l > DegradationLevel.NONE)
            / len(self._degradation_history),
        }
