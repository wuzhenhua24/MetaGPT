#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/11/16
@Author  : MetaGPT Team
@File    : multi_user_context_management.py
@Desc    : Example of multi-user context management with session isolation,
           quota management, metrics collection, and graceful degradation
"""

import asyncio

from metagpt.config2 import Config
from metagpt.configs.compress_msg_config import CompressType
from metagpt.configs.llm_config import LLMConfig
from metagpt.configs.redis_config import RedisConfig
from metagpt.logs import logger
from metagpt.management import (
    AdaptiveDegradationStrategy,
    ContextOverflowError,
    LatencyTracker,
    MetricsCollector,
    QuotaConfig,
    QuotaExceeded,
    QuotaManager,
    QuotaPeriod,
    SessionManager,
)
from metagpt.memory.brain_memory import BrainMemory
from metagpt.provider.openai_api import OpenAILLM
from metagpt.schema import Message


class MultiUserChatService:
    """
    Production-ready multi-user chat service with comprehensive management.

    Features:
    - Session isolation per user/chat
    - Token quota management
    - Performance metrics collection
    - Automatic context degradation
    - Redis persistence
    """

    def __init__(self, config: Config):
        self.config = config
        self.session_manager = SessionManager(config)
        self.quota_manager = QuotaManager(
            config,
            default_quota=QuotaConfig(
                max_tokens_per_period=100000,  # 100K tokens per day
                max_requests_per_period=1000,  # 1000 requests per day
                max_concurrent_sessions=10,  # 10 concurrent sessions
                max_history_length=100,  # 100 messages max
                max_context_tokens=8000,  # 8K tokens per request
                period=QuotaPeriod.DAILY,
            ),
        )
        self.metrics_collector = MetricsCollector(config, snapshot_interval=300)  # 5 min snapshots
        self.llm = OpenAILLM(config.llm)

    async def create_user_session(self, user_id: str, chat_id: str = None) -> str:
        """
        Create a new session for a user.

        Args:
            user_id: User identifier
            chat_id: Optional chat identifier

        Returns:
            str: Session ID

        Raises:
            QuotaExceeded: If user has too many active sessions
        """
        # Check concurrent session quota
        active_sessions = await self.session_manager.list_user_sessions(user_id)
        quota = self.quota_manager.get_user_quota(user_id)

        if len(active_sessions) >= quota.max_concurrent_sessions:
            raise QuotaExceeded(
                f"User {user_id} has reached max concurrent sessions " f"({quota.max_concurrent_sessions})"
            )

        # Create session
        session = await self.session_manager.create_session(user_id, chat_id, ttl=3600)  # 1 hour TTL

        # Update metrics and quota
        self.metrics_collector.record_session_created()
        await self.quota_manager.increment_sessions(user_id)

        logger.info(f"Created session {session.session_id} for user {user_id}")
        return session.session_id

    async def send_message(self, session_id: str, user_message: str) -> str:
        """
        Send a message in a session.

        Args:
            session_id: Session identifier
            user_message: User's message

        Returns:
            str: Assistant's response

        Raises:
            QuotaExceeded: If user quota exceeded
            ContextOverflowError: If context too large
        """
        with LatencyTracker(self.metrics_collector):
            # Get session
            session = await self.session_manager.get_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")

            # Load memory
            brain_memory = await self.session_manager.get_memory(session_id)
            if not brain_memory:
                brain_memory = BrainMemory(config=self.config)

            # Add user message to history
            user_msg = Message(role="user", content=user_message)
            brain_memory.history.append(user_msg)

            # Prepare messages for LLM
            messages = brain_memory.history.copy()

            # Apply graceful degradation if needed
            degradation_strategy = AdaptiveDegradationStrategy(
                llm=self.llm,
                max_tokens=self.quota_manager.get_user_quota(session.user_id).max_context_tokens,
                threshold=0.8,
                min_messages=3,
            )

            try:
                messages = await degradation_strategy.handle_overflow(messages, brain_memory)
            except ContextOverflowError as e:
                logger.error(f"Context overflow for session {session_id}: {e}")
                raise

            # Estimate tokens for quota check
            from metagpt.utils.token_counter import count_message_tokens

            msg_dicts = [
                m.to_dict() if hasattr(m, "to_dict") else {"role": m.role, "content": m.content} for m in messages
            ]
            estimated_tokens = count_message_tokens(msg_dicts, model=self.llm.model)

            # Check and consume quota
            try:
                await self.quota_manager.check_and_consume(
                    user_id=session.user_id, tokens=estimated_tokens, requests=1
                )
            except QuotaExceeded as e:
                logger.warning(f"Quota exceeded for user {session.user_id}: {e}")
                raise

            # Call LLM
            response = await self.llm.aask(
                msg=user_message,
                system_msgs=[m.content for m in messages if m.role == "system"],
            )

            # Add assistant response to history
            assistant_msg = Message(role="assistant", content=response)
            brain_memory.history.append(assistant_msg)

            # Save memory
            await self.session_manager.save_memory(session_id, brain_memory)

            # Record metrics
            self.metrics_collector.record_token_usage(
                user_id=session.user_id, tokens=estimated_tokens, session_id=session_id
            )

            # Record compression if applied
            level = degradation_strategy.get_current_level(brain_memory.history)
            if level.value > 0:
                original = count_message_tokens(
                    [m.to_dict() if hasattr(m, "to_dict") else {"role": m.role, "content": m.content} for m in brain_memory.history],
                    model=self.llm.model,
                )
                compressed = count_message_tokens(msg_dicts, model=self.llm.model)
                self.metrics_collector.record_compression(original, compressed)

            logger.info(f"Response generated for session {session_id}")
            return response

    async def end_session(self, session_id: str):
        """
        End a session and clean up resources.

        Args:
            session_id: Session identifier
        """
        session = await self.session_manager.get_session(session_id)
        if session:
            await self.quota_manager.decrement_sessions(session.user_id)
            await self.session_manager.delete_session(session_id)
            self.metrics_collector.record_session_deleted()
            logger.info(f"Ended session {session_id}")

    async def get_user_quota_status(self, user_id: str) -> dict:
        """
        Get quota status for a user.

        Args:
            user_id: User identifier

        Returns:
            dict: Quota status
        """
        return await self.quota_manager.get_remaining_quota(user_id)

    async def get_metrics_summary(self) -> dict:
        """Get overall metrics summary"""
        return self.metrics_collector.get_summary()

    async def set_user_quota(self, user_id: str, quota_config: QuotaConfig):
        """
        Set custom quota for a user.

        Args:
            user_id: User identifier
            quota_config: Custom quota configuration
        """
        self.quota_manager.set_user_quota(user_id, quota_config)
        logger.info(f"Set custom quota for user {user_id}")


async def example_basic_usage():
    """Basic usage example"""
    print("\n=== Basic Usage Example ===\n")

    # Configure
    config = Config(
        llm=LLMConfig(
            model="gpt-4-turbo-preview",
            compress_type=CompressType.POST_CUT_BY_TOKEN,
            max_token=8000,
            context_length=128000,
        ),
        # Uncomment if you have Redis configured
        # redis=RedisConfig(
        #     host="localhost",
        #     port=6379,
        #     password="your_password",
        #     db="0"
        # )
    )

    # Create service
    service = MultiUserChatService(config)

    # Create sessions for two different users
    user1_session = await service.create_user_session("alice")
    user2_session = await service.create_user_session("bob")

    print(f"Created sessions: alice={user1_session}, bob={user2_session}\n")

    # Send messages from user 1
    response1 = await service.send_message(user1_session, "Hello! What's the weather like?")
    print(f"Alice: Hello! What's the weather like?")
    print(f"Assistant: {response1}\n")

    # Send messages from user 2 (completely isolated)
    response2 = await service.send_message(user2_session, "Can you help me with Python?")
    print(f"Bob: Can you help me with Python?")
    print(f"Assistant: {response2}\n")

    # Check quota status
    alice_quota = await service.get_user_quota_status("alice")
    print(f"Alice's quota: {alice_quota}\n")

    # Get metrics
    metrics = await service.get_metrics_summary()
    print(f"System metrics: {metrics}\n")

    # Clean up
    await service.end_session(user1_session)
    await service.end_session(user2_session)


async def example_custom_quota():
    """Example with custom user quota"""
    print("\n=== Custom Quota Example ===\n")

    config = Config(llm=LLMConfig(model="gpt-4-turbo-preview"))
    service = MultiUserChatService(config)

    # Set premium user quota
    premium_quota = QuotaConfig(
        max_tokens_per_period=500000,  # 500K tokens per day
        max_requests_per_period=5000,
        max_concurrent_sessions=50,
        max_context_tokens=32000,  # 32K context
        period=QuotaPeriod.DAILY,
    )
    await service.set_user_quota("premium_user", premium_quota)

    # Set free tier quota
    free_quota = QuotaConfig(
        max_tokens_per_period=10000,  # 10K tokens per day
        max_requests_per_period=100,
        max_concurrent_sessions=3,
        max_context_tokens=4000,  # 4K context
        period=QuotaPeriod.DAILY,
    )
    await service.set_user_quota("free_user", free_quota)

    print("Quota configured:")
    print(f"Premium user: {await service.get_user_quota_status('premium_user')}")
    print(f"Free user: {await service.get_user_quota_status('free_user')}")


async def example_graceful_degradation():
    """Example demonstrating graceful degradation"""
    print("\n=== Graceful Degradation Example ===\n")

    config = Config(llm=LLMConfig(model="gpt-4-turbo-preview"))
    service = MultiUserChatService(config)

    session_id = await service.create_user_session("test_user")

    # Simulate a long conversation
    for i in range(50):
        await service.send_message(session_id, f"Message {i}: Tell me about topic {i}")
        print(f"Sent message {i}")

    # Get degradation stats
    metrics = await service.get_metrics_summary()
    print(f"\nDegradation stats: {metrics.get('compression', {})}")

    await service.end_session(session_id)


async def example_quota_exceeded():
    """Example handling quota exceeded"""
    print("\n=== Quota Exceeded Handling ===\n")

    config = Config(llm=LLMConfig(model="gpt-4-turbo-preview"))
    service = MultiUserChatService(config)

    # Set very low quota for demo
    low_quota = QuotaConfig(
        max_tokens_per_period=100,  # Very low
        max_requests_per_period=2,
        max_concurrent_sessions=1,
        period=QuotaPeriod.HOURLY,
    )
    await service.set_user_quota("limited_user", low_quota)

    session_id = await service.create_user_session("limited_user")

    try:
        # This should work
        await service.send_message(session_id, "Short message")
        print("Message 1: Success")

        # This might exceed quota
        await service.send_message(session_id, "Another message")
        print("Message 2: Success")

        # This should exceed quota
        await service.send_message(session_id, "One more message")
        print("Message 3: Success")

    except QuotaExceeded as e:
        print(f"\nQuota exceeded: {e}")
        quota_status = await service.get_user_quota_status("limited_user")
        print(f"Current quota: {quota_status}")

    await service.end_session(session_id)


async def main():
    """Run all examples"""
    # Note: These examples require OpenAI API key to be configured
    # export OPENAI_API_KEY=your_key_here

    try:
        await example_basic_usage()
    except Exception as e:
        logger.error(f"Basic usage example failed: {e}")

    try:
        await example_custom_quota()
    except Exception as e:
        logger.error(f"Custom quota example failed: {e}")

    try:
        await example_graceful_degradation()
    except Exception as e:
        logger.error(f"Graceful degradation example failed: {e}")

    try:
        await example_quota_exceeded()
    except Exception as e:
        logger.error(f"Quota exceeded example failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
