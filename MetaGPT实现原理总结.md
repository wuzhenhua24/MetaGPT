# MetaGPT 实现原理深度解析

> **文档目的**：全面解析MetaGPT多智能体框架的核心架构、设计理念和实现原理

---

## 一、项目概述

### 1.1 项目简介

**MetaGPT** 是一个革命性的多智能体框架，其核心理念是"将一个软件公司抽象为由LLM驱动的多智能体系统"。

- **核心哲学**：`Code = SOP(Team)` - 将标准操作流程（SOP）物化并应用于LLM团队
- **版本**：v1.0.0
- **开源协议**：MIT License
- **Python要求**：>= 3.9, < 3.12

### 1.2 核心特性

1. **一行需求到完整项目**：输入一个需求，输出用户故事、竞品分析、需求文档、数据结构、API设计、完整代码等
2. **完整的角色生态**：产品经理、架构师、项目经理、工程师等
3. **标准化工作流程**：模拟真实软件公司的SOP
4. **灵活的智能体框架**：支持自定义角色和动作

### 1.3 技术栈

**核心依赖**：
- **LLM支持**：OpenAI GPT、Azure OpenAI、Ollama、Groq等
- **异步框架**：asyncio（Python原生异步）
- **数据建模**：Pydantic（数据验证和序列化）
- **可视化**：Mermaid（流程图和类图）
- **RAG支持**：LlamaIndex、FAISS、ChromaDB等
- **Node.js工具**：Mermaid CLI

---

## 二、核心架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                         User Input                          │
│                    "创建一个2048游戏"                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Team (团队)                            │
│  ┌────────────────────────────────────────────────────┐    │
│  │          Environment (环境/消息总线)                │    │
│  │                                                     │    │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐          │    │
│  │  │  Role1  │  │  Role2   │  │  Role3   │  ...     │    │
│  │  │  (PM)   │  │(Architect)│ │(Engineer)│          │    │
│  │  └────┬────┘  └────┬─────┘  └────┬─────┘          │    │
│  │       │            │             │                 │    │
│  │  ┌────▼────────────▼─────────────▼─────┐          │    │
│  │  │         Message Queue (消息队列)     │          │    │
│  │  └──────────────────────────────────────┘          │    │
│  │                                                     │    │
│  │  ┌──────────────────────────────────────┐          │    │
│  │  │      Memory (历史记录/上下文)        │          │    │
│  │  └──────────────────────────────────────┘          │    │
│  └────────────────────────────────────────────────────┘    │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   ProjectRepo (项目仓库)                    │
│        PRD / 设计文档 / 代码 / 测试 / 文档 ...              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心模块组成

```
metagpt/
├── schema.py              # 核心数据结构（Message, Task, Role等）
├── team.py                # 团队管理
├── environment/           # 环境系统
│   ├── base_env.py       # 基础环境（消息总线）
│   └── mgx_env.py        # MGX增强环境
├── roles/                 # 角色定义
│   ├── role.py           # Role基类
│   ├── product_manager.py # 产品经理
│   ├── architect.py      # 架构师
│   ├── engineer.py       # 工程师
│   └── ...
├── actions/              # 动作定义
│   ├── action.py         # Action基类
│   ├── write_prd.py      # 写PRD
│   ├── write_design.py   # 写设计
│   ├── write_code.py     # 写代码
│   └── ...
├── memory/               # 记忆系统
│   ├── memory.py         # 基础记忆
│   └── longterm_memory.py # 长期记忆
├── provider/             # LLM提供者
│   ├── openai_api.py
│   ├── azure_gpt_api.py
│   └── ...
└── utils/                # 工具函数
```

---

## 三、核心概念详解

### 3.1 Message - 消息系统

**设计理念**：消息是智能体间通信的唯一方式，类似于Actor模型。

**核心结构**：
```python
class Message(BaseModel):
    id: str                           # 消息唯一标识（UUID）
    content: str                      # 自然语言内容
    instruct_content: Optional[BaseModel]  # 结构化内容（如PRD对象）
    role: str = "user"               # 角色类型
    cause_by: str                    # 触发此消息的Action类名
    sent_from: str                   # 发送者名称
    send_to: set[str]                # 接收者集合（支持广播）
    metadata: Dict[str, Any]         # 元数据（如时间戳等）
```

**消息路由机制**：
1. **cause_by路由**：角色通过`_watch([ActionType])`订阅特定类型的消息
2. **send_to路由**：显式指定接收者，支持点对点和广播
3. **双重内容模式**：
   - `content`：给LLM看的自然语言描述
   - `instruct_content`：给程序用的结构化数据

**示例**：
```python
# ProductManager发布PRD消息
msg = Message(
    content="产品需求文档已完成",
    instruct_content=PRD(...),      # 结构化的PRD对象
    cause_by="WritePRD",            # Architect会订阅此类型
    sent_from="Alice/ProductManager",
    send_to={"*"}                   # 广播给所有人
)
```

### 3.2 Role - 智能体角色

**设计理念**：每个Role代表一个智能体，拥有独立的目标、记忆和行动能力。

**核心属性**：
```python
class Role(BaseRole, SerializationMixin, ContextMixin):
    # 身份属性
    name: str                        # 角色实例名（如"Alice"）
    profile: str                     # 角色类型（如"ProductManager"）
    goal: str                        # 角色目标
    constraints: str                 # 约束条件

    # 能力属性
    actions: list[Action]            # 可执行的动作列表

    # 运行时上下文
    rc: RoleContext                  # 包含环境、记忆、状态等
```

**RoleContext - 运行时上下文**：
```python
class RoleContext(BaseModel):
    env: BaseEnvironment             # 所在环境（用于发布消息）
    msg_buffer: MessageQueue         # 个人消息缓冲区
    memory: Memory                   # 长期记忆
    working_memory: Memory           # 工作记忆（临时）
    state: int                       # 当前状态（对应actions索引）
    todo: Action                     # 当前待执行的动作
    watch: set[str]                  # 订阅的Action类型
    react_mode: RoleReactMode        # 反应模式
    max_react_loop: int = 1          # 最大思考-行动循环次数
```

**三种反应模式**：

#### 1. REACT模式 - 动态决策

适用于需要根据情况灵活决策的场景。

```python
async def _react(self) -> Message:
    """标准ReAct循环：观察 -> 思考 -> 行动 -> 观察 -> ..."""
    actions_taken = 0
    rsp = Message(content="")

    while actions_taken < self.rc.max_react_loop:
        # 思考：决定下一步做什么
        has_todo = await self._think()
        if not has_todo:
            break

        # 行动：执行选定的动作
        rsp = await self._act()
        actions_taken += 1

    return rsp
```

