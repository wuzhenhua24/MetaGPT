# MetaGPT 用户上下文隔离与长度管理分析

## 概述

本文档详细分析 MetaGPT 项目如何在多用户场景下保证：
1. **用户上下文隔离**：确保不同用户的会话数据不互相污染
2. **上下文长度管理**：防止单个用户的上下文超过模型窗口限制

## 1. 多用户上下文隔离机制

### 1.1 基于 Redis 的会话隔离

MetaGPT 通过 **BrainMemory** 类实现用户级别的上下文隔离。

**实现位置**: `metagpt/memory/brain_memory.py:197-199`

```python
@staticmethod
def to_redis_key(prefix: str, user_id: str, chat_id: str):
    return f"{prefix}:{user_id}:{chat_id}"
```

**核心特性**:
- 使用 `{prefix}:{user_id}:{chat_id}` 格式作为 Redis key
- 实现用户级和会话级的双层隔离
- 支持同一用户的多个并发会话

**使用示例**:
```python
# 为不同用户创建完全隔离的会话
redis_key = BrainMemory.to_redis_key("metagpt", user_id="user123", chat_id="chat456")
brain_memory = BrainMemory(config=config)
await brain_memory.loads(redis_key)  # 加载特定用户的上下文
```

### 1.2 角色级别的私有上下文

每个 Role 实例拥有独立的上下文环境，避免角色间的数据污染。

**实现位置**: `metagpt/context_mixin.py`

**核心组件**:
- `private_context` - 角色的私有上下文
- `private_config` - 角色的私有配置
- `private_llm` - 角色的私有 LLM 实例

**RoleContext 结构** (`metagpt/roles/role.py`):
```python
class RoleContext(BaseModel):
    msg_buffer: MessageQueue    # 独立的异步消息队列
    memory: Memory              # 独立的短期记忆
    working_memory: Memory      # 独立的工作记忆

    @property
    def history(self) -> list[Message]:
        return self.memory.get()
```

### 1.3 存储层隔离策略

MetaGPT 在多个存储层实现了隔离：

| 存储类型 | 隔离策略 | 实现位置 |
|---------|---------|---------|
| **Redis** | `user_id:chat_id` 作为 key | `metagpt/memory/brain_memory.py` |
| **本地文件** | `role_mem/{role_id}/` 目录隔离 | `metagpt/memory/memory_storage.py` |
| **向量数据库** | 按 `role_id` 分别存储 FAISS 索引 | `metagpt/memory/longterm_memory.py` |

**持久化机制** (`metagpt/memory/brain_memory.py`):
```python
async def loads(self, redis_key: str) -> "BrainMemory":
    """从 Redis 加载特定用户/会话的内存"""
    redis = Redis(self.config.redis)
    v = await redis.get(key=redis_key)
    # ...

async def dumps(self, redis_key: str, timeout_sec: int = 30 * 60):
    """保存到 Redis，默认 30 分钟过期"""
    redis = Redis(self.config.redis)
    await redis.set(key=redis_key, data=v, timeout_sec=timeout_sec)
```

## 2. 单用户上下文长度管理

### 2.1 消息压缩策略

MetaGPT 提供了 **5 种压缩策略**，应对不同的上下文管理需求。

**实现位置**: `metagpt/configs/compress_msg_config.py`

```python
class CompressType(Enum):
    NO_COMPRESS = ""                        # 不压缩（适合短会话）
    POST_CUT_BY_MSG = "post_cut_by_msg"     # 保留最新 N 条消息
    POST_CUT_BY_TOKEN = "post_cut_by_token" # 按 token 截断，保留最新
    PRE_CUT_BY_MSG = "pre_cut_by_msg"       # 保留最早 N 条消息
    PRE_CUT_BY_TOKEN = "pre_cut_by_token"   # 按 token 截断，保留最早
```

**策略选择指南**:
- `POST_CUT_BY_TOKEN`: 适合对话场景，保留最近的上下文
- `PRE_CUT_BY_MSG`: 适合需要保留初始指令的场景
- `POST_CUT_BY_MSG`: 简单快速，适合消息数量限制

### 2.2 自动 Token 管理

**实现位置**: `metagpt/provider/base_llm.py`

```python
def compress_messages(
    self,
    messages: list[dict],
    compress_type: CompressType = CompressType.NO_COMPRESS,
    max_token: int = 128000,
    threshold: float = 0.8,  # 保留 80% 用于输入，20% 用于输出
) -> list[dict]:
    """压缩消息以适应 token 限制

    工作流程：
    1. 系统消息（system）始终保留
    2. 计算当前消息的总 token 数
    3. 根据 threshold 计算可用的输入 token 限制
    4. 根据 compress_type 策略截断用户/助手消息
    5. 返回压缩后的消息列表
    """
```

