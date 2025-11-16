# Software Company 实现细节详解

## 目录

1. [概述](#概述)
2. [整体架构](#整体架构)
3. [核心组件](#核心组件)
4. [工作流程](#工作流程)
5. [关键实现](#关键实现)
6. [使用示例](#使用示例)
7. [技术细节](#技术细节)

---

## 概述

### 什么是 Software Company

Software Company 是 MetaGPT 框架中的一个示例应用，位于 `examples/di/software_company.py`。它展示了如何使用 **Data Interpreter (DI)** 角色来自动化软件开发的全生命周期流程，包括：

- 编写产品需求文档 (PRD)
- 系统设计 (Design)
- 项目计划 (Plan)
- 代码实现 (Code)
- 质量保证测试 (QA)
- Git 版本控制

### 设计理念

Software Company 的核心理念是将传统软件公司的开发流程自动化，通过 AI Agent 模拟产品经理、架构师、项目经理、工程师等角色的协作，从用户需求直接生成可运行的软件项目。

---

## 整体架构

### 架构图

```
用户需求
    ↓
DataInterpreter (DI Agent)
    ↓
工具链 (Tools)
    ├── WritePRD (产品需求文档)
    ├── WriteDesign (系统设计)
    ├── WritePlan (项目计划)
    ├── WriteCode (代码编写)
    ├── RunCode (代码执行)
    └── DebugError (错误调试)
    ↓
完整的软件项目
```

### 技术栈

- **核心框架**: MetaGPT
- **AI 引擎**: LLM (Large Language Model)
- **执行环境**: Jupyter Notebook (通过 ExecuteNbCode)
- **工具系统**: Tool Registry + Tool Recommender
- **版本控制**: Git

---

## 核心组件

### 1. DataInterpreter 角色

**位置**: `metagpt/roles/di/data_interpreter.py`

DataInterpreter 是 Software Company 的核心执行者，它继承自 `Role` 基类，具有以下特性：

#### 关键属性

```python
class DataInterpreter(Role):
    name: str = "David"                          # Agent 名称
    profile: str = "DataInterpreter"             # 角色类型
    auto_run: bool = True                        # 是否自动运行
    use_plan: bool = True                        # 是否使用计划模式
    use_reflection: bool = False                 # 是否使用反思机制
    execute_code: ExecuteNbCode                  # 代码执行器
    tools: list[str] = []                        # 可用工具列表
    tool_recommender: ToolRecommender = None     # 工具推荐器
    react_mode: Literal["plan_and_act", "react"] # 运行模式
    max_react_loop: int = 10                     # 最大循环次数
```

#### 两种运行模式

1. **plan_and_act 模式** (默认)
   - 先制定完整计划
   - 按计划逐步执行任务
   - 适合复杂的软件开发流程

2. **react 模式**
   - 边思考边行动
   - 动态决策下一步操作
   - 适合探索性任务

#### 核心方法

##### `_plan_and_act()` 方法

```python
async def _plan_and_act(self) -> Message:
    """
    计划并执行模式的主流程
    1. 制定计划
    2. 执行每个任务
    3. 处理执行结果
    """
    self._set_state(0)
    try:
        rsp = await super()._plan_and_act()
        await self.execute_code.terminate()
        return rsp
    except Exception as e:
        await self.execute_code.terminate()
        raise e
```

##### `_write_and_exec_code()` 方法

```python
async def _write_and_exec_code(self, max_retry: int = 3):
    """
    编写并执行代码的核心循环

    流程:
    1. 获取计划状态
    2. 推荐相关工具
    3. 检查数据
    4. 编写代码 (最多重试3次)
    5. 执行代码
    6. 处理执行结果

    返回:
        (code, result, success): 代码内容、执行结果、是否成功
    """
    counter = 0
    success = False

    # 获取计划状态
    plan_status = self.planner.get_plan_status() if self.use_plan else ""

    # 工具推荐
    if self.tool_recommender:
        context = self.working_memory.get()[-1].content if self.working_memory.get() else ""
        plan = self.planner.plan if self.use_plan else None
        tool_info = await self.tool_recommender.get_recommended_tool_info(
            context=context, plan=plan
        )
    else:
        tool_info = ""

    # 数据检查
    await self._check_data()

    # 重试循环
    while not success and counter < max_retry:
        # 编写代码
        code, cause_by = await self._write_code(counter, plan_status, tool_info)
        self.working_memory.add(Message(content=code, role="assistant", cause_by=cause_by))

        # 执行代码
        result, success = await self.execute_code.run(code)
        print(result)

        self.working_memory.add(Message(content=result, role="user", cause_by=ExecuteNbCode))
        counter += 1

    return code, result, success
```

### 2. 工具系统

Software Company 使用了一系列专门的工具来完成软件开发的各个阶段：

#### WritePRD - 产品需求文档工具

**位置**: `metagpt/actions/write_prd.py`

**功能**:
- 根据用户需求生成产品需求文档 (PRD)
- 支持新需求、需求更新和 Bug 修复三种场景
- 自动生成竞品分析图表

**核心流程**:

```python
@register_tool(include_functions=["run"])
class WritePRD(Action):
    async def run(
        self,
        user_requirement: str = "",      # 用户需求
        output_pathname: str = "",       # 输出路径
        legacy_prd_filename: str = "",   # 旧版 PRD 文件
        extra_info: str = "",            # 额外信息
    ) -> str:
        """
        生成 PRD 的三种场景:
        1. Bugfix: 检测到是 bug 修复需求
        2. New requirement: 全新需求
        3. Requirement update: 需求更新
        """
```

**关键特性**:
1. **智能需求分类**
   ```python
   async def _is_bugfix(self, context: str) -> bool:
       """通过 LLM 判断是否为 bug 修复"""
       if not self.repo.code_files_exists():
           return False
       node = await WP_ISSUE_TYPE_NODE.fill(req=context, llm=self.llm)
       return node.get("issue_type") == "BUG"
   ```

2. **需求关联检测**
   ```python
   async def _is_related(self, req: Document, old_prd: Document) -> bool:
       """判断新需求是否与现有 PRD 相关"""
       context = NEW_REQ_TEMPLATE.format(
           old_prd=old_prd.content,
           requirements=req.content
       )
       node = await WP_IS_RELATIVE_NODE.fill(req=context, llm=self.llm)
       return node.get("is_relative") == "YES"
   ```

3. **文档生成**
   - 生成 JSON 格式的结构化 PRD
   - 自动生成 Markdown 版本用于阅读
   - 生成竞品分析四象限图 (Mermaid)

**输出示例**:
```
- PRD 文档: snake_game/docs/prd.json
- Markdown 版本: snake_game/docs/prd.md
- 竞品分析图: snake_game/resources/competitive_analysis/prd.svg
```

#### WriteDesign - 系统设计工具

**位置**: `metagpt/actions/design_api.py`

**功能**:
- 基于 PRD 设计系统架构
- 定义数据结构和接口
- 设计程序调用流程

**核心流程**:

```python
@register_tool(include_functions=["run"])
class WriteDesign(Action):
    async def run(
        self,
        user_requirement: str = "",       # 用户需求
        prd_filename: str = "",           # PRD 文件路径
        legacy_design_filename: str = "", # 旧版设计文件
        extra_info: str = "",             # 额外信息
        output_pathname: str = "",        # 输出路径
    ) -> str:
        """
        生成系统设计文档
        """
```

**设计内容**:

1. **数据结构和接口** (Data Structures and Interfaces)
   - 类定义
   - 接口规范
   - 数据模型
   - 生成类图 (Mermaid ClassDiagram)

2. **程序调用流程** (Program Call Flow)
   - 模块间交互
   - 函数调用关系
   - 生成序列图 (Mermaid SequenceDiagram)

**关键方法**:

```python
async def _new_system_design(self, context):
    """生成新的系统设计"""
    node = await DESIGN_API_NODE.fill(
        req=context,
        llm=self.llm,
        schema=self.prompt_schema
    )
    return node

async def _merge(self, prd_doc, system_design_doc):
    """合并 PRD 和现有设计"""
    context = NEW_REQ_TEMPLATE.format(
        old_design=system_design_doc.content,
        context=prd_doc.content
    )
    node = await REFINED_DESIGN_NODE.fill(
        req=context,
        llm=self.llm,
        schema=self.prompt_schema
    )
    system_design_doc.content = node.instruct_content.model_dump_json()
    return system_design_doc
```

**输出示例**:
```
- 系统设计文档: snake_game/docs/system_design.json
- 类图: snake_game/resources/data_api_design/system_design.svg
- 序列图: snake_game/resources/seq_flow/system_design.svg
```

#### WritePlan - 项目计划工具

**位置**: `metagpt/actions/di/write_plan.py`

**功能**:
- 将系统设计分解为具体任务
- 管理任务依赖关系
- 支持计划动态调整

**核心实现**:

```python
class WritePlan(Action):
    async def run(self, context: list[Message], max_tasks: int = 5) -> str:
        """
        生成项目计划

        Args:
            context: 上下文消息列表
            max_tasks: 最大任务数量

        Returns:
            JSON 格式的任务列表
        """
        task_type_desc = "\n".join([
            f"- **{tt.type_name}**: {tt.value.desc}"
            for tt in TaskType
        ])

        prompt = PROMPT_TEMPLATE.format(
            context="\n".join([str(ct) for ct in context]),
            max_tasks=max_tasks,
            task_type_desc=task_type_desc
        )

        rsp = await self._aask(prompt)
        rsp = CodeParser.parse_code(text=rsp)
        return rsp
```

**任务类型** (TaskType):
- `DATA_PREPROCESS`: 数据预处理
- `FEATURE_ENGINEERING`: 特征工程
- `MODEL_TRAIN`: 模型训练
- `EDA`: 探索性数据分析
- `OTHER`: 其他任务

**任务结构**:
```json
[
    {
        "task_id": "1",
        "dependent_task_ids": [],
        "instruction": "编写 snake.py 实现蛇的移动逻辑",
        "task_type": "OTHER"
    },
    {
        "task_id": "2",
        "dependent_task_ids": ["1"],
        "instruction": "编写 game.py 实现游戏主循环",
        "task_type": "OTHER"
    }
]
```

**计划更新机制**:

```python
def update_plan_from_rsp(rsp: str, current_plan: Plan):
    """
    根据 LLM 响应更新计划

    支持三种更新模式:
    1. 替换现有任务
    2. 追加新任务
    3. 完全重建计划
    """
    rsp = json.loads(rsp)
    tasks = [Task(**task_config) for task_config in rsp]

    if len(tasks) == 1 or tasks[0].dependent_task_ids:
        # 单任务更新
        if current_plan.has_task_id(tasks[0].task_id):
            current_plan.replace_task(...)
        else:
            current_plan.append_task(...)
    else:
        # 批量添加任务
        current_plan.add_tasks(tasks)
```

#### WriteCode - 代码编写工具

**位置**: `metagpt/actions/write_code.py`

**功能**:
- 根据设计和任务编写代码
- 支持增量开发
- 处理调试日志和错误反馈

**核心实现**:

```python
class WriteCode(Action):
    name: str = "WriteCode"
    i_context: Document = Field(default_factory=Document)
    repo: Optional[ProjectRepo] = Field(default=None, exclude=True)

    async def run(self, *args, **kwargs) -> CodingContext:
        """
        编写代码的完整流程

        流程:
        1. 加载上下文 (设计文档、任务、已有代码)
        2. 加载测试结果和错误日志
        3. 构建提示词
        4. 生成代码
        5. 保存代码文档
        """
        # 加载编码上下文
        coding_context = CodingContext.loads(self.i_context.content)

        # 加载相关文档
        code_plan_and_change_doc = await self.repo.docs.code_plan_and_change.get(...)
        test_doc = await self.repo.test_outputs.get(...)
        requirement_doc = await Document.load(...)

        # 获取已有代码
        code_context = await self.get_codes(
            coding_context.task_doc,
            exclude=self.i_context.filename,
            project_repo=self.repo
        )

        # 构建提示词
        prompt = PROMPT_TEMPLATE.format(
            design=coding_context.design_doc.content,
            task=coding_context.task_doc.content,
            code=code_context,
            logs=logs,
            feedback=bug_feedback.content if bug_feedback else "",
            filename=self.i_context.filename,
            demo_filename=Path(self.i_context.filename).stem,
        )

        # 生成代码
        code = await self.write_code(prompt)

        # 保存代码
        coding_context.code_doc.content = code

        return coding_context
```

**代码生成提示词模板**:

```
NOTICE
Role: You are a professional engineer
Goal: Write google-style, elegant, modular code

# Context
## Design
{design}

## Task
{task}

## Legacy Code
{code}

## Debug logs
{logs}

## Bug Feedback logs
{feedback}

# Instruction: Based on the context, write code.
1. Only One file: implement THIS ONLY ONE FILE
2. COMPLETE CODE: implement complete, reliable, reusable code
3. Set default value: ALWAYS SET A DEFAULT VALUE
4. Follow design: MUST FOLLOW "Data structures and interfaces"
5. CAREFULLY CHECK: don't miss any necessary class/function
6. Import first: make sure you import external variable/module first
7. Write EVERY CODE DETAIL, DON'T LEAVE TODO
```

**重试机制**:

```python
@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
async def write_code(self, prompt) -> str:
    """
    使用 tenacity 库实现重试
    - 等待时间: 1-60秒随机指数退避
    - 最大重试: 6 次
    """
    code_rsp = await self._aask(prompt)
    code = CodeParser.parse_code(text=code_rsp)
    return code
```

#### RunCode - 代码执行工具

**功能**:
- 在沙箱环境中执行代码
- 捕获输出和错误
- 提供执行结果反馈

**实现** (ExecuteNbCode):
```python
class ExecuteNbCode:
    async def run(self, code: str) -> Tuple[str, bool]:
        """
        在 Jupyter Notebook 环境中执行代码

        Returns:
            (result, success): 执行结果和是否成功
        """
```

#### DebugError - 错误调试工具

**功能**:
- 分析执行错误
- 提供修复建议
- 自动重试机制

### 3. 工具推荐系统

**位置**: `metagpt/tools/tool_recommend.py`

**BM25ToolRecommender**:
```python
class BM25ToolRecommender(ToolRecommender):
    """
    基于 BM25 算法的工具推荐器

    工作原理:
    1. 对工具描述建立索引
    2. 根据当前任务上下文计算相似度
    3. 推荐最相关的工具
    """

    async def get_recommended_tool_info(
        self,
        context: str,
        plan: Plan = None
    ) -> str:
        """
        获取推荐工具信息

        Args:
            context: 当前上下文
            plan: 当前计划

        Returns:
            推荐工具的描述和使用方法
        """
```

### 4. 工作记忆 (Working Memory)

**作用**:
- 存储执行过程中的消息和状态
- 提供上下文给 LLM
- 支持思考链 (Chain of Thought)

**结构**:
```python
working_memory = [
    Message(content="用户需求: 编写贪吃蛇游戏", role="user"),
    Message(content="任务计划: ...", role="assistant"),
    Message(content="代码: ...", role="assistant"),
    Message(content="执行结果: ...", role="user"),
]
```

---

## 工作流程

### 完整流程图

```
1. 用户输入需求
   ↓
2. DataInterpreter 初始化
   - 加载工具: [WritePRD, WriteDesign, WritePlan, WriteCode, RunCode, DebugError]
   - 初始化工作记忆
   - 设置运行模式 (plan_and_act)
   ↓
3. WritePRD 工具执行
   - 分析需求类型 (新需求/更新/Bug修复)
   - 生成 PRD 文档
   - 保存 PRD (JSON + Markdown)
   - 生成竞品分析图
   ↓
4. WriteDesign 工具执行
   - 读取 PRD 文档
   - 生成系统架构设计
   - 定义数据结构和接口
   - 设计程序调用流程
   - 保存设计文档 (JSON + Markdown)
   - 生成类图和序列图
   ↓
5. WritePlan 工具执行
   - 读取设计文档
   - 分解为具体任务
   - 建立任务依赖关系
   - 生成任务列表
   ↓
6. WriteCode 工具执行 (循环执行每个任务)
   对于每个任务:
   - 读取设计文档和任务描述
   - 获取已有代码上下文
   - 生成代码
   - 保存代码文件
   ↓
7. RunCode 工具执行
   - 执行生成的代码
   - 捕获输出和错误
   ↓
8. DebugError 工具执行 (如果有错误)
   - 分析错误信息
   - 修改代码
   - 重新执行
   ↓
9. Git 提交 (可选)
   - 暂存所有更改
   - 创建提交
   ↓
10. 返回结果
```

### 详细执行流程

#### 第一阶段: 初始化

```python
# 1. 创建 DataInterpreter 实例
di = DataInterpreter(
    tools=[
        "WritePRD",      # 产品需求文档
        "WriteDesign",   # 系统设计
        "WritePlan",     # 项目计划
        "WriteCode",     # 代码编写
        "RunCode",       # 代码执行
        "DebugError",    # 错误调试
    ]
)

# 2. 设置运行模式
di.react_mode = "plan_and_act"  # 计划并执行模式
di.use_plan = True              # 启用计划
di.use_reflection = False       # 禁用反思 (可选)

# 3. 初始化工具推荐器
di.tool_recommender = BM25ToolRecommender(tools=di.tools)
```

#### 第二阶段: 执行任务

```python
# 4. 运行
await di.run(prompt)

# 内部执行流程:
# 4.1 进入 _plan_and_act 模式
async def _plan_and_act(self):
    # 4.2 创建计划
    plan = await self.planner.create_plan(self.user_requirement)

    # 4.3 执行每个任务
    for task in plan.tasks:
        # 4.4 设置当前任务
        self.planner.set_current_task(task)

        # 4.5 执行任务
        task_result = await self._act_on_task(task)

        # 4.6 更新任务结果
        task.result = task_result

        # 4.7 如果失败,重试或调整计划
        if not task_result.is_success:
            # 重新计划或调试
            ...
```

#### 第三阶段: 代码生成与执行

```python
# 在 _act_on_task 中
async def _act_on_task(self, current_task: Task) -> TaskResult:
    # 1. 编写并执行代码
    code, result, is_success = await self._write_and_exec_code()

    # 2. 包装结果
    task_result = TaskResult(
        code=code,
        result=result,
        is_success=is_success
    )

    return task_result

# _write_and_exec_code 的详细流程:
async def _write_and_exec_code(self, max_retry: int = 3):
    counter = 0
    success = False

    while not success and counter < max_retry:
        # 1. 获取工具推荐
        tool_info = await self.tool_recommender.get_recommended_tool_info(...)

        # 2. 编写代码
        code = await self._write_code(counter, plan_status, tool_info)

        # 3. 添加到工作记忆
        self.working_memory.add(Message(content=code, role="assistant"))

        # 4. 执行代码
        result, success = await self.execute_code.run(code)

        # 5. 添加执行结果到工作记忆
        self.working_memory.add(Message(content=result, role="user"))

        counter += 1

    return code, result, success
```

---

## 关键实现

### 1. 计划生成与管理

**Plan 类**:
```python
class Plan:
    tasks: List[Task] = []           # 任务列表
    current_task_id: str = ""        # 当前任务 ID

    def add_tasks(self, tasks: List[Task]):
        """添加任务"""

    def replace_task(self, task_id, ...):
        """替换任务"""

    def append_task(self, task_id, ...):
        """追加任务"""

    def get_finished_tasks(self) -> List[Task]:
        """获取已完成任务"""

    def get_current_task(self) -> Task:
        """获取当前任务"""
```

**Task 类**:
```python
class Task:
    task_id: str                     # 任务 ID
    dependent_task_ids: List[str]    # 依赖的任务 ID
    instruction: str                 # 任务指令
    task_type: str                   # 任务类型
    assignee: str = ""               # 分配给谁
    result: TaskResult = None        # 任务结果
```

### 2. 代码解析

**CodeParser**:
```python
class CodeParser:
    @staticmethod
    def parse_code(text: str, lang: str = "") -> str:
        """
        从 LLM 响应中解析代码块

        支持格式:
        ```python
        code here
        ```

        或

        ```json
        {"key": "value"}
        ```
        """
        # 使用正则表达式提取代码块
        pattern = r"```[\w]*\n(.*?)\n```"
        matches = re.findall(pattern, text, re.DOTALL)

        if matches:
            return matches[0]
        return text
```

### 3. 文档管理

**ProjectRepo**:
```python
class ProjectRepo:
    workdir: Path                    # 工作目录
    docs: FileRepository             # 文档仓库
    srcs: FileRepository             # 源代码仓库
    resources: FileRepository        # 资源仓库

    # 文档类型
    docs.prd                         # PRD 文档
    docs.system_design               # 系统设计文档
    docs.task                        # 任务文档
    docs.code_plan_and_change        # 代码计划和变更
    docs.code_summary                # 代码摘要

    # 资源类型
    resources.prd                    # PRD 资源 (Markdown, PDF)
    resources.system_design          # 设计资源
    resources.data_api_design        # 数据和 API 设计图
    resources.seq_flow               # 序列图
```

### 4. 消息传递

**Message**:
```python
class Message:
    content: str                     # 消息内容
    role: str                        # 角色 (user/assistant)
    cause_by: Action                 # 由哪个 Action 产生
    sent_from: str = ""              # 发送者
    send_to: str = ""                # 接收者
    instruct_content: BaseModel      # 结构化指令内容
```

### 5. 成本管理

**CostManager**:
```python
class CostManager:
    max_budget: float = 10.0         # 最大预算
    total_cost: float = 0.0          # 总成本

    def update_cost(self, cost: float):
        """更新成本"""
        self.total_cost += cost

    def is_budget_exceeded(self) -> bool:
        """检查预算是否超支"""
        return self.total_cost >= self.max_budget
```

---

## 使用示例

### 基本使用

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
import fire
from metagpt.roles.di.data_interpreter import DataInterpreter

async def main():
    # 定义需求
    prompt = """
This is a software requirement:
```text
write a snake game
```
---
1. Writes a PRD based on software requirements.
2. Writes a design to the project repository, based on the PRD of the project.
3. Writes a project plan to the project repository, based on the design of the project.
4. Writes codes to the project repository, based on the project plan of the project.
5. Run QA test on the project repository.
6. Stage and commit changes for the project repository using Git.
Note: All required dependencies and environments have been fully installed and configured.
"""

    # 创建 DataInterpreter
    di = DataInterpreter(
        tools=[
            "WritePRD",
            "WriteDesign",
            "WritePlan",
            "WriteCode",
            "RunCode",
            "DebugError",
        ]
    )

    # 执行
    await di.run(prompt)

if __name__ == "__main__":
    fire.Fire(main)
```

### 高级配置

```python
# 使用反思机制
di = DataInterpreter(
    tools=[...],
    use_reflection=True,      # 启用反思
    max_react_loop=20,        # 增加最大循环次数
)

# 使用 react 模式
di = DataInterpreter(
    tools=[...],
    react_mode="react",       # 边思考边行动
    auto_run=True,
)

# 自定义 LLM 配置
from metagpt.config import Config
from metagpt.context import Context

config = Config.default()
config.llm.model = "gpt-4"
config.llm.temperature = 0.7

context = Context(config=config)
di = DataInterpreter(tools=[...], context=context)
```

### 执行输出示例

```
初始化 DataInterpreter...
工具: ['WritePRD', 'WriteDesign', 'WritePlan', 'WriteCode', 'RunCode', 'DebugError']

[Step 1/6] 执行 WritePRD
生成 PRD 文档...
保存到: workspace/snake_game/docs/prd.json
生成竞品分析图: workspace/snake_game/resources/competitive_analysis/prd.svg
✓ WritePRD 完成

[Step 2/6] 执行 WriteDesign
读取 PRD: workspace/snake_game/docs/prd.json
生成系统设计...
保存到: workspace/snake_game/docs/system_design.json
生成类图: workspace/snake_game/resources/data_api_design/system_design.svg
生成序列图: workspace/snake_game/resources/seq_flow/system_design.svg
✓ WriteDesign 完成

[Step 3/6] 执行 WritePlan
读取设计文档...
生成任务计划...
任务列表:
  - Task 1: 实现 Snake 类
  - Task 2: 实现 Food 类
  - Task 3: 实现 Game 类
  - Task 4: 实现主程序
✓ WritePlan 完成

[Step 4/6] 执行 WriteCode
[Task 1/4] 编写 snake.py...
保存到: workspace/snake_game/snake_game/snake.py
✓ Task 1 完成

[Task 2/4] 编写 food.py...
保存到: workspace/snake_game/snake_game/food.py
✓ Task 2 完成

[Task 3/4] 编写 game.py...
保存到: workspace/snake_game/snake_game/game.py
✓ Task 3 完成

[Task 4/4] 编写 main.py...
保存到: workspace/snake_game/snake_game/main.py
✓ Task 4 完成
✓ WriteCode 完成

[Step 5/6] 执行 RunCode
执行 main.py...
输出:
  Snake Game Started!
  Score: 0
  ...
✓ RunCode 完成

[Step 6/6] Git 提交
暂存文件: 15 个文件
创建提交: "feat: implement snake game"
✓ Git 提交完成

全部完成! 🎉
项目路径: workspace/snake_game/
```

---

## 技术细节

### 1. Action Node 系统

Action Node 是 MetaGPT 中用于结构化输出的核心机制：

```python
# 定义 PRD 的输出结构
WRITE_PRD_NODE = ActionNode(
    key="PRD",
    expected_type=str,
    instruction="根据用户需求编写 PRD",
    example="...",
    schema={
        "Project Name": str,
        "Goals": List[str],
        "Requirements": List[str],
        "User Stories": List[str],
        ...
    }
)

# 使用 ActionNode
node = await WRITE_PRD_NODE.fill(req=context, llm=self.llm)
prd_content = node.instruct_content.model_dump_json()
```

### 2. 增量开发支持

Software Company 支持增量开发，可以在现有项目基础上添加新功能：

```python
# 检测是否为增量开发
if self.config.inc or bug_feedback:
    code_context = await self.get_codes(
        coding_context.task_doc,
        exclude=self.i_context.filename,
        project_repo=self.repo,
        use_inc=True  # 启用增量模式
    )
```

增量模式下:
- 保留现有代码
- 只修改变更部分
- 避免破坏已有功能

### 3. 错误处理与重试

多层次的错误处理:

1. **代码生成重试**
   ```python
   @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
   async def write_code(self, prompt) -> str:
       # 最多重试 6 次
   ```

2. **代码执行重试**
   ```python
   async def _write_and_exec_code(self, max_retry: int = 3):
       while not success and counter < max_retry:
           # 最多重试 3 次
   ```

3. **任务级重试**
   ```python
   # 如果任务失败,可以重新规划
   if not task_result.is_success:
       new_plan = await self.planner.revise_plan(...)
   ```

### 4. 流式输出

支持实时查看 LLM 生成过程:

```python
async with DocsReporter(enable_llm_stream=True) as reporter:
    await reporter.async_report({"type": "prd"}, "meta")
    node = await self._new_prd(requirement=req.content)
    # 实时显示生成的 PRD 内容
    await reporter.async_report(prd_path, "path")
```

### 5. 文档版本管理

使用 Git 管理文档变更:

```python
class FileRepository:
    changed_files: Dict[str, Document] = {}  # 变更的文件
    all_files: List[str] = []                # 所有文件

    async def save(self, filename: str, content: str, dependencies: Set[str] = None):
        """
        保存文件并跟踪依赖

        Args:
            filename: 文件名
            content: 文件内容
            dependencies: 依赖的文件路径集合
        """
        # 保存文件
        await awrite(self.workdir / filename, content)

        # 标记为已变更
        self.changed_files[filename] = Document(
            filename=filename,
            content=content,
            dependencies=dependencies
        )
```

### 6. Mermaid 图表生成

自动生成可视化图表:

```python
async def mermaid_to_file(engine: str, mermaid_code: str, output_path: Path):
    """
    将 Mermaid 代码转换为图片

    支持的引擎:
    - mermaid-cli: 命令行工具
    - playwright: 浏览器渲染
    - pyppeteer: 无头浏览器
    """
    if engine == "mermaid-cli":
        # 使用 mmdc 命令
        cmd = f"mmdc -i {input_file} -o {output_path}.svg"
        await subprocess.run(cmd, shell=True)
    elif engine == "playwright":
        # 使用 Playwright 渲染
        ...
```

### 7. 工具注册系统

工具通过装饰器自动注册:

```python
@register_tool(include_functions=["run"])
class WritePRD(Action):
    """
    注册为可调用工具

    include_functions: 指定哪些方法可以被调用
    """

    async def run(self, ...):
        # 这个方法可以被 DataInterpreter 调用
        ...
```

注册后的工具可以通过名称调用:

```python
tools = ["WritePRD", "WriteDesign", ...]
# DataInterpreter 会自动查找并加载这些工具
```

---

## 总结

### Software Company 的优势

1. **全自动化**: 从需求到代码一站式生成
2. **结构化输出**: 使用 JSON Schema 确保输出格式正确
3. **可扩展性**: 易于添加新工具和功能
4. **错误恢复**: 多层次的重试和调试机制
5. **可视化**: 自动生成架构图和流程图
6. **版本控制**: 集成 Git 管理代码变更

### 适用场景

1. **快速原型开发**: 快速验证想法
2. **代码生成**: 自动生成样板代码
3. **文档生成**: 自动生成技术文档
4. **教学演示**: 展示软件开发流程
5. **测试数据生成**: 生成测试用例和数据

### 局限性

1. **复杂项目**: 对于大型复杂项目,生成的代码可能需要人工调整
2. **依赖 LLM**: 质量依赖于 LLM 的能力
3. **成本**: 大量 API 调用可能产生较高成本
4. **特定领域**: 某些特定领域的需求可能处理不佳

### 最佳实践

1. **清晰的需求**: 提供详细、明确的需求描述
2. **合理的预期**: 理解 AI 生成代码的局限性
3. **人工审查**: 对生成的代码进行审查和测试
4. **迭代改进**: 通过反馈不断优化生成结果
5. **成本控制**: 合理设置预算和重试次数

---

## 参考资料

- [MetaGPT 官方文档](https://docs.deepwisdom.ai/)
- [Data Interpreter 论文](https://arxiv.org/abs/2402.18679)
- [MetaGPT GitHub](https://github.com/geekan/MetaGPT)
- [示例代码](https://github.com/geekan/MetaGPT/tree/main/examples/di)

---

**文档版本**: 1.0
**最后更新**: 2025-11-16
**作者**: Claude
**项目**: MetaGPT Software Company
