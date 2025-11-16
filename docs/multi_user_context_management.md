# 多用户上下文管理功能

本文档介绍 MetaGPT 新增的多用户上下文管理功能，包括会话管理、配额管理、监控指标和优雅降级等生产环境必需的特性。

## 功能概述

### 1. 会话管理器 (SessionManager)

统一管理用户会话，避免手动构建 Redis key，提供完整的会话生命周期管理。

**核心功能**：
- ✅ 自动生成会话 ID
- ✅ 会话过期时间管理（TTL）
- ✅ 会话元数据跟踪
- ✅ Redis 持久化
- ✅ 用户会话列表查询

**使用示例**：
```python
from metagpt.config2 import Config
from metagpt.management import SessionManager

config = Config(...)
session_manager = SessionManager(config)

# 创建会话
session = await session_manager.create_session(
    user_id="user123",
    chat_id="chat456",  # 可选，自动生成
    ttl=3600,           # 1 小时过期
    metadata={"source": "web"}
)

# 获取会话
session = await session_manager.get_session(session.session_id)

# 获取会话内存
brain_memory = await session_manager.get_memory(session.session_id)

# 保存内存
await session_manager.save_memory(session.session_id, brain_memory)

# 列出用户的所有会话
sessions = await session_manager.list_user_sessions("user123")

# 删除会话
await session_manager.delete_session(session.session_id)
```

**API 文档**：

| 方法 | 描述 | 参数 | 返回值 |
|------|------|------|--------|
| `create_session` | 创建新会话 | user_id, chat_id?, ttl, metadata? | Session |
| `get_session` | 获取会话 | session_id | Session \| None |
| `delete_session` | 删除会话 | session_id | bool |
| `list_user_sessions` | 列出用户会话 | user_id | List[Session] |
| `get_memory` | 获取会话内存 | session_id | BrainMemory \| None |
| `save_memory` | 保存会话内存 | session_id, brain_memory | bool |
| `set_ttl` | 设置会话 TTL | session_id, ttl | bool |

### 2. 配额管理器 (QuotaManager)

限制用户资源使用，防止滥用，支持灵活的配额策略。

**核心功能**：
- ✅ Token 使用量限制
- ✅ 请求频率限制
- ✅ 并发会话数限制
- ✅ 单次请求上下文限制
- ✅ 多种配额周期（分钟/小时/天/周/月）
- ✅ 每用户自定义配额
- ✅ 自动配额重置

**配额周期**：
```python
from metagpt.management import QuotaPeriod

QuotaPeriod.MINUTE   # 每分钟
QuotaPeriod.HOURLY   # 每小时
QuotaPeriod.DAILY    # 每天（默认）
QuotaPeriod.WEEKLY   # 每周
QuotaPeriod.MONTHLY  # 每月
```

**使用示例**：
```python
from metagpt.management import QuotaManager, QuotaConfig, QuotaPeriod

quota_manager = QuotaManager(config, default_quota=QuotaConfig(
    max_tokens_per_period=100000,    # 每天 100K tokens
    max_requests_per_period=1000,    # 每天 1000 次请求
    max_concurrent_sessions=10,      # 最多 10 个并发会话
    max_context_tokens=8000,         # 单次请求最多 8K tokens
    period=QuotaPeriod.DAILY
))

# 设置 VIP 用户配额
vip_quota = QuotaConfig(
    max_tokens_per_period=500000,
    max_requests_per_period=5000,
    max_concurrent_sessions=50,
    max_context_tokens=32000,
    period=QuotaPeriod.DAILY
)
quota_manager.set_user_quota("vip_user", vip_quota)

# 检查配额
if await quota_manager.check_quota("user123", tokens=1000):
    # 消耗配额
    await quota_manager.consume_quota("user123", tokens=1000, requests=1)

# 或者一步完成
try:
    await quota_manager.check_and_consume("user123", tokens=1000, requests=1)
except QuotaExceeded as e:
    print(f"配额超限: {e}")

# 查询剩余配额
remaining = await quota_manager.get_remaining_quota("user123")
print(f"剩余 tokens: {remaining['tokens']['remaining']}")
print(f"剩余请求: {remaining['requests']['remaining']}")
```