**工作流程**：
```
1. 观察环境（_observe）
2. 思考下一步（_think）- 使用LLM选择Action
3. 执行动作（_act）
4. 根据结果继续思考或结束
```

#### 2. BY_ORDER模式 - 顺序执行

适用于有明确工作流程的场景，按预定义顺序执行动作。

```python
async def _think(self) -> bool:
    """按顺序执行预定义的Action序列"""
    if self.rc.react_mode == RoleReactMode.BY_ORDER:
        # 简单递增state，执行下一个Action
        self._set_state(self.rc.state + 1)
        return self.rc.state >= 0 and self.rc.todo
    ...
```

**示例**：ProductManager
```python
class ProductManager(Role):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_actions([PrepareDocuments, WritePRD])  # 顺序执行
        self._set_react_mode(RoleReactMode.BY_ORDER)

# 执行顺序：
# 第1轮：PrepareDocuments（准备竞品分析等）
# 第2轮：WritePRD（写产品需求文档）
```

#### 3. PLAN_AND_ACT模式 - 先规划后执行

适用于复杂任务，先制定计划，再逐步执行。

```python
async def _plan_and_act(self) -> Message:
    """规划-执行循环"""
    # 如果没有计划，先制定计划
    if not self.planner.plan.goal:
        await self.planner.update_plan(goal=self.rc.memory.get()[-1].content)

    # 逐个执行计划中的任务
    while self.planner.current_task:
        task = self.planner.current_task

        # 执行任务
        task_result = await self._act_on_task(task)

        # 处理结果，更新计划
        await self.planner.process_task_result(task_result)

    return self.planner.get_useful_memories()[0]
```

**计划示例**：
```yaml
Goal: "创建一个2048游戏"
Tasks:
  - task_id: "1"
    instruction: "分析需求，编写PRD"
    assignee: "ProductManager"
    dependent_task_ids: []

  - task_id: "2"
    instruction: "设计系统架构"
    assignee: "Architect"
    dependent_task_ids: ["1"]  # 依赖任务1

  - task_id: "3"
    instruction: "实现游戏逻辑"
    assignee: "Engineer"
    dependent_task_ids: ["2"]  # 依赖任务2
```

### 3.3 核心工作流程：观察-思考-行动循环

```python
async def run(self, with_message=None) -> Message | None:
    """Role的主循环"""

    # 1. 观察阶段：从环境获取新消息
    if with_message:
        self.put_message(with_message)

    if not await self._observe():
        # 没有新消息，直接返回
        return

    # 2. 反应阶段：思考和行动
    rsp = await self.react()  # 根据react_mode调用不同的方法

    # 3. 发布阶段：将响应发布到环境
    self.publish_message(rsp)

    return rsp
```

**详细流程解析**：

#### 阶段1：观察（_observe）

```python
async def _observe(self, ignore_memory=False) -> int:
    """观察环境，获取新消息"""

    # 从消息缓冲区获取所有新消息
    news = self.rc.msg_buffer.pop_all()

    # 获取旧消息（避免重复处理）
    old_messages = [] if ignore_memory else self.rc.memory.get()

    # 过滤：只保留感兴趣的消息
    self.rc.news = [
        n for n in news
        if (
            # 条件1：消息是我订阅的Action类型
            n.cause_by in self.rc.watch or
            # 条件2：消息明确发给我的
            self.name in n.send_to
        ) and
        # 条件3：不是旧消息
        n not in old_messages
    ]

    # 新消息加入记忆
    if not ignore_memory:
        self.rc.memory.add_batch(self.rc.news)

    return len(self.rc.news)
```

#### 阶段2：思考（_think）

```python
async def _think(self) -> bool:
    """决定下一步做什么"""

    # 情况1：只有一个Action，直接执行
    if len(self.actions) == 1:
        self._set_state(0)
        return True

    # 情况2：BY_ORDER模式，按顺序执行
    if self.rc.react_mode == RoleReactMode.BY_ORDER:
        self._set_state(self.rc.state + 1)
        return self.rc.state >= 0 and self.rc.todo

    # 情况3：REACT模式，使用LLM选择
    prompt = self._get_state_prompt()  # 根据当前状态和记忆生成prompt
    next_state = await self.llm.aask(prompt)  # 询问LLM
    self._set_state(int(next_state))
    return True
```

**_set_state方法**：
```python
def _set_state(self, state: int):
    """设置当前状态，并更新todo"""
    self.rc.state = state
    if state < 0 or state >= len(self.actions):
        self.rc.todo = None
    else:
        self.rc.todo = self.actions[state]
```

#### 阶段3：行动（_act）

```python
async def _act(self) -> Message:
    """执行当前的todo动作"""

    # 获取相关消息作为上下文
    todo = self.rc.todo
    msg = self.rc.memory.get_by_action(todo)[-1] if self.rc.memory.get_by_action(todo) else None

    # 执行Action
    result = await todo.run(msg)

    # 更新记忆
    self.rc.memory.add(result)

    return result
```

### 3.4 Action - 动作执行

**设计理念**：Action是Role能力的具体实现，一个Action代表一个具体的任务。

**核心结构**：
```python
class Action(SerializationMixin, ContextMixin, BaseModel):
    name: str                        # 动作名称
    i_context: Union[str, Message, ...]  # 输入上下文
    prefix: str                      # 系统提示词前缀
    desc: str                        # 动作描述
    node: ActionNode                 # 结构化输出节点
    llm_name_or_type: Optional[str]  # LLM配置

    async def run(self, *args, **kwargs):
        """执行动作的主方法，子类需实现"""
        if self.node:
            # 使用ActionNode进行结构化输出
            return await self._run_action_node(*args, **kwargs)
        raise NotImplementedError
```

**ActionNode - 结构化输出**：

ActionNode是MetaGPT的核心创新之一，它将LLM的自然语言输出转换为结构化数据。

```python
# 定义数据结构
class PRD(BaseModel):
    title: str
    goals: List[str]
    user_stories: List[str]
    requirements: List[str]
    constraints: List[str]

# 创建ActionNode
prd_node = ActionNode.from_pydantic(PRD)

# 运行并获取结构化输出
result = await prd_node.fill(
    context="用户需求：创建一个2048游戏",
    llm=self.llm
)

# result.instruct_content 是 PRD 类型的对象
prd = result.instruct_content
print(prd.title)  # 直接访问结构化字段
```

**具体Action示例**：

#### WritePRD - 编写产品需求文档