**关键参数说明**:
- `max_token`: 模型的最大上下文长度
- `threshold`: token 限制阈值，默认 0.8
  - 保留 80% 的 token 用于输入（历史对话）
  - 预留 20% 的 token 用于输出（生成回复）

### 2.3 历史摘要机制

**BrainMemory** 提供自动摘要功能，将长历史记录压缩为简洁的摘要。

**实现位置**: `metagpt/memory/brain_memory.py:96-121`

```python
async def summarize(self, llm, max_words=200):
    """将长历史记录压缩为摘要

    特性：
    - 使用滑动窗口处理超长文本（避免单次超过模型限制）
    - 支持递归摘要（多轮压缩）
    - 自动更新 historical_summary 字段
    - 保留关键信息，丢弃冗余细节
    """

@staticmethod
def split_texts(text: str, window_size):
    """将长文本分割为滑动窗口

    参数：
    - window_size: 窗口大小（token 数）
    - padding_size: 窗口重叠大小（默认 20）
    """
```

**使用场景**:
```python
# 当历史记录过长时，自动触发摘要
brain_memory = BrainMemory(config=config)
brain_memory.history = long_history_messages
await brain_memory.summarize(llm, max_words=300)
# 之后使用 brain_memory.historical_summary 代替完整历史
```

### 2.4 Token 计数器

**实现位置**: `metagpt/utils/token_counter.py`

MetaGPT 内置了精确的 token 计数工具，支持多种主流模型。

```python
# 各模型的最大 token 限制
TOKEN_MAX = {
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    "gpt-4-turbo-preview": 128000,
    "gpt-3.5-turbo": 4096,
    "gpt-3.5-turbo-16k": 16384,
    "claude-2": 100000,
    "claude-instant-1": 100000,
    # ...
}

def count_message_tokens(messages, model="gpt-3.5-turbo"):
    """计算消息列表的 token 数

    使用 tiktoken 库进行精确计数
    支持不同模型的 token 编码方式
    """

def get_max_completion_tokens(messages, model, default):
    """计算最大可用 completion tokens

    返回：max_token - 输入 token 数
    """
```

## 3. 内存和消息管理

### 3.1 短期记忆管理

**Memory 类** (`metagpt/memory/memory.py`)

```python
class Memory(BaseModel):
    storage: list[Message] = []                        # 消息存储
    index: DefaultDict[str, list[Message]]             # 按 cause_by 索引

    def add(self, message: Message):                   # 添加消息
        """添加新消息到存储和索引"""

    def get(self, k=0) -> list[Message]:               # 获取最近 k 条
        """k=0 返回全部，k>0 返回最新 k 条"""

    def get_by_role(self, role: str):                  # 按角色筛选
        """获取特定角色发送的消息"""

    def get_by_action(self, action):                   # 按 action 筛选
        """获取由特定 action 触发的消息"""

    def delete_newest(self):                           # 删除最新消息
        """删除最后添加的消息"""

    def clear(self):                                   # 清空记忆
        """清空所有存储和索引"""
```

### 3.2 长期记忆管理

**LongTermMemory 类** (`metagpt/memory/longterm_memory.py`)

```python
class LongTermMemory(Memory):
    memory_storage: MemoryStorage  # 持久化存储（FAISS 向量数据库）

    def recover_memory(self, role_id: str, rc: RoleContext):
        """从存储中恢复记忆

        工作流程：
        1. 从磁盘加载 FAISS 索引
        2. 恢复历史消息到 memory
        3. 更新 RoleContext
        """

    async def find_news(self, observed: list[Message], k=0):
        """过滤已见过的消息

        基于向量相似度判断消息是否为新消息
        threshold=0.1（高度相似视为重复）
        """
```

**MemoryStorage** (`metagpt/memory/memory_storage.py`):
- 使用 **FAISS** 作为向量数据库
- 支持语义相似度搜索
- 按 `role_id` 隔离存储路径：`DATA_PATH/role_mem/{role_id}/`

```python
class MemoryStorage:
    def recover_memory(self, role_id: str):
        """从磁盘恢复记忆"""
        self.role_mem_path = Path(DATA_PATH / f"role_mem/{self.role_id}/")
        # 加载 FAISS 索引和消息

    async def search_similar(self, message: Message, k=4):
        """搜索相似消息

        参数：
        - k: 返回最相似的 k 条消息
        - threshold: 相似度阈值（默认 0.1）
        """
```

### 3.3 BrainMemory - 高级记忆管理