**配额配置示例**：

**免费用户**：
```python
QuotaConfig(
    max_tokens_per_period=10000,     # 每天 10K tokens
    max_requests_per_period=100,      # 每天 100 次
    max_concurrent_sessions=3,        # 最多 3 个会话
    max_context_tokens=4000,          # 单次 4K tokens
    period=QuotaPeriod.DAILY
)
```

**标准用户**：
```python
QuotaConfig(
    max_tokens_per_period=100000,    # 每天 100K tokens
    max_requests_per_period=1000,     # 每天 1000 次
    max_concurrent_sessions=10,       # 最多 10 个会话
    max_context_tokens=8000,          # 单次 8K tokens
    period=QuotaPeriod.DAILY
)
```

**高级用户**：
```python
QuotaConfig(
    max_tokens_per_period=500000,    # 每天 500K tokens
    max_requests_per_period=5000,     # 每天 5000 次
    max_concurrent_sessions=50,       # 最多 50 个会话
    max_context_tokens=32000,         # 单次 32K tokens
    period=QuotaPeriod.DAILY
)
```

### 3. 监控指标收集器 (MetricsCollector)

收集系统性能和资源使用指标，支持监控和分析。

**核心功能**：
- ✅ 压缩指标（压缩率、节省的 tokens）
- ✅ 缓存指标（命中率、未命中率）
- ✅ Token 使用指标（每用户、每会话、总量）
- ✅ 延迟指标（平均值、最小值、最大值）
- ✅ 会话指标（创建、删除、活跃、过期）
- ✅ 摘要指标（摘要次数、压缩比）
- ✅ 时间序列快照
- ✅ Redis 持久化

**使用示例**：
```python
from metagpt.management import MetricsCollector, LatencyTracker

collector = MetricsCollector(config, snapshot_interval=300)  # 每 5 分钟快照

# 记录压缩事件
collector.record_compression(original_tokens=1000, compressed_tokens=500)

# 记录缓存命中/未命中
collector.record_cache_hit(hit=True)   # 命中
collector.record_cache_hit(hit=False)  # 未命中

# 记录 token 使用
collector.record_token_usage("user123", tokens=250, session_id="sess_456")

# 记录延迟（手动）
collector.record_latency(latency_ms=150.5)

# 记录延迟（自动）
with LatencyTracker(collector):
    # 执行一些操作
    await llm.acompletion(...)
    # 延迟自动记录

# 记录会话事件
collector.record_session_created()
collector.record_session_deleted(expired=True)

# 记录摘要事件
collector.record_summary(original_messages=50, summary_tokens=200)

# 获取指标摘要
summary = collector.get_summary()
print(f"压缩率: {summary['compression']['average_ratio']}")
print(f"缓存命中率: {summary['cache']['hit_rate']}")
print(f"平均延迟: {summary['latency']['average_ms']} ms")
print(f"总 tokens: {summary['tokens']['total']}")

# 获取用户指标
user_metrics = collector.get_user_metrics("user123")
print(f"用户 token 使用: {user_metrics['tokens_used']}")

# 获取时间序列快照
snapshots = collector.get_snapshots(count=10)
```

**指标摘要示例**：
```json
{
    "timestamp": "2025-11-16T10:30:00",
    "compression": {
        "total_compressions": 150,
        "average_ratio": "45.20%",
        "tokens_saved": 45000
    },
    "cache": {
        "hits": 850,
        "misses": 150,
        "hit_rate": "85.00%"
    },
    "tokens": {
        "total": 1250000,
        "requests": 5000,
        "average_per_request": "250.00",
        "top_users": [
            {"user_id": "user123", "tokens": 50000},
            {"user_id": "user456", "tokens": 35000}
        ]
    },
    "latency": {
        "average_ms": "145.50",
        "min_ms": "50.20",
        "max_ms": "850.00",
        "total_requests": 5000
    },
    "sessions": {
        "created": 500,
        "deleted": 450,
        "active": 50,
        "expired": 100
    }
}
```