```python
class WritePRD(Action):
    """产品经理编写PRD的动作"""

    async def run(self, with_messages: Message = None, **kwargs) -> Message:
        # 1. 获取用户需求或竞品分析
        docs = await self.repo.docs.prd.get_by_suffix(".md")
        requirement = with_messages.content

        # 2. 使用ActionNode生成结构化PRD
        node = await PRD_NODE.fill(
            context=requirement,
            llm=self.llm,
            schema="json"
        )

        # 3. 保存PRD文档
        await self.repo.docs.prd.save(
            filename="prd.md",
            content=node.instruct_content.model_dump_json()
        )

        # 4. 返回消息
        return Message(
            content="PRD文档已完成",
            instruct_content=node.instruct_content,
            cause_by=self
        )
```

#### WriteDesign - 编写系统设计

```python
class WriteDesign(Action):
    """架构师编写系统设计的动作"""

    async def run(self, with_messages: Message = None, **kwargs) -> Message:
        # 1. 读取PRD
        prd = await self.repo.docs.prd.get("prd.md")

        # 2. 生成系统设计
        system_design = await SYSTEM_DESIGN_NODE.fill(
            context=prd.content,
            llm=self.llm
        )

        # 3. 生成数据结构和API设计
        data_api_design = await DATA_API_DESIGN_NODE.fill(
            context=system_design.content,
            llm=self.llm
        )

        # 4. 生成流程图（使用Mermaid）
        seq_flow = await self._design_seq_flow(system_design.content)

        # 5. 保存所有设计文档
        await self.repo.docs.system_design.save(...)
        await self.repo.resources.data_api_design.save(...)
        await self.repo.resources.seq_flow.save(...)

        return Message(...)
```

#### WriteCode - 编写代码

```python
class WriteCode(Action):
    """工程师编写代码的动作"""

    async def run(self, with_messages: Message = None) -> Message:
        # 1. 读取设计文档
        design = await self.repo.docs.system_design.get_all()

        # 2. 获取文件列表
        code_plan_and_change = design.get("code_plan_and_change.md")

        # 3. 为每个文件生成代码
        for file_info in code_plan_and_change.files:
            code = await CODE_NODE.fill(
                context=f"设计：{design}\n文件：{file_info}",
                llm=self.llm
            )

            # 保存代码文件
            await self.repo.src_workspace.save(
                filename=file_info.filename,
                content=code.content
            )

        return Message(content="代码编写完成", cause_by=self)
```

### 3.5 Environment - 环境系统

**设计理念**：Environment是智能体生存的环境，负责消息路由和角色管理。

**核心职责**：
1. **消息总线**：接收和分发消息
2. **角色容器**：管理所有角色的生命周期
3. **历史记录**：保存所有交互历史
4. **并发执行**：协调多个角色的并发运行

**核心结构**：
```python
class Environment(ExtEnv):
    desc: str = "Environment"        # 环境描述
    roles: dict[str, BaseRole]       # 角色字典 {name: role}
    member_addrs: Dict[BaseRole, Set[str]]  # 角色地址映射
    history: Memory                  # 完整历史记录
    context: Context                 # 共享上下文

    def add_role(self, role: BaseRole):
        """添加角色到环境"""
        self.roles[role.name] = role
        role.set_env(self)

    def publish_message(self, message: Message) -> bool:
        """发布消息（消息总线核心）"""
        # 根据路由信息分发消息
        for role in self.roles.values():
            if self._is_send_to(message, role):
                role.put_message(message)  # 放入角色的消息缓冲区

        # 保存到历史
        self.history.add(message)
        return True

    async def run(self, k=1):
        """运行环境k轮"""
        for i in range(k):
            # 并发执行所有角色
            futures = []
            for role in self.roles.values():
                if not role.is_idle:
                    future = role.run()
                    futures.append(future)

            if futures:
                await asyncio.gather(*futures)

            # 检查是否所有角色都空闲
            if self.is_idle:
                break
```

**消息路由逻辑**：
```python
def _is_send_to(self, message: Message, role: BaseRole) -> bool:
    """判断消息是否应该发给某个角色"""
    # 情况1：广播消息
    if "*" in message.send_to:
        return True

    # 情况2：明确指定接收者
    if role.name in message.send_to:
        return True

    # 情况3：角色订阅了该Action类型
    if message.cause_by in role.rc.watch:
        return True

    return False
```

### 3.6 Memory - 记忆系统

**设计理念**：Memory是角色的记忆存储，支持按时间和类型检索。

**核心结构**：
```python
class Memory(BaseModel):
    storage: list[Message] = []      # 线性存储（保持时序）
    index: DefaultDict[str, list[Message]] = DefaultDict(list)  # 按Action类型索引

    def add(self, message: Message):
        """添加消息"""
        self.storage.append(message)
        if message.cause_by:
            self.index[message.cause_by].append(message)

    def get(self, k=0) -> list[Message]:
        """获取最近k条消息（k=0表示全部）"""
        return self.storage[-k:] if k else self.storage

    def get_by_action(self, action) -> list[Message]:
        """获取特定Action触发的所有消息"""
        return self.index[any_to_str(action)]

    def get_by_role(self, role: str) -> list[Message]:
        """获取特定角色发送的消息"""
        return [m for m in self.storage if m.sent_from == role]
```

**使用场景**：
```python
# 场景1：获取最近的PRD文档
prd_messages = role.rc.memory.get_by_action(WritePRD)
latest_prd = prd_messages[-1] if prd_messages else None

# 场景2：获取最近3条消息作为上下文
recent_context = role.rc.memory.get(3)

# 场景3：获取所有与产品经理的对话
pm_messages = role.rc.memory.get_by_role("Alice/ProductManager")
```

### 3.7 Team - 团队协作

**设计理念**：Team是最顶层的协调者，管理整个项目的执行。

**核心结构**：
```python
class Team(BaseModel):
    env: Optional[Environment] = None      # 环境
    investment: float = 10.0              # 预算（美元）
    idea: str = ""                        # 项目目标

    def hire(self, roles: list[Role]):
        """雇佣角色"""
        for role in roles:
            self.env.add_role(role)

    async def run(self, n_round=3, idea=""):
        """运行团队"""
        # 1. 初始化项目
        if idea:
            self.run_project(idea)

        # 2. 运行n轮
        for i in range(n_round):
            # 检查预算
            if self._check_balance() <= 0:
                raise ValueError("预算不足")

            # 运行环境
            await self.env.run()

            # 如果所有角色都空闲，提前结束
            if self.env.is_idle:
                break

        # 3. 返回历史记录
        return self.env.history

    def run_project(self, idea: str):
        """启动新项目"""
        # 发布初始需求消息
        self.env.publish_message(
            Message(
                content=idea,
                cause_by="UserRequirement",
                send_to={"*"}  # 广播给所有角色
            )
        )
```