**实现位置**: `metagpt/memory/brain_memory.py`

专为 AgentStore 设计的高级记忆管理系统。

```python
class BrainMemory(BaseModel):
    history: List[Message]          # 对话历史
    knowledge: List[Message]        # 知识库
    historical_summary: str         # 历史摘要

    async def is_history_available(self, llm, context_window_pct=0.6):
        """检查历史记录是否超过上下文窗口

        返回：
        - True: 历史未超限，可直接使用
        - False: 历史超限，需要压缩或摘要
        """

    async def summarize(self, llm, max_words=200):
        """自动摘要历史记录

        触发时机：
        - 历史 token > context_window * 0.6
        - 手动调用
        """
```

### 3.4 消息队列和路由

**MessageQueue** (`metagpt/schema.py`)

```python
class MessageQueue(BaseModel):
    _queue: Queue = PrivateAttr(default_factory=Queue)

    def push(self, msg: Message):              # 推送消息
    def pop(self) -> Optional[Message]:        # 弹出消息（FIFO）
    def pop_all(self) -> List[Message]:        # 弹出所有消息
    def empty(self) -> bool:                   # 检查队列是否为空
```

**消息路由常量** (`metagpt/const.py`):
```python
MESSAGE_ROUTE_FROM = "sent_from"      # 消息来源
MESSAGE_ROUTE_TO = "send_to"          # 消息目标
MESSAGE_ROUTE_CAUSE_BY = "cause_by"   # 触发原因
MESSAGE_ROUTE_TO_ALL = "<all>"        # 广播给所有角色
MESSAGE_ROUTE_TO_SELF = "<self>"      # 发给自己
```

## 4. 配置与使用

### 4.1 LLM 配置

**配置文件**: `metagpt/configs/llm_config.py`

```python
class LLMConfig(YamlModel):
    api_key: str                                       # API 密钥
    model: str = "gpt-4"                               # 模型名称
    max_token: int = 4096                              # 最大 token
    context_length: Optional[int] = None               # 最大输入 tokens
    compress_type: CompressType = CompressType.NO_COMPRESS  # 压缩策略
    temperature: float = 0.7                           # 生成温度
```

### 4.2 Redis 配置

**配置文件**: `metagpt/configs/redis_config.py`

```python
class RedisConfig(YamlModelWithoutDefault):
    host: str = "localhost"        # Redis 主机
    port: int = 6379               # Redis 端口
    username: str = ""             # 用户名（可选）
    password: str                  # 密码
    db: str = "0"                  # 数据库编号
```

### 4.3 完整使用示例

```python
from metagpt.config2 import Config
from metagpt.memory.brain_memory import BrainMemory
from metagpt.configs.llm_config import LLMConfig, CompressType
from metagpt.configs.redis_config import RedisConfig

# 1. 配置 LLM 压缩策略
llm_config = LLMConfig(
    model="gpt-4-turbo-preview",
    compress_type=CompressType.POST_CUT_BY_TOKEN,  # 保留最新消息
    max_token=8000,                                 # 最大输入 token
    context_length=128000                           # 模型上下文长度
)

# 2. 配置 Redis 持久化
redis_config = RedisConfig(
    host="localhost",
    port=6379,
    password="your_password",
    db="0"
)

# 3. 创建配置对象
config = Config(llm=llm_config, redis=redis_config)

# 4. 为每个用户创建隔离会话
async def create_user_session(user_id: str, chat_id: str):
    # 生成唯一的 Redis key
    redis_key = BrainMemory.to_redis_key("metagpt", user_id, chat_id)

    # 创建或加载 BrainMemory
    brain_memory = BrainMemory(config=config)

    # 尝试加载历史记录（如果存在）
    try:
        await brain_memory.loads(redis_key)
        print(f"已加载用户 {user_id} 的会话 {chat_id}")
    except Exception:
        print(f"创建新会话：{user_id}/{chat_id}")

    # ... 使用 brain_memory 进行对话 ...

    # 对话结束后保存，30 分钟 TTL
    await brain_memory.dumps(redis_key, timeout_sec=1800)

    return brain_memory

# 5. 使用示例
async def main():
    # 用户 A 的会话
    session_a = await create_user_session("user_alice", "chat_001")

    # 用户 B 的会话（完全隔离）
    session_b = await create_user_session("user_bob", "chat_002")

    # 检查是否需要摘要
    from metagpt.provider.openai_api import OpenAILLM
    llm = OpenAILLM(config.llm)

    if not await session_a.is_history_available(llm):
        print("历史过长，进行摘要...")
        await session_a.summarize(llm, max_words=300)
```