### 4. 优雅降级策略 (DegradationStrategy)

当上下文超过限制时，自动应用降级策略而不是简单拒绝。

**降级层级**：

| 级别 | 名称 | 策略 | 适用场景 |
|------|------|------|----------|
| 0 | NONE | 无需降级 | 上下文在限制内 |
| 1 | COMPRESS | 消息压缩 | 轻度超限 |
| 2 | SUMMARIZE | 历史摘要 | 中度超限 |
| 3 | TRUNCATE | 激进截断 | 重度超限 |
| 4 | REJECT | 拒绝请求 | 无法处理 |

**使用示例**：
```python
from metagpt.management import DegradationStrategy, ContextOverflowError

strategy = DegradationStrategy(
    llm=llm,
    max_tokens=8000,
    threshold=0.8,           # 80% 用于输入，20% 用于输出
    min_messages=3,          # 截断时至少保留 3 条消息
    summarize_max_words=200  # 摘要最多 200 词
)

try:
    # 自动处理上下文溢出
    processed_messages = await strategy.handle_overflow(
        messages=all_messages,
        brain_memory=brain_memory
    )

    # 使用处理后的消息调用 LLM
    response = await llm.aask(processed_messages)

except ContextOverflowError as e:
    # 即使降级也无法处理，需要开始新会话
    print(f"上下文过大: {e}")
    print("请开始新的对话")
```

**自适应降级策略**：
```python
from metagpt.management import AdaptiveDegradationStrategy

# 自适应策略会学习降级模式并提供建议
adaptive_strategy = AdaptiveDegradationStrategy(
    llm=llm,
    max_tokens=8000,
    threshold=0.8
)

# 使用方式相同
processed = await adaptive_strategy.handle_overflow(messages, brain_memory)

# 获取降级统计
stats = adaptive_strategy.get_degradation_stats()
print(f"总降级次数: {stats['total']}")
print(f"降级率: {stats['degradation_rate']:.2%}")
print(f"按级别统计: {stats['by_level']}")
```

**降级策略详解**：

**Level 1 - 压缩 (COMPRESS)**：
- 应用 `POST_CUT_BY_TOKEN` 压缩
- 保留最新的消息
- 系统消息始终保留
- 适合轻度超限（10-30% 超限）

**Level 2 - 摘要 (SUMMARIZE)**：
- 将较早的消息摘要为简洁文本
- 保留最近的 N 条消息（完整）
- 摘要插入为系统消息
- 适合中度超限（30-60% 超限）

**Level 3 - 截断 (TRUNCATE)**：
- 仅保留系统消息和最近 N 条消息
- 丢弃所有中间历史
- 最激进的策略
- 适合重度超限（60%+ 超限）

**Level 4 - 拒绝 (REJECT)**：
- 抛出 `ContextOverflowError`
- 无法在限制内处理
- 建议用户开始新会话

## 完整使用示例

### 生产环境部署示例