---

## 四、完整工作流程示例

### 4.1 软件开发完整流程

**场景**：用户输入"创建一个2048游戏"

#### 步骤1：初始化团队

```python
from metagpt.team import Team
from metagpt.roles import ProductManager, Architect, Engineer

# 创建团队
team = Team()

# 雇佣角色
team.hire([
    ProductManager(name="Alice"),
    Architect(name="Bob"),
    Engineer(name="Charlie")
])

# 启动项目
await team.run(idea="创建一个2048游戏")
```

#### 步骤2：消息流转过程

```
时间轴 | 角色 | 动作 | 输入 | 输出
-------|------|------|------|------
T0 | User | - | "创建一个2048游戏" | Message(cause_by=UserRequirement)
T1 | Alice/PM | _observe | UserRequirement消息 | 检测到新消息
T2 | Alice/PM | _think | - | 决定执行WritePRD
T3 | Alice/PM | _act | 用户需求 | PRD文档
T4 | Alice/PM | publish | - | Message(cause_by=WritePRD)
T5 | Bob/Arch | _observe | WritePRD消息 | 检测到PRD
T6 | Bob/Arch | _think | - | 决定执行WriteDesign
T7 | Bob/Arch | _act | PRD | 系统设计文档
T8 | Bob/Arch | publish | - | Message(cause_by=WriteDesign)
T9 | Charlie/Eng | _observe | WriteDesign消息 | 检测到设计
T10 | Charlie/Eng | _think | - | 决定执行WriteCode
T11 | Charlie/Eng | _act | 设计文档 | 完整代码
T12 | Charlie/Eng | publish | - | Message(cause_by=WriteCode)
```

#### 步骤3：详细执行流程

**T0-T1：用户需求进入系统**

```python
# Team.run_project()
initial_message = Message(
    content="创建一个2048游戏",
    cause_by="UserRequirement",
    send_to={"*"}
)
env.publish_message(initial_message)
# -> 所有角色的msg_buffer都收到此消息
```

**T1-T4：ProductManager生成PRD**

```python
# ProductManager._observe()
await pm._observe()
# -> pm.rc.news = [Message(content="创建一个2048游戏", cause_by=UserRequirement)]

# ProductManager._think() (BY_ORDER模式)
await pm._think()
# -> pm.rc.state = 0
# -> pm.rc.todo = WritePRD

# ProductManager._act()
rsp = await pm._act()
# WritePRD.run() 被调用
# -> 使用LLM生成PRD
# -> 保存到 workspace/docs/prd/prd.md
# -> 返回 Message(
#      content="PRD已完成：包含游戏规则、用户故事等",
#      instruct_content=PRD(...),
#      cause_by="WritePRD"
#    )

# ProductManager.publish_message()
env.publish_message(rsp)
# -> Architect的msg_buffer收到消息（因为订阅了WritePRD）
```

**T5-T8：Architect生成设计**

```python
# Architect._observe()
await architect._observe()
# -> architect.rc.news = [Message(cause_by=WritePRD)]

# Architect._think()
await architect._think()
# -> architect.rc.todo = WriteDesign

# Architect._act()
rsp = await architect._act()
# WriteDesign.run()
# 1. 读取PRD
# 2. 生成系统设计
# 3. 生成数据结构和API
# 4. 生成Mermaid类图和序列图
# 5. 保存到 workspace/docs/system_design/
# -> 返回 Message(cause_by="WriteDesign")

env.publish_message(rsp)
# -> Engineer的msg_buffer收到消息
```

**T9-T12：Engineer编写代码**

```python
# Engineer._observe()
await engineer._observe()
# -> engineer.rc.news = [Message(cause_by=WriteDesign)]

# Engineer._think()
await engineer._think()
# -> engineer.rc.todo = WriteCode

# Engineer._act()
rsp = await engineer._act()
# WriteCode.run()
# 1. 读取设计文档
# 2. 为每个文件生成代码
#    - game_2048/main.py
#    - game_2048/game.py
#    - game_2048/ui.py
#    - requirements.txt
# 3. 保存到 workspace/game_2048/
# -> 返回 Message(cause_by="WriteCode")

env.publish_message(rsp)
```

**T13：检查是否完成**

```python
# Team.run()中的循环
await env.run()
# -> 所有角色执行完毕
# -> env.is_idle == True（所有角色都没有新消息）
# -> 循环结束
```

#### 步骤4：生成的文件结构

```
workspace/
├── docs/
│   ├── prd/
│   │   └── prd.md                    # 产品需求文档
│   ├── system_design/
│   │   ├── system_design.md          # 系统设计
│   │   ├── data_api_design.json      # 数据结构和API
│   │   └── seq_flow.mmd              # 序列图
│   └── api_spec_and_tasks/
│       └── code_plan_and_change.md   # 代码计划
├── resources/
│   ├── class_diagram.mmd             # 类图
│   └── seq_flow.png                  # 序列图（渲染后）
└── game_2048/
    ├── main.py                       # 主程序
    ├── game.py                       # 游戏逻辑
    ├── ui.py                         # 用户界面
    ├── requirements.txt              # 依赖
    └── README.md                     # 说明文档
```

### 4.2 消息路由详解

**订阅关系（watch）**：

```python
# ProductManager
self._watch([UserRequirement, BossRequirement])

# Architect
self._watch([WritePRD])

# Engineer
self._watch([WriteDesign])

# QAEngineer
self._watch([WriteCode])
```

**消息流图**：

```
UserRequirement
    ├─> ProductManager (订阅UserRequirement)
    │   └─> WritePRD
    │       └─> Architect (订阅WritePRD)
    │           └─> WriteDesign
    │               ├─> Engineer (订阅WriteDesign)
    │               │   └─> WriteCode
    │               │       └─> QAEngineer (订阅WriteCode)
    │               │           └─> WriteTest
    │               └─> ProjectManager (订阅WriteDesign)
    │                   └─> WritePlan
```

---

## 五、关键设计模式

### 5.1 观察者模式（Observer Pattern）

**应用场景**：消息订阅机制

**实现方式**：
```python
# 订阅（在Role初始化时）
self._watch([WritePRD, WriteDesign])

# 发布（在Action完成后）
self.publish_message(Message(cause_by=WritePRD))

# 接收（在Environment中分发）
for role in self.roles.values():
    if message.cause_by in role.rc.watch:
        role.put_message(message)
```

**优势**：
- 角色间解耦：角色不需要知道其他角色的存在
- 灵活路由：通过修改watch轻松改变协作关系
- 支持广播：一个消息可以被多个角色接收