## 5. 架构评估

### 5.1 优势

| 特性 | 说明 |
|------|------|
| ✅ **完善的隔离** | user_id + chat_id 双层隔离，确保会话独立 |
| ✅ **灵活的压缩** | 5 种策略适应不同场景需求 |
| ✅ **自动管理** | token 计数和压缩自动进行，开发者无需手动干预 |
| ✅ **多层记忆** | 短期 + 长期 + 向量检索，满足不同时间跨度的需求 |
| ✅ **精确计数** | 基于 tiktoken 的精确 token 计数 |
| ✅ **持久化** | Redis + 本地文件双重持久化 |

### 5.2 局限性

| 问题 | 影响 | 优先级 |
|------|------|--------|
| ⚠️ **缺少会话管理器** | 需要手动构建 Redis key，容易出错 | 高 |
| ⚠️ **无全局配额管理** | 没有跨用户的资源限制，可能被滥用 | 高 |
| ⚠️ **TTL 固定** | Redis 默认 30 分钟，不够灵活 | 中 |
| ⚠️ **缺少监控** | 没有指标收集，难以追踪性能和资源使用 | 中 |
| ⚠️ **无降级策略** | 上下文超限时缺少明确的处理流程 | 中 |

## 6. 生产环境建议

### 6.1 添加会话管理层

**目标**：统一管理 user_id/chat_id 映射，避免手动构建 Redis key

**建议实现**：
```python
class SessionManager:
    def create_session(self, user_id: str, chat_id: str = None) -> Session
    def get_session(self, session_id: str) -> Session
    def delete_session(self, session_id: str)
    def list_user_sessions(self, user_id: str) -> List[Session]
    def set_ttl(self, session_id: str, ttl: int)
```

### 6.2 实现配额系统

**目标**：限制每个用户的资源使用，防止滥用

**建议实现**：
```python
class QuotaManager:
    def check_quota(self, user_id: str, tokens: int) -> bool
    def consume_quota(self, user_id: str, tokens: int)
    def get_remaining_quota(self, user_id: str) -> int
    def reset_quota(self, user_id: str, period: str = "daily")

# 配置示例
quota_config = {
    "daily_tokens": 100000,      # 每日 token 限额
    "max_sessions": 10,          # 最大并发会话数
    "max_history_length": 50,    # 最大历史消息数
}
```

### 6.3 监控指标

**目标**：跟踪系统性能和资源使用

**关键指标**：
- 压缩率：`(原始 token - 压缩后 token) / 原始 token`
- 内存使用：每个会话的内存占用
- Redis 命中率：缓存命中 vs 缓存未命中
- Token 消耗：每个用户/会话的 token 使用量
- 摘要触发次数：历史摘要的频率

**建议实现**：
```python
class MetricsCollector:
    def record_compression(self, original: int, compressed: int)
    def record_token_usage(self, user_id: str, tokens: int)
    def record_cache_hit(self, hit: bool)
    def get_metrics_summary(self) -> dict
```

### 6.4 优雅降级

**目标**：当上下文超限时提供明确的处理策略

**降级策略**：
1. **Level 1**: 自动压缩（POST_CUT_BY_TOKEN）
2. **Level 2**: 历史摘要（summarize）
3. **Level 3**: 仅保留系统消息 + 最新 N 条
4. **Level 4**: 拒绝请求，提示用户开始新会话

**建议实现**：
```python
class GracefulDegradation:
    async def handle_context_overflow(
        self,
        messages: List[Message],
        max_token: int
    ) -> List[Message]:
        # 依次尝试降级策略
        if self.can_compress(messages, max_token):
            return self.compress(messages, max_token)
        elif self.can_summarize(messages, max_token):
            return await self.summarize(messages, max_token)
        elif self.can_truncate(messages, max_token):
            return self.truncate(messages, max_token)
        else:
            raise ContextOverflowError("无法在限制内处理，请开始新会话")
```

## 7. 总结

MetaGPT 已经具备了生产级多用户场景的**基础能力**：

✅ **已实现**：
- 基于 Redis 的会话隔离
- 5 种消息压缩策略
- 自动 token 计数和管理
- 历史摘要机制
- 多层记忆系统（短期/长期/向量）

⚠️ **待增强**（生产环境必需）：
- 统一的会话管理层
- 全局配额和限流系统
- 监控和指标收集
- 优雅降级策略
- 灵活的 TTL 配置

**建议**：在生产环境部署前，优先实现会话管理层和配额系统，以确保系统的稳定性和安全性。

---

**文档版本**: 1.0
**最后更新**: 2025-11-16
**分析范围**: MetaGPT 主分支最新代码