```python
from metagpt.config2 import Config
from metagpt.configs.llm_config import LLMConfig
from metagpt.configs.redis_config import RedisConfig
from metagpt.configs.compress_msg_config import CompressType
from metagpt.management import (
    SessionManager,
    QuotaManager,
    QuotaConfig,
    QuotaPeriod,
    MetricsCollector,
    AdaptiveDegradationStrategy,
)
from metagpt.memory.brain_memory import BrainMemory
from metagpt.provider.openai_api import OpenAILLM

# 1. 配置
config = Config(
    llm=LLMConfig(
        model="gpt-4-turbo-preview",
        compress_type=CompressType.POST_CUT_BY_TOKEN,
        max_token=8000,
        context_length=128000
    ),
    redis=RedisConfig(
        host="localhost",
        port=6379,
        password="your_password",
        db="0"
    )
)

# 2. 初始化管理器
session_manager = SessionManager(config)
quota_manager = QuotaManager(
    config,
    default_quota=QuotaConfig(
        max_tokens_per_period=100000,
        max_requests_per_period=1000,
        max_concurrent_sessions=10,
        period=QuotaPeriod.DAILY
    )
)
metrics_collector = MetricsCollector(config, snapshot_interval=300)
llm = OpenAILLM(config.llm)

# 3. 创建会话
session = await session_manager.create_session(
    user_id="user123",
    ttl=3600,
    metadata={"platform": "web"}
)

# 4. 处理用户消息
async def handle_message(session_id: str, user_message: str) -> str:
    # 获取会话
    session = await session_manager.get_session(session_id)
    if not session:
        raise ValueError("Session not found")

    # 检查配额
    try:
        await quota_manager.check_and_consume(
            user_id=session.user_id,
            tokens=1000,  # 估算
            requests=1
        )
    except QuotaExceeded as e:
        return f"配额已用尽: {e}"

    # 加载内存
    brain_memory = await session_manager.get_memory(session_id)
    if not brain_memory:
        brain_memory = BrainMemory(config=config)

    # 添加用户消息
    from metagpt.schema import Message
    brain_memory.history.append(Message(role="user", content=user_message))

    # 应用降级策略
    degradation = AdaptiveDegradationStrategy(
        llm=llm,
        max_tokens=8000,
        threshold=0.8
    )

    messages = await degradation.handle_overflow(
        brain_memory.history,
        brain_memory
    )

    # 调用 LLM
    response = await llm.aask(user_message)

    # 保存响应
    brain_memory.history.append(Message(role="assistant", content=response))
    await session_manager.save_memory(session_id, brain_memory)

    # 记录指标
    metrics_collector.record_token_usage(
        session.user_id,
        tokens=1000,
        session_id=session_id
    )

    return response

# 5. 监控和分析
summary = metrics_collector.get_summary()
print(f"系统指标: {summary}")

quota_status = await quota_manager.get_remaining_quota("user123")
print(f"用户配额: {quota_status}")

# 6. 清理
await session_manager.delete_session(session.session_id)
```

## 配置建议

### 不同规模的推荐配置

**小型应用（< 100 用户）**：
```python
QuotaConfig(
    max_tokens_per_period=50000,
    max_requests_per_period=500,
    max_concurrent_sessions=5,
    max_context_tokens=8000,
    period=QuotaPeriod.DAILY
)
```

**中型应用（100-1000 用户）**：
```python
QuotaConfig(
    max_tokens_per_period=100000,
    max_requests_per_period=1000,
    max_concurrent_sessions=10,
    max_context_tokens=8000,
    period=QuotaPeriod.DAILY
)
```

**大型应用（> 1000 用户）**：
```python
QuotaConfig(
    max_tokens_per_period=200000,
    max_requests_per_period=2000,
    max_concurrent_sessions=20,
    max_context_tokens=16000,
    period=QuotaPeriod.DAILY
)
```

### Redis 配置建议

```yaml
# config.yaml
redis:
  host: "localhost"
  port: 6379
  password: "strong_password"
  db: "0"

  # 连接池配置（如果 Redis 类支持）
  max_connections: 50
  timeout: 5
```

### 监控配置建议

```python
# 开发环境：更频繁的快照
MetricsCollector(config, snapshot_interval=60)  # 1 分钟

# 生产环境：适中的快照频率
MetricsCollector(config, snapshot_interval=300)  # 5 分钟

# 高流量环境：较长的快照间隔
MetricsCollector(config, snapshot_interval=600)  # 10 分钟
```

## 最佳实践

### 1. 会话管理

✅ **推荐**：
- 为不同类型的会话设置不同的 TTL
- 定期清理过期会话
- 在会话元数据中记录重要信息（来源、平台等）

❌ **避免**：
- TTL 设置过长（浪费内存）
- TTL 设置过短（用户体验差）
- 不清理过期会话

### 2. 配额管理

✅ **推荐**：
- 根据用户等级设置不同配额
- 监控配额使用趋势
- 在接近限制时提前警告用户
- 使用合适的配额周期

❌ **避免**：
- 配额设置过低（影响用户体验）
- 配额设置过高（成本失控）
- 忽略异常使用模式