### 5.2 责任链模式（Chain of Responsibility）

**应用场景**：任务流转

**实现方式**：
```python
# 隐式责任链：通过消息订阅形成
UserRequirement -> PM -> Architect -> Engineer -> QA
```

**特点**：
- 自动流转：每个角色完成后自动触发下一个
- 可中断：任何环节失败不影响其他角色
- 可扩展：插入新角色只需修改watch关系

### 5.3 策略模式（Strategy Pattern）

**应用场景**：RoleReactMode

**实现方式**：
```python
class Role:
    async def react(self) -> Message:
        if self.rc.react_mode == RoleReactMode.REACT:
            return await self._react()
        elif self.rc.react_mode == RoleReactMode.BY_ORDER:
            return await self._act()
        elif self.rc.react_mode == RoleReactMode.PLAN_AND_ACT:
            return await self._plan_and_act()
```

**优势**：
- 同一个Role可以用不同模式运行
- 易于扩展新的反应模式

### 5.4 发布-订阅模式（Pub-Sub Pattern）

**应用场景**：Environment作为消息总线

**实现方式**：
```python
# Environment作为事件总线
class Environment:
    def publish_message(self, message: Message):
        # 发布到所有订阅者
        for role in self.subscribers(message):
            role.put_message(message)
```

### 5.5 Actor模型

**应用场景**：整体架构

**核心思想**：
- 每个Role是一个Actor
- Actor间只通过Message通信
- 每个Actor有独立的状态（memory, todo等）
- Actor并发执行，互不干扰

**优势**：
- 天然支持并发
- 避免状态竞争
- 易于分布式扩展

---

## 六、多智能体协作机制

### 6.1 协作模式分类

#### 1. 流水线模式（Pipeline）

**特点**：任务按顺序流转，每个角色负责一个环节。

**示例**：软件开发流程
```
PM -> Architect -> Engineer -> QA -> DevOps
```

**实现**：
```python
class ProductManager(Role):
    def __init__(self):
        self._watch([UserRequirement])  # 监听用户需求
        self.set_actions([WritePRD])

class Architect(Role):
    def __init__(self):
        self._watch([WritePRD])         # 监听PRD
        self.set_actions([WriteDesign])

class Engineer(Role):
    def __init__(self):
        self._watch([WriteDesign])      # 监听设计
        self.set_actions([WriteCode])
```

#### 2. 协同模式（Collaboration）

**特点**：多个角色同时工作，互相配合。

**示例**：MGX环境中的TeamLeader协调
```
TeamLeader -> 协调多个角色 -> 汇总结果
```

**实现**：
```python
class TeamLeader(Role):
    async def _coordinate(self):
        # 分配任务给不同角色
        task1 = await self._assign_to(researcher, "研究竞品")
        task2 = await self._assign_to(analyst, "分析数据")

        # 并发执行
        results = await asyncio.gather(task1, task2)

        # 汇总结果
        summary = await self._summarize(results)
        return summary
```

#### 3. 评审模式（Review）

**特点**：一个角色的输出需要另一个角色审查。

**示例**：代码评审
```
Engineer -> WriteCode -> CodeReviewEngineer -> Review -> Engineer -> Fix
```

**实现**：
```python
class CodeReviewEngineer(Role):
    async def _review(self, code: Message):
        issues = await self._find_issues(code)

        if issues:
            # 发送回Engineer修改
            return Message(
                content=f"发现{len(issues)}个问题",
                instruct_content=issues,
                send_to={"Engineer"}
            )
        else:
            return Message(content="代码通过评审")
```

#### 4. 辩论模式（Debate）

**特点**：多个角色从不同角度讨论问题。

**示例**：技术方案选型
```
Round 1: A提出方案1, B提出方案2
Round 2: A反驳方案2, B反驳方案1
Round 3: 达成共识
```

**实现**：
```python
class DebateTeam(Team):
    async def debate(self, topic: str, n_round=3):
        for i in range(n_round):
            # 所有角色发表观点
            opinions = await asyncio.gather(
                *[role.express_opinion(topic) for role in self.roles]
            )

            # 每个角色阅读其他人的观点
            for role in self.roles:
                role.read_opinions(opinions)

        # 最终投票
        decision = await self.vote()
        return decision
```

### 6.2 消息驱动协作

**核心机制**：

1. **异步消息传递**：
   ```python
   # 角色A发送消息
   msg = Message(content="任务完成", cause_by=TaskA)
   self.publish_message(msg)

   # 角色B在下一轮观察到消息
   await role_b._observe()  # 从msg_buffer获取
   ```

2. **消息缓冲队列**：
   ```python
   class MessageQueue:
       def __init__(self):
           self._queue = deque()

       def push(self, msg: Message):
           self._queue.append(msg)

       def pop_all(self) -> List[Message]:
           msgs = list(self._queue)
           self._queue.clear()
           return msgs
   ```

3. **并发执行**：
   ```python
   # Environment并发运行所有角色
   futures = [role.run() for role in self.roles.values()]
   await asyncio.gather(*futures)
   ```

### 6.3 状态同步

**共享状态**：

1. **Context（全局配置）**：
   ```python
   class Context:
       config: Config              # 配置
       cost_manager: CostManager   # 成本管理

   # 所有角色共享同一个Context
   for role in team.roles:
       assert role.context is team.context
   ```

2. **Environment.history（完整历史）**：
   ```python
   # 任何角色都可以访问完整历史
   full_history = role.rc.env.history.get()
   ```

3. **ProjectRepo（文件仓库）**：
   ```python
   # 共享的文件系统
   await self.repo.docs.prd.save("prd.md", content)
   prd = await self.repo.docs.prd.get("prd.md")
   ```

**私有状态**：

1. **RoleContext.memory（个人记忆）**：
   ```python
   # 每个角色有独立的记忆
   role_a.rc.memory != role_b.rc.memory
   ```

2. **RoleContext.todo（当前任务）**：
   ```python
   # 角色的当前待办事项
   role.rc.todo = WriteCode
   ```

### 6.4 冲突解决

**场景1：多个角色修改同一文件**

**解决方案**：版本控制
```python
class Document:
    version: int

    async def save(self, content):
        # 检查版本冲突
        if self.version != expected_version:
            raise ConflictError

        self.content = content
        self.version += 1
```

**场景2：角色意见不一致**

**解决方案**：TeamLeader仲裁
```python
class TeamLeader(Role):
    async def resolve_conflict(self, opinions: List[Message]):
        # 使用LLM综合所有意见
        decision = await self.llm.aask(
            f"请综合以下意见做出决定：\n{opinions}"
        )
        return decision
```

---

## 七、核心创新点

### 7.1 SOP物化（Code = SOP(Team)）

**传统软件开发**：
```
需求 -> 设计 -> 编码 -> 测试 -> 部署
（每个环节由人工完成，依赖个人经验）
```

**MetaGPT的SOP物化**：
```python
# SOP被编码为角色和动作的序列
class SoftwareCompany(Team):
    def __init__(self):
        self.hire([
            ProductManager(),   # SOP步骤1：需求分析
            Architect(),        # SOP步骤2：系统设计
            Engineer(),         # SOP步骤3：编码实现
            QAEngineer()        # SOP步骤4：质量保证
        ])

    # 整个SOP可以自动执行
    async def develop(self, requirement: str):
        await self.run(idea=requirement)
```

**优势**：
- **可复制**：SOP可以跨项目复用
- **可优化**：通过修改角色配置优化流程
- **可扩展**：轻松添加新环节（如CodeReview）

### 7.2 结构化输出（ActionNode）

**传统LLM调用**：
```python
# 问题：输出是自然语言，难以解析
prd_text = await llm.aask("请写一个PRD")
# 输出：一大段文本，格式不固定

# 需要复杂的解析逻辑
title = extract_title(prd_text)  # 易出错
goals = extract_goals(prd_text)
```

**MetaGPT的ActionNode**：
```python
# 定义结构
class PRD(BaseModel):
    title: str
    goals: List[str]
    requirements: List[Requirement]

# 使用ActionNode
prd = await PRD_NODE.fill(context="...", llm=llm)

# 直接得到结构化对象
print(prd.instruct_content.title)        # 类型安全
print(prd.instruct_content.goals[0])     # 可直接访问
```

**实现原理**：
```python
# ActionNode使用JSON Schema约束LLM输出
class ActionNode:
    @classmethod
    def from_pydantic(cls, model: Type[BaseModel]):
        # 从Pydantic模型生成JSON Schema
        schema = model.schema()

        # 在prompt中要求输出符合schema
        prompt = f"""
        请按照以下JSON Schema输出：
        {json.dumps(schema)}

        要求：输出必须是有效的JSON，且符合schema定义。
        """
        return cls(schema=schema, prompt=prompt)

    async def fill(self, context: str, llm):
        # 调用LLM
        response = await llm.aask(self.prompt + context)

        # 解析并验证
        data = json.loads(response)
        validated = self.model.parse_obj(data)

        return Message(instruct_content=validated)
```

### 7.3 三种反应模式

**REACT模式的创新**：
```python
# 传统：固定流程
def process():
    step1()
    step2()
    step3()

# MetaGPT REACT：动态决策
async def _react(self):
    while not done:
        # LLM动态决定下一步
        next_action = await self._think()
        result = await self._act(next_action)

        # 根据结果决定是否继续
        if self._is_done(result):
            break
```

**应用场景**：
- **BY_ORDER**：流程明确的场景（如软件开发）
- **REACT**：需要灵活应对的场景（如客服对话）
- **PLAN_AND_ACT**：复杂任务需要先规划（如研究项目）

### 7.4 消息路由系统

**传统多智能体系统**：
```python
# 硬编码调用
result1 = agent1.process(input)
result2 = agent2.process(result1)
result3 = agent3.process(result2)
```

**MetaGPT的消息路由**：
```python
# 声明式订阅
class Agent1(Role):
    def __init__(self):
        self._watch([UserInput])

class Agent2(Role):
    def __init__(self):
        self._watch([Agent1Action])

# 自动路由
env.publish_message(msg)  # 自动找到订阅者
```

**优势**：
- 角色间完全解耦
- 易于调整协作关系
- 支持动态添加/删除角色

### 7.5 增量迭代支持

**场景**：基于已有代码的迭代开发

```python
# 第一次运行：创建项目
await team.run(idea="创建一个2048游戏")
# 生成：game.py, ui.py, main.py

# 第二次运行：添加功能
await team.run(idea="添加排行榜功能")
# Engineer会：
# 1. 读取现有代码
# 2. 分析需要修改的部分
# 3. 增量修改，保留其他代码
```

**实现机制**：
```python
class Engineer(Role):
    async def _incremental_dev(self, new_requirement: str):
        # 1. 读取现有代码
        existing_code = await self.repo.src_workspace.get_all()

        # 2. 分析变更
        changes = await self._analyze_changes(
            existing_code=existing_code,
            new_requirement=new_requirement
        )

        # 3. 应用变更
        for change in changes:
            if change.type == "modify":
                # 修改现有文件
                await self._modify_file(change)
            elif change.type == "add":
                # 添加新文件
                await self._add_file(change)
```

---

## 八、实际应用案例

### 8.1 软件公司（SoftwareCompany）

**场景**：从需求到完整项目

**输入**：
```python
await team.run(idea="创建一个命令行俄罗斯方块游戏")
```

**输出**：
```
workspace/
├── docs/
│   ├── prd/
│   │   ├── competitive_analysis.md    # 竞品分析
│   │   └── prd.md                     # 产品需求文档
│   ├── system_design/
│   │   ├── system_design.md           # 系统设计
│   │   └── data_api_design.json       # 数据和API设计
│   └── api_spec_and_tasks/
│       └── code_plan.md               # 开发计划
├── tetris/
│   ├── game.py                        # 游戏逻辑
│   ├── blocks.py                      # 方块定义
│   ├── board.py                       # 游戏板
│   ├── ui.py                          # 用户界面
│   └── main.py                        # 主程序
├── tests/
│   ├── test_game.py
│   └── test_blocks.py
└── requirements.txt
```

### 8.2 数据解释器（DataInterpreter）

**场景**：数据分析和可视化

**输入**：
```python
di = DataInterpreter()
await di.run("分析sklearn Iris数据集，画出散点图")
```

**执行流程**：
```
1. 理解需求
2. 编写Python代码加载数据
3. 执行代码，获取数据
4. 分析数据特征
5. 生成可视化代码
6. 执行并展示图表
```

**输出**：
- Python分析脚本
- 数据统计报告
- 可视化图表（PNG）

### 8.3 研究助手（Researcher）

**场景**：文献调研和报告撰写

**输入**：
```python
researcher = Researcher()
await researcher.run("调研Transformer模型的最新进展")
```

**工作流程**：
```python
class Researcher(Role):
    def __init__(self):
        self.set_actions([
            CollectLinks,      # 收集相关链接
            WebBrowseAndSummarize,  # 浏览并总结
            ConductResearch,   # 深入研究
            WriteReport        # 撰写报告
        ])
```