### 3. 监控指标

✅ **推荐**：
- 定期导出指标到外部系统（Prometheus、Grafana）
- 设置关键指标告警
- 分析用户使用模式
- 追踪性能趋势

❌ **避免**：
- 快照间隔过短（性能影响）
- 不持久化指标数据
- 忽略异常指标

### 4. 优雅降级

✅ **推荐**：
- 使用自适应降级策略
- 记录降级事件用于分析
- 在频繁降级时建议用户开始新会话
- 根据用户类型调整降级阈值

❌ **避免**：
- 降级阈值设置过低（过早降级）
- 降级阈值设置过高（容易拒绝）
- 不通知用户降级发生

## 故障排查

### 会话找不到

**问题**：`get_session` 返回 `None`

**可能原因**：
1. 会话已过期（TTL）
2. Redis 连接问题
3. Session ID 错误

**解决方案**：
```python
session = await session_manager.get_session(session_id)
if not session:
    # 检查是否过期
    logger.warning(f"Session {session_id} not found, may be expired")
    # 创建新会话
    session = await session_manager.create_session(user_id)
```

### 配额总是超限

**问题**：频繁遇到 `QuotaExceeded`

**可能原因**：
1. 配额设置过低
2. Token 估算不准确
3. 用户使用异常

**解决方案**：
```python
# 1. 检查当前配额
quota_status = await quota_manager.get_remaining_quota(user_id)
logger.info(f"Quota status: {quota_status}")

# 2. 调整配额
if user_is_premium:
    quota_manager.set_user_quota(user_id, premium_quota)

# 3. 重置配额（如果是误判）
await quota_manager.reset_quota(user_id)
```

### 指标不更新

**问题**：`get_summary()` 显示的指标不变

**可能原因**：
1. 没有调用 `record_*` 方法
2. Redis 持久化失败

**解决方案**：
```python
# 确保记录事件
collector.record_token_usage(user_id, tokens)

# 手动触发持久化
await collector.persist()

# 从 Redis 加载
await collector.load()
```

### 降级策略不生效

**问题**：仍然遇到 `ContextOverflowError`

**可能原因**：
1. 单条消息太长
2. min_messages 设置过大
3. 真的无法在限制内处理

**解决方案**：
```python
# 1. 降低 min_messages
strategy = DegradationStrategy(
    llm=llm,
    max_tokens=8000,
    min_messages=1  # 最少保留 1 条
)

# 2. 检查降级级别
level = strategy.get_current_level(messages)
logger.info(f"Current degradation level: {level.name}")

# 3. 估算降级后的大小
estimated = strategy.estimate_tokens_after_degradation(
    messages,
    DegradationLevel.TRUNCATE
)
logger.info(f"Estimated tokens after truncation: {estimated}")
```

## 性能优化建议

### 1. Redis 优化

- 使用 Redis 集群提高可用性
- 配置合适的内存淘汰策略
- 开启 AOF 持久化
- 使用 Redis 连接池

### 2. 并发优化

```python
# 使用 asyncio.gather 并发处理多个会话
sessions = await asyncio.gather(
    session_manager.get_session(id1),
    session_manager.get_session(id2),
    session_manager.get_session(id3),
)
```

### 3. 缓存优化

```python
# 在应用层缓存频繁访问的配额信息
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_cached_quota(user_id: str) -> QuotaConfig:
    return quota_manager.get_user_quota(user_id)
```

## 总结

通过这套完整的多用户上下文管理功能，MetaGPT 现在具备了：

1. ✅ **完善的隔离**：基于会话的用户隔离
2. ✅ **资源控制**：灵活的配额管理
3. ✅ **可观测性**：全面的监控指标
4. ✅ **稳定性**：优雅的降级策略

这些功能使 MetaGPT 能够在生产环境中稳定运行，支持大规模多用户场景。

## 参考资料

- [用户上下文隔离分析文档](./user_context_isolation_analysis.md)
- [完整使用示例](../examples/multi_user_context_management.py)
- [API 文档](../metagpt/management/)