**输出**：
- 相关论文列表
- 每篇论文的摘要
- 综合研究报告

### 8.4 辩论（Debate）

**场景**：多角度讨论问题

**输入**：
```python
team = Team()
team.hire([
    Debater(name="正方", stance="支持"),
    Debater(name="反方", stance="反对")
])
await team.run(idea="AI是否会取代程序员？")
```

**执行流程**：
```
Round 1:
  正方: 提出论点A
  反方: 提出论点B

Round 2:
  正方: 反驳论点B，补充论据
  反方: 反驳论点A，补充论据

Round 3:
  正方: 总结陈词
  反方: 总结陈词

最终: 综合双方观点
```

---

## 九、扩展和自定义

### 9.1 创建自定义Role

**示例**：创建一个SEO专家角色

```python
from metagpt.actions import Action
from metagpt.roles import Role
from metagpt.schema import Message

# 1. 定义Action
class AnalyzeSEO(Action):
    """分析网站SEO"""

    async def run(self, url: str) -> Message:
        # 使用LLM分析SEO
        analysis = await self.llm.aask(f"""
        分析以下网站的SEO情况：{url}

        请从以下方面分析：
        1. 标题和描述
        2. 关键词使用
        3. 内容质量
        4. 链接结构
        """)

        return Message(content=analysis, cause_by=self)

class OptimizeSEO(Action):
    """优化SEO建议"""

    async def run(self, analysis: str) -> Message:
        suggestions = await self.llm.aask(f"""
        根据以下SEO分析结果，提供优化建议：
        {analysis}
        """)

        return Message(content=suggestions, cause_by=self)

# 2. 定义Role
class SEOExpert(Role):
    name: str = "SEOExpert"
    profile: str = "SEO专家"
    goal: str = "优化网站的搜索引擎排名"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 设置动作序列
        self.set_actions([AnalyzeSEO, OptimizeSEO])

        # 设置反应模式
        self._set_react_mode(RoleReactMode.BY_ORDER)

        # 订阅用户请求
        self._watch([UserRequirement])

# 3. 使用
seo_expert = SEOExpert()
result = await seo_expert.run(
    Message(content="分析 https://example.com 的SEO")
)
```

### 9.2 创建自定义Action

**示例**：创建一个代码重构Action

```python
class RefactorCode(Action):
    """代码重构"""

    # 定义输出结构
    class RefactorResult(BaseModel):
        original_code: str
        refactored_code: str
        changes: List[str]
        improvements: List[str]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 使用ActionNode实现结构化输出
        self.node = ActionNode.from_pydantic(self.RefactorResult)

    async def run(self, code: str) -> Message:
        # 使用LLM重构代码
        result = await self.node.fill(
            context=f"""
            请重构以下代码，提高可读性和性能：

            ```python
            {code}
            ```

            要求：
            1. 遵循PEP 8规范
            2. 提取重复代码
            3. 优化算法复杂度
            4. 添加必要注释
            """,
            llm=self.llm
        )

        return result
```

### 9.3 创建自定义Environment

**示例**：创建一个限流环境

```python
class RateLimitedEnv(Environment):
    """带速率限制的环境"""

    def __init__(self, max_messages_per_minute: int = 10, **kwargs):
        super().__init__(**kwargs)
        self.max_messages = max_messages_per_minute
        self.message_times = deque()

    def publish_message(self, message: Message) -> bool:
        # 检查速率限制
        now = time.time()

        # 清理1分钟前的记录
        while self.message_times and self.message_times[0] < now - 60:
            self.message_times.popleft()

        # 检查是否超过限制
        if len(self.message_times) >= self.max_messages:
            logger.warning("达到速率限制，消息被延迟")
            await asyncio.sleep(1)

        # 记录消息时间
        self.message_times.append(now)

        # 调用父类方法
        return super().publish_message(message)
```

### 9.4 自定义Team工作流程

**示例**：创建一个敏捷开发团队

```python
class AgileTeam(Team):
    """敏捷开发团队"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 雇佣团队成员
        self.hire([
            ProductOwner(),     # 产品负责人
            ScrumMaster(),      # Scrum Master
            Developer(),        # 开发人员
            Tester()           # 测试人员
        ])

    async def sprint(self, user_stories: List[str], sprint_days: int = 14):
        """执行一个Sprint"""

        # Sprint Planning
        await self._sprint_planning(user_stories)

        # Daily Scrum
        for day in range(sprint_days):
            await self._daily_scrum()
            await self.env.run()  # 执行当天任务

        # Sprint Review
        await self._sprint_review()

        # Sprint Retrospective
        await self._sprint_retrospective()

    async def _sprint_planning(self, user_stories: List[str]):
        """Sprint计划会议"""
        self.env.publish_message(Message(
            content=f"Sprint Planning: {user_stories}",
            cause_by="SprintPlanning",
            send_to={"*"}
        ))

    async def _daily_scrum(self):
        """每日站会"""
        for role in self.roles.values():
            # 每个成员汇报进度
            report = await role.daily_report()
            self.env.publish_message(report)
```

---

## 十、最佳实践

### 10.1 角色设计原则

1. **单一职责**：每个Role只负责一个领域
   ```python
   # Good
   class ProductManager(Role):
       actions = [WritePRD]

   # Bad
   class SuperRole(Role):
       actions = [WritePRD, WriteCode, WriteTest]  # 职责太多
   ```

2. **明确目标**：设置清晰的goal和constraints
   ```python
   class Architect(Role):
       goal = "设计可扩展、高性能的系统架构"
       constraints = "必须考虑成本和开发时间"
   ```

3. **合理订阅**：只订阅必要的消息
   ```python
   # Good
   self._watch([WritePRD])  # 只关注PRD

   # Bad
   self._watch([*])  # 订阅所有消息，噪音太多
   ```

### 10.2 Action设计原则

1. **原子性**：每个Action完成一个完整的任务
   ```python
   # Good
   class WriteCode(Action):
       async def run(self):
           # 完整地写完一个文件的代码
           ...

   # Bad
   class WriteHalfCode(Action):
       async def run(self):
           # 只写一半，需要另一个Action继续
           ...
   ```

2. **幂等性**：多次执行结果相同
   ```python
   class WriteDesign(Action):
       async def run(self):
           # 每次运行生成相同的设计（给定相同输入）
           design = await self._generate_design(prd)
           return design
   ```

3. **结构化输出**：使用ActionNode
   ```python
   class WriteAPI(Action):
       def __init__(self):
           # 定义结构化输出
           self.node = ActionNode.from_pydantic(APISpec)
   ```

### 10.3 成本控制

**监控成本**：
```python
from metagpt.context import Context

# 获取成本信息
ctx = Context()
total_cost = ctx.cost_manager.total_cost
print(f"总成本: ${total_cost:.2f}")
```

**设置预算**：
```python
team = Team(investment=10.0)  # 预算10美元

# 运行时检查
if team.cost_manager.total_cost > team.investment:
    raise ValueError("超出预算")
```

**优化提示词**：
```python
# Bad: 冗长的prompt
prompt = """
请你作为一个非常有经验的产品经理，认真仔细地分析用户需求...
（1000字的提示词）
"""

# Good: 简洁的prompt
prompt = """
作为产品经理，分析需求并输出PRD。
要求：包含目标、用户故事、需求列表。
"""
```

### 10.4 调试技巧

**1. 启用详细日志**：
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 查看所有消息流转
logger.debug(f"Message: {msg}")
```

**2. 保存中间结果**：
```python
class DebugRole(Role):
    async def _act(self):
        result = await super()._act()

        # 保存到文件
        with open(f"debug_{self.name}_{time.time()}.json", "w") as f:
            f.write(result.model_dump_json())

        return result
```

**3. 可视化消息流**：
```python
class VisualizationEnv(Environment):
    def publish_message(self, message: Message):
        # 记录消息流
        self.message_flow.append({
            "from": message.sent_from,
            "to": message.send_to,
            "action": message.cause_by,
            "time": time.time()
        })

        return super().publish_message(message)

    def export_flow_diagram(self):
        # 导出Mermaid图
        mermaid = "sequenceDiagram\n"
        for msg in self.message_flow:
            mermaid += f"  {msg['from']}->{msg['to']}: {msg['action']}\n"
        return mermaid
```

---

## 十一、性能优化

### 11.1 并发优化

**策略1：并行执行独立角色**
```python
# Environment已默认实现
async def run(self):
    futures = [role.run() for role in self.roles.values()]
    await asyncio.gather(*futures)  # 并发执行
```

**策略2：批量处理消息**
```python
class BatchedAction(Action):
    async def run(self, messages: List[Message]):
        # 批量调用LLM
        prompts = [self._make_prompt(m) for m in messages]
        results = await self.llm.abatch_ask(prompts)
        return results
```

### 11.2 缓存优化

**策略1：LLM响应缓存**
```python
from functools import lru_cache

class CachedAction(Action):
    @lru_cache(maxsize=100)
    async def _cached_ask(self, prompt: str):
        return await self.llm.aask(prompt)
```

**策略2：文档缓存**
```python
class DocumentCache:
    def __init__(self):
        self._cache = {}

    async def get(self, filename: str):
        if filename not in self._cache:
            self._cache[filename] = await self._load(filename)
        return self._cache[filename]
```

### 11.3 Prompt优化

**减少token使用**：
```python
# Bad
prompt = f"完整的PRD文档：\n{prd_content}"  # 可能很长

# Good
prompt = f"PRD摘要：\n{prd_summary}"  # 使用摘要
```

**使用更便宜的模型**：
```python
class SimpleAction(Action):
    llm_name_or_type = "gpt-3.5-turbo"  # 简单任务用3.5

class ComplexAction(Action):
    llm_name_or_type = "gpt-4"  # 复杂任务用4
```

---

## 十二、总结

### 12.1 核心优势

1. **高度模块化**：Role、Action、Environment完全解耦，易于扩展
2. **灵活的协作机制**：消息驱动，支持多种协作模式
3. **结构化输出**：ActionNode确保LLM输出可靠
4. **SOP物化**：将标准流程编码为可执行的系统
5. **并发支持**：天然支持多智能体并发执行

### 12.2 适用场景

**推荐使用**：
- 软件开发项目
- 数据分析任务
- 研究和调研
- 内容创作
- 多角度决策

**不推荐使用**：
- 实时性要求极高的场景（LLM有延迟）
- 需要100%准确的计算任务
- 预算非常有限的场景

### 12.3 未来发展方向

1. **更多预定义角色**：覆盖更多领域
2. **可视化开发**：拖拽式配置工作流程
3. **分布式支持**：跨机器部署角色
4. **人机协作**：更好的人类介入机制
5. **持续学习**：从历史执行中学习优化

---

## 附录

### A. 核心类速查表

| 类名 | 位置 | 职责 |
|------|------|------|
| Message | schema.py | 消息封装 |
| Role | roles/role.py | 智能体基类 |
| Action | actions/action.py | 动作基类 |
| Environment | environment/base_env.py | 环境和消息总线 |
| Team | team.py | 团队管理 |
| Memory | memory/memory.py | 记忆存储 |
| Context | context.py | 全局上下文 |
| ActionNode | actions/action_node.py | 结构化输出 |

### B. 常用配置

**config2.yaml示例**：
```yaml
llm:
  api_type: "openai"
  model: "gpt-4-turbo"
  base_url: "https://api.openai.com/v1"
  api_key: "YOUR_API_KEY"
  temperature: 0.7
  max_tokens: 2000

workspace:
  path: "./workspace"

cost_limit:
  max_cost: 100.0  # 最大成本（美元）
```

### C. 环境变量

```bash
# OpenAI API
export OPENAI_API_KEY="sk-..."

# 工作目录
export METAGPT_WORKSPACE="./workspace"

# 日志级别
export METAGPT_LOG_LEVEL="INFO"
```

### D. 常见问题

**Q: 如何修改LLM提供者？**
```python
# 在config2.yaml中修改
llm:
  api_type: "azure"  # 或 "ollama", "groq"等
```

**Q: 如何限制执行轮次？**
```python
await team.run(n_round=5)  # 最多执行5轮
```

**Q: 如何保存和恢复执行状态？**
```python
# 保存
team.serialize(path="team_state.json")

# 恢复
team = Team.deserialize(path="team_state.json")
await team.run()  # 继续执行
```

**Q: 如何查看消耗的token数？**
```python
print(f"总成本: ${ctx.cost_manager.total_cost}")
print(f"总token: {ctx.cost_manager.total_tokens}")
```

---

**文档版本**：1.0
**最后更新**：2025-11-16
**作者**：基于MetaGPT v1.0.0源码分析

---

## 参考资料

1. [MetaGPT官方文档](https://docs.deepwisdom.ai/)
2. [MetaGPT GitHub仓库](https://github.com/geekan/MetaGPT)
3. [MetaGPT论文](https://openreview.net/forum?id=VtmBAGCN7o)
4. [Pydantic文档](https://docs.pydantic.dev/)
5. [AsyncIO文档](https://docs.python.org/3/library/asyncio.html)
