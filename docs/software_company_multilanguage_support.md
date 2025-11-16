# Software Company - 多语言支持扩展指南

## 目录

1. [概述](#概述)
2. [当前限制](#当前限制)
3. [扩展方案对比](#扩展方案对比)
4. [方案一：Jupyter 多 Kernel 支持](#方案一jupyter-多-kernel-支持)
5. [方案二：Subprocess 直接执行](#方案二subprocess-直接执行)
6. [方案三：Docker 容器化执行（推荐）](#方案三docker-容器化执行推荐)
7. [方案四：混合执行策略](#方案四混合执行策略)
8. [集成到 DataInterpreter](#集成到-datainterpreter)
9. [使用示例](#使用示例)
10. [部署指南](#部署指南)
11. [最佳实践](#最佳实践)

---

## 概述

### 当前状态

MetaGPT 的 Software Company 当前主要支持 **Python** 代码的执行，通过 Jupyter Kernel 实现。虽然可以生成多种语言的代码文件，但无法直接执行 Python 以外的语言。

### 扩展目标

本文档提供多种方案，使 Software Company 能够：
- ✅ 执行 JavaScript/TypeScript (Node.js)
- ✅ 执行 Java
- ✅ 执行 Go
- ✅ 执行 Rust
- ✅ 执行 C/C++
- ✅ 执行 Shell 脚本
- ✅ 支持混合语言项目

---

## 当前限制

### ExecuteNbCode 的语言限制

**源码位置**: `metagpt/actions/di/execute_nb_code.py:246`

```python
async def run(self, code: str, language: Literal["python", "markdown"] = "python"):
    if language == "python":
        # ✅ 支持执行
        ...
    elif language == "markdown":
        # ⚠️ 只添加文档，不执行
        ...
    else:
        # ❌ 抛出异常
        raise ValueError(f"Only support for language: python, markdown, but got {language}")
```

### 限制原因

1. **硬编码的 Kernel**: 只启动 Python Kernel
2. **缺少语言检测**: 无法根据代码类型选择执行器
3. **没有编译器支持**: 缺少 Java、C++ 等编译型语言的支持
4. **环境依赖**: 没有自动安装运行时的机制

---

## 扩展方案对比

| 方案 | 优势 | 劣势 | 适用场景 | 难度 |
|-----|------|------|---------|------|
| **Jupyter 多 Kernel** | 统一接口、支持交互式执行 | 需要安装各语言 Kernel、配置复杂 | 数据分析、探索式开发 | ⭐⭐⭐ |
| **Subprocess 执行** | 实现简单、资源消耗小 | 隔离性差、无交互式支持 | 简单脚本、快速原型 | ⭐ |
| **Docker 容器化** | 完全隔离、易于部署、支持所有语言 | 资源消耗大、启动慢 | 生产环境、多租户 | ⭐⭐⭐⭐ |
| **混合策略** | 灵活、性能好 | 维护复杂 | 复杂项目 | ⭐⭐⭐⭐⭐ |

---

## 方案一：Jupyter 多 Kernel 支持

### 原理

Jupyter 生态系统提供了多种语言的 Kernel：
- **IJavaScript** - JavaScript/TypeScript
- **IJava** - Java
- **IRkernel** - R
- **IScala** - Scala
- **Golang Kernel** - Go
- **Rust Kernel** - Rust

### 1.1 安装语言 Kernel

#### JavaScript/Node.js Kernel

```bash
# 安装 Node.js (如果未安装)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# 安装 IJavaScript Kernel
npm install -g ijavascript
ijsinstall

# 验证安装
jupyter kernelspec list
```

#### Java Kernel

```bash
# 方案 A: 使用 IJava
wget https://github.com/SpencerPark/IJava/releases/download/v1.3.0/ijava-1.3.0.zip
unzip ijava-1.3.0.zip -d ijava-kernel
cd ijava-kernel
python install.py --sys-prefix

# 方案 B: 使用 Rapaio Kernel (更现代)
wget https://github.com/padreati/rapaio-jupyter-kernel/releases/download/2.0.0/rapaio-jupyter-kernel-2.0.0.jar
java -jar rapaio-jupyter-kernel-2.0.0.jar --install
```

#### Go Kernel

```bash
# 安装 Go
wget https://go.dev/dl/go1.21.5.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf go1.21.5.linux-amd64.tar.gz
export PATH=$PATH:/usr/local/go/bin

# 安装 gophernotes
go install github.com/gopherdata/gophernotes@latest
mkdir -p ~/.local/share/jupyter/kernels/gophernotes
cp "$(go env GOPATH)"/pkg/mod/github.com/gopherdata/gophernotes*/kernel/* \
   ~/.local/share/jupyter/kernels/gophernotes
```

#### Rust Kernel

```bash
# 安装 Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 安装 Evcxr Jupyter Kernel
cargo install evcxr_jupyter
evcxr_jupyter --install
```

### 1.2 实现多 Kernel 执行器

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多语言 Jupyter Kernel 执行器
文件: metagpt/actions/di/execute_multi_kernel.py
"""
from __future__ import annotations

import re
from typing import Literal, Tuple, Optional
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_notebook

from metagpt.actions.di.execute_nb_code import (
    ExecuteNbCode,
    RealtimeOutputNotebookClient,
)
from metagpt.logs import logger


class MultiKernelExecutor(ExecuteNbCode):
    """支持多语言的 Jupyter Kernel 执行器"""

    # 语言到 Kernel 的映射
    KERNEL_MAPPING = {
        "python": "python3",
        "javascript": "javascript",
        "typescript": "javascript",  # TypeScript 通过 ts-node
        "java": "java",
        "golang": "gophernotes",
        "go": "gophernotes",
        "rust": "rust",
        "r": "ir",
        "scala": "scala",
        "julia": "julia-1.9",
    }

    # 语言文件扩展名
    LANGUAGE_EXTENSIONS = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "java": ".java",
        "golang": ".go",
        "rust": ".rs",
        "r": ".r",
        "scala": ".scala",
        "julia": ".jl",
    }

    def __init__(
        self,
        kernel_name: str = "python3",
        language: str = "python",
        timeout: int = 600,
        *args,
        **kwargs
    ):
        """
        初始化多语言执行器

        Args:
            kernel_name: Jupyter Kernel 名称
            language: 编程语言名称
            timeout: 超时时间（秒）
        """
        self.kernel_name = kernel_name
        self.language = language.lower()

        # 创建新的 notebook
        nb = new_notebook(
            metadata={
                "kernelspec": {
                    "name": kernel_name,
                    "display_name": kernel_name,
                    "language": language,
                },
                "language_info": {"name": language},
            }
        )

        super().__init__(nb=nb, timeout=timeout, *args, **kwargs)

    @classmethod
    def from_language(cls, language: str, timeout: int = 600) -> "MultiKernelExecutor":
        """
        根据语言名称创建执行器

        Args:
            language: 编程语言名称

        Returns:
            MultiKernelExecutor 实例
        """
        language = language.lower()
        kernel_name = cls.KERNEL_MAPPING.get(language)

        if not kernel_name:
            raise ValueError(
                f"Unsupported language: {language}. "
                f"Supported languages: {list(cls.KERNEL_MAPPING.keys())}"
            )

        return cls(kernel_name=kernel_name, language=language, timeout=timeout)

    @staticmethod
    def detect_language(code: str, filename: str = "") -> str:
        """
        自动检测代码语言

        Args:
            code: 代码内容
            filename: 文件名（可选）

        Returns:
            检测到的语言名称
        """
        # 首先尝试从文件扩展名检测
        if filename:
            ext = Path(filename).suffix.lower()
            ext_to_lang = {
                ".py": "python",
                ".js": "javascript",
                ".ts": "typescript",
                ".java": "java",
                ".go": "golang",
                ".rs": "rust",
                ".r": "r",
                ".scala": "scala",
                ".jl": "julia",
            }
            if ext in ext_to_lang:
                return ext_to_lang[ext]

        # 从代码特征检测
        code_lower = code.lower().strip()

        # Python
        if re.search(r"(import |from .+ import |def |class |print\()", code):
            return "python"

        # JavaScript/TypeScript
        if re.search(r"(const |let |var |function |console\.log|=>|async |await )", code):
            if "interface " in code or "type " in code or ": string" in code:
                return "typescript"
            return "javascript"

        # Java
        if re.search(r"(public class|private |protected |public static void main)", code):
            return "java"

        # Go
        if re.search(r"(package |func |import \(|fmt\.)", code):
            return "golang"

        # Rust
        if re.search(r"(fn |let mut|impl |pub |use |println!)", code):
            return "rust"

        # R
        if re.search(r"(<-|library\(|data\.frame|ggplot)", code):
            return "r"

        # 默认返回 Python
        logger.warning(f"Cannot detect language, defaulting to Python")
        return "python"

    def set_nb_client(self):
        """设置指定 Kernel 的 Notebook Client"""
        self.nb_client = RealtimeOutputNotebookClient(
            self.nb,
            timeout=self.timeout,
            kernel_name=self.kernel_name,  # 指定 kernel
            resources={"metadata": {"path": self.config.workspace.path}},
            notebook_reporter=self.reporter,
            coalesce_streams=True,
        )

    async def run(
        self, code: str, language: Optional[str] = None, filename: str = ""
    ) -> Tuple[str, bool]:
        """
        执行代码

        Args:
            code: 代码内容
            language: 语言类型（可选，会自动检测）
            filename: 文件名（帮助检测语言）

        Returns:
            (输出结果, 是否成功)
        """
        # 如果指定了语言，切换到对应的 kernel
        if language and language != self.language:
            detected_lang = language.lower()
        else:
            # 自动检测语言
            detected_lang = self.detect_language(code, filename)

        # 如果检测到的语言与当前不同，需要重新初始化
        if detected_lang != self.language:
            logger.info(f"Switching kernel from {self.language} to {detected_lang}")
            kernel_name = self.KERNEL_MAPPING.get(detected_lang)
            if kernel_name:
                self.kernel_name = kernel_name
                self.language = detected_lang
                self.nb.metadata["kernelspec"]["name"] = kernel_name
                self.nb.metadata["kernelspec"]["language"] = detected_lang
                await self.reset()  # 重启 kernel

        # 执行代码
        return await super().run(code, language="python")  # 使用父类的 run 方法

    async def run_file(self, filepath: str) -> Tuple[str, bool]:
        """
        执行代码文件

        Args:
            filepath: 代码文件路径

        Returns:
            (输出结果, 是否成功)
        """
        filepath = Path(filepath)
        if not filepath.exists():
            return f"File not found: {filepath}", False

        code = filepath.read_text(encoding="utf-8")
        return await self.run(code, filename=str(filepath))


# 便捷的语言特定执行器
class JavaScriptExecutor(MultiKernelExecutor):
    """JavaScript 执行器"""

    def __init__(self, timeout: int = 600):
        super().__init__(kernel_name="javascript", language="javascript", timeout=timeout)


class JavaExecutor(MultiKernelExecutor):
    """Java 执行器"""

    def __init__(self, timeout: int = 600):
        super().__init__(kernel_name="java", language="java", timeout=timeout)


class GoExecutor(MultiKernelExecutor):
    """Go 执行器"""

    def __init__(self, timeout: int = 600):
        super().__init__(kernel_name="gophernotes", language="golang", timeout=timeout)


class RustExecutor(MultiKernelExecutor):
    """Rust 执行器"""

    def __init__(self, timeout: int = 600):
        super().__init__(kernel_name="rust", language="rust", timeout=timeout)
```

### 1.3 使用示例

```python
from metagpt.actions.di.execute_multi_kernel import MultiKernelExecutor

# 自动检测语言并执行
executor = MultiKernelExecutor.from_language("javascript")

# 执行 JavaScript
js_code = """
const arr = [1, 2, 3, 4, 5];
const squared = arr.map(x => x * x);
console.log('Squared:', squared);

const sum = arr.reduce((a, b) => a + b, 0);
console.log('Sum:', sum);
"""
output, success = await executor.run(js_code)
print(f"Success: {success}")
print(f"Output: {output}")

# 执行 Java
java_executor = MultiKernelExecutor.from_language("java")
java_code = """
List<Integer> numbers = Arrays.asList(1, 2, 3, 4, 5);
int sum = numbers.stream().mapToInt(Integer::intValue).sum();
System.out.println("Sum: " + sum);
"""
output, success = await java_executor.run(java_code)

# 自动检测语言
auto_executor = MultiKernelExecutor()
code = """
package main
import "fmt"

func main() {
    fmt.Println("Hello from Go!")
}
"""
# 会自动检测为 Go 并切换 kernel
output, success = await auto_executor.run(code)
```

---

## 方案二：Subprocess 直接执行

### 原理

直接使用 `subprocess` 调用各语言的解释器/编译器。

### 2.1 实现通用执行器

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
基于 Subprocess 的多语言执行器
文件: metagpt/actions/di/execute_subprocess.py
"""
import asyncio
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Dict, Optional

from metagpt.actions import Action
from metagpt.logs import logger


class SubprocessLanguageExecutor(Action):
    """使用 subprocess 执行多种语言的代码"""

    # 语言配置
    LANGUAGE_CONFIG: Dict[str, dict] = {
        "python": {
            "extension": ".py",
            "command": ["python3", "{file}"],
            "compile": None,
        },
        "javascript": {
            "extension": ".js",
            "command": ["node", "{file}"],
            "compile": None,
        },
        "typescript": {
            "extension": ".ts",
            "command": ["ts-node", "{file}"],
            "compile": None,
        },
        "java": {
            "extension": ".java",
            "command": ["java", "{class}"],
            "compile": ["javac", "{file}"],
            "extract_class": r"public\s+class\s+(\w+)",
        },
        "golang": {
            "extension": ".go",
            "command": ["go", "run", "{file}"],
            "compile": None,
        },
        "rust": {
            "extension": ".rs",
            "command": ["{exe}"],
            "compile": ["rustc", "{file}", "-o", "{exe}"],
        },
        "c": {
            "extension": ".c",
            "command": ["{exe}"],
            "compile": ["gcc", "{file}", "-o", "{exe}"],
        },
        "cpp": {
            "extension": ".cpp",
            "command": ["{exe}"],
            "compile": ["g++", "{file}", "-o", "{exe}"],
        },
        "shell": {
            "extension": ".sh",
            "command": ["bash", "{file}"],
            "compile": None,
        },
    }

    def __init__(self, timeout: int = 30, workspace: Optional[Path] = None):
        super().__init__()
        self.timeout = timeout
        self.workspace = workspace or Path(tempfile.mkdtemp())
        self.workspace.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def detect_language(code: str, filename: str = "") -> str:
        """检测代码语言"""
        if filename:
            ext = Path(filename).suffix
            for lang, config in SubprocessLanguageExecutor.LANGUAGE_CONFIG.items():
                if ext == config["extension"]:
                    return lang

        # 代码特征检测（与方案一相同）
        code_lower = code.strip()

        if re.search(r"#include\s*<|int\s+main\(", code_lower):
            if ".cpp" in filename or "std::" in code_lower:
                return "cpp"
            return "c"

        if re.search(r"(import |from .+ import |def |class )", code):
            return "python"

        if re.search(r"(const |let |var |console\.log|=>)", code):
            return "javascript"

        if re.search(r"package main|func main\(", code):
            return "golang"

        if re.search(r"fn main\(|println!", code):
            return "rust"

        if re.search(r"public\s+class|public\s+static\s+void\s+main", code):
            return "java"

        if re.search(r"^#!/bin/(bash|sh)", code):
            return "shell"

        return "python"  # 默认

    async def execute(
        self, code: str, language: Optional[str] = None, filename: str = ""
    ) -> Tuple[str, bool]:
        """
        执行代码

        Args:
            code: 代码内容
            language: 语言类型（可选）
            filename: 文件名（可选）

        Returns:
            (输出, 是否成功)
        """
        # 检测语言
        if not language:
            language = self.detect_language(code, filename)

        if language not in self.LANGUAGE_CONFIG:
            return f"Unsupported language: {language}", False

        config = self.LANGUAGE_CONFIG[language]

        try:
            # 生成文件名
            if filename:
                base_name = Path(filename).stem
            else:
                base_name = "main"

            # 对于 Java，需要从代码中提取类名
            if language == "java" and "extract_class" in config:
                match = re.search(config["extract_class"], code)
                if match:
                    base_name = match.group(1)

            # 保存代码到文件
            code_file = self.workspace / f"{base_name}{config['extension']}"
            code_file.write_text(code, encoding="utf-8")

            # 编译（如果需要）
            if config.get("compile"):
                exe_file = self.workspace / base_name
                compile_cmd = [
                    arg.format(file=str(code_file), exe=str(exe_file), class=base_name)
                    for arg in config["compile"]
                ]

                logger.info(f"Compiling: {' '.join(compile_cmd)}")
                compile_process = await asyncio.create_subprocess_exec(
                    *compile_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.workspace,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        compile_process.communicate(), timeout=self.timeout
                    )
                except asyncio.TimeoutError:
                    compile_process.kill()
                    return "Compilation timeout", False

                if compile_process.returncode != 0:
                    return f"Compilation failed:\n{stderr.decode()}", False

            # 执行
            exe_file = self.workspace / base_name
            run_cmd = [
                arg.format(file=str(code_file), exe=str(exe_file), class=base_name)
                for arg in config["command"]
            ]

            logger.info(f"Executing: {' '.join(run_cmd)}")
            exec_process = await asyncio.create_subprocess_exec(
                *run_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    exec_process.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                exec_process.kill()
                return "Execution timeout", False

            output = stdout.decode() + stderr.decode()
            success = exec_process.returncode == 0

            return output, success

        except Exception as e:
            logger.error(f"Execution error: {e}")
            return f"Error: {str(e)}", False

    async def run(self, code: str, **kwargs) -> Tuple[str, bool]:
        """Action 接口实现"""
        return await self.execute(code, **kwargs)
```

### 2.2 使用示例

```python
from metagpt.actions.di.execute_subprocess import SubprocessLanguageExecutor

executor = SubprocessLanguageExecutor(timeout=10)

# 执行 JavaScript
js_code = """
console.log('Hello from JavaScript!');
const numbers = [1, 2, 3, 4, 5];
console.log('Sum:', numbers.reduce((a, b) => a + b, 0));
"""
output, success = await executor.execute(js_code, language="javascript")
print(output)

# 执行 Go
go_code = """
package main
import "fmt"

func main() {
    fmt.Println("Hello from Go!")
    sum := 0
    for i := 1; i <= 5; i++ {
        sum += i
    }
    fmt.Printf("Sum: %d\\n", sum)
}
"""
output, success = await executor.execute(go_code, language="golang")
print(output)

# 执行 Rust
rust_code = """
fn main() {
    println!("Hello from Rust!");
    let numbers = vec![1, 2, 3, 4, 5];
    let sum: i32 = numbers.iter().sum();
    println!("Sum: {}", sum);
}
"""
output, success = await executor.execute(rust_code, language="rust")
print(output)

# 自动检测语言
cpp_code = """
#include <iostream>
#include <vector>
#include <numeric>

int main() {
    std::cout << "Hello from C++!" << std::endl;
    std::vector<int> numbers = {1, 2, 3, 4, 5};
    int sum = std::accumulate(numbers.begin(), numbers.end(), 0);
    std::cout << "Sum: " << sum << std::endl;
    return 0;
}
"""
output, success = await executor.execute(cpp_code)  # 自动检测为 C++
print(output)
```

---

## 方案三：Docker 容器化执行（推荐）

### 原理

使用 Docker 容器提供完全隔离的执行环境，支持所有语言。

### 3.1 实现容器化执行器

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
基于 Docker 的多语言执行器
文件: metagpt/actions/di/execute_docker.py
"""
import asyncio
import tempfile
from pathlib import Path
from typing import Tuple, Dict, Optional

try:
    import docker
    from docker.errors import ImageNotFound, ContainerError
except ImportError:
    raise ImportError("Please install docker: pip install docker")

from metagpt.actions import Action
from metagpt.logs import logger


class DockerLanguageExecutor(Action):
    """使用 Docker 容器执行多种语言的代码"""

    # 语言到 Docker 镜像的映射
    LANGUAGE_IMAGES: Dict[str, dict] = {
        "python": {
            "image": "python:3.11-slim",
            "command": "python /workspace/main.py",
            "extension": ".py",
            "filename": "main.py",
        },
        "javascript": {
            "image": "node:18-alpine",
            "command": "node /workspace/main.js",
            "extension": ".js",
            "filename": "main.js",
        },
        "typescript": {
            "image": "node:18-alpine",
            "command": "sh -c 'npm install -g ts-node typescript && ts-node /workspace/main.ts'",
            "extension": ".ts",
            "filename": "main.ts",
        },
        "java": {
            "image": "openjdk:17-alpine",
            "command": "sh -c 'cd /workspace && javac Main.java && java Main'",
            "extension": ".java",
            "filename": "Main.java",
        },
        "golang": {
            "image": "golang:1.21-alpine",
            "command": "go run /workspace/main.go",
            "extension": ".go",
            "filename": "main.go",
        },
        "rust": {
            "image": "rust:1.74-alpine",
            "command": "sh -c 'rustc /workspace/main.rs -o /workspace/main && /workspace/main'",
            "extension": ".rs",
            "filename": "main.rs",
        },
        "c": {
            "image": "gcc:13-alpine",
            "command": "sh -c 'gcc /workspace/main.c -o /workspace/main && /workspace/main'",
            "extension": ".c",
            "filename": "main.c",
        },
        "cpp": {
            "image": "gcc:13-alpine",
            "command": "sh -c 'g++ /workspace/main.cpp -o /workspace/main && /workspace/main'",
            "extension": ".cpp",
            "filename": "main.cpp",
        },
        "ruby": {
            "image": "ruby:3.2-alpine",
            "command": "ruby /workspace/main.rb",
            "extension": ".rb",
            "filename": "main.rb",
        },
        "php": {
            "image": "php:8.2-cli-alpine",
            "command": "php /workspace/main.php",
            "extension": ".php",
            "filename": "main.php",
        },
    }

    def __init__(
        self,
        timeout: int = 60,
        memory_limit: str = "512m",
        cpu_quota: int = 50000,  # 50% CPU
        enable_network: bool = True,
        workspace: Optional[Path] = None,
    ):
        """
        初始化 Docker 执行器

        Args:
            timeout: 超时时间（秒）
            memory_limit: 内存限制（如 "512m", "1g"）
            cpu_quota: CPU 配额（100000 = 100%）
            enable_network: 是否启用网络
            workspace: 工作目录
        """
        super().__init__()
        self.docker_client = docker.from_env()
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.enable_network = enable_network
        self.workspace = workspace or Path(tempfile.mkdtemp())
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        code: str,
        language: str = "python",
        image: Optional[str] = None,
        command: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """
        在 Docker 容器中执行代码

        Args:
            code: 代码内容
            language: 编程语言
            image: Docker 镜像（可选，默认使用预定义镜像）
            command: 执行命令（可选，默认使用预定义命令）

        Returns:
            (输出, 是否成功)
        """
        if language not in self.LANGUAGE_IMAGES and not image:
            return f"Unsupported language: {language}", False

        config = self.LANGUAGE_IMAGES.get(language, {})
        image = image or config.get("image")
        command = command or config.get("command")
        filename = config.get("filename", "main.txt")

        # 保存代码到工作目录
        code_file = self.workspace / filename
        code_file.write_text(code, encoding="utf-8")

        try:
            # 拉取镜像（如果不存在）
            try:
                self.docker_client.images.get(image)
            except ImageNotFound:
                logger.info(f"Pulling image: {image}")
                self.docker_client.images.pull(image)

            # 运行容器
            logger.info(f"Running container with image: {image}")
            container = self.docker_client.containers.run(
                image=image,
                command=command,
                volumes={str(self.workspace): {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                mem_limit=self.memory_limit,
                cpu_quota=self.cpu_quota,
                network_mode="bridge" if self.enable_network else "none",
                detach=True,
                remove=False,  # 保留容器以获取日志
                stdout=True,
                stderr=True,
            )

            # 等待容器执行完成
            try:
                result = container.wait(timeout=self.timeout)
                exit_code = result["StatusCode"]

                # 获取输出
                logs = container.logs(stdout=True, stderr=True).decode("utf-8")

                # 清理容器
                container.remove(force=True)

                success = exit_code == 0
                return logs, success

            except Exception as e:
                # 超时或其他错误，强制停止容器
                container.stop(timeout=1)
                container.remove(force=True)
                return f"Container execution failed: {str(e)}", False

        except ContainerError as e:
            logger.error(f"Container error: {e}")
            return f"Container error: {e.stderr.decode()}", False
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return f"Error: {str(e)}", False

    async def run(self, code: str, **kwargs) -> Tuple[str, bool]:
        """Action 接口实现"""
        return await self.execute(code, **kwargs)

    async def execute_project(
        self, project_path: Path, language: str, entry_file: str = None
    ) -> Tuple[str, bool]:
        """
        执行整个项目

        Args:
            project_path: 项目目录
            language: 编程语言
            entry_file: 入口文件（可选）

        Returns:
            (输出, 是否成功)
        """
        config = self.LANGUAGE_IMAGES.get(language)
        if not config:
            return f"Unsupported language: {language}", False

        # 构建项目特定的命令
        if language == "javascript" and (project_path / "package.json").exists():
            command = "sh -c 'npm install && npm start'"
        elif language == "python" and (project_path / "requirements.txt").exists():
            command = "sh -c 'pip install -r requirements.txt && python main.py'"
        else:
            command = config.get("command")

        image = config.get("image")

        try:
            container = self.docker_client.containers.run(
                image=image,
                command=command,
                volumes={str(project_path): {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                mem_limit=self.memory_limit,
                cpu_quota=self.cpu_quota,
                network_mode="bridge" if self.enable_network else "none",
                detach=True,
                remove=False,
            )

            result = container.wait(timeout=self.timeout)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8")
            container.remove(force=True)

            success = result["StatusCode"] == 0
            return logs, success

        except Exception as e:
            return f"Error: {str(e)}", False

    def cleanup(self):
        """清理资源"""
        # 清理临时文件
        import shutil

        if self.workspace.exists():
            shutil.rmtree(self.workspace)
```

### 3.2 使用示例

```python
from metagpt.actions.di.execute_docker import DockerLanguageExecutor

# 创建执行器（限制资源）
executor = DockerLanguageExecutor(
    timeout=30,
    memory_limit="1g",
    cpu_quota=100000,  # 100% CPU
    enable_network=True
)

# 执行 Python
python_code = """
import sys
print(f"Python version: {sys.version}")
print("Hello from Docker!")
"""
output, success = await executor.execute(python_code, language="python")
print(f"Success: {success}")
print(f"Output:\n{output}")

# 执行 JavaScript
js_code = """
console.log('Node.js version:', process.version);
console.log('Hello from Docker!');

const fetch = require('node-fetch');
// 可以访问网络（如果 enable_network=True）
"""
output, success = await executor.execute(js_code, language="javascript")

# 执行 Rust
rust_code = """
fn main() {
    println!("Hello from Rust in Docker!");
    let numbers: Vec<i32> = (1..=10).collect();
    let sum: i32 = numbers.iter().sum();
    println!("Sum of 1-10: {}", sum);
}
"""
output, success = await executor.execute(rust_code, language="rust")

# 执行整个项目
project_path = Path("/path/to/project")
output, success = await executor.execute_project(
    project_path,
    language="javascript",
)

# 清理
executor.cleanup()
```

---

## 方案四：混合执行策略

### 原理

根据不同场景选择最优执行方式。

### 4.1 实现智能执行器

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
混合执行策略
文件: metagpt/actions/di/execute_hybrid.py
"""
from enum import Enum
from pathlib import Path
from typing import Tuple, Optional

from metagpt.actions import Action
from metagpt.actions.di.execute_multi_kernel import MultiKernelExecutor
from metagpt.actions.di.execute_subprocess import SubprocessLanguageExecutor
from metagpt.actions.di.execute_docker import DockerLanguageExecutor
from metagpt.logs import logger


class ExecutionMode(Enum):
    """执行模式"""
    JUPYTER = "jupyter"      # Jupyter Kernel
    SUBPROCESS = "subprocess"  # 直接 subprocess
    DOCKER = "docker"        # Docker 容器
    AUTO = "auto"           # 自动选择


class HybridLanguageExecutor(Action):
    """混合执行策略的智能执行器"""

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.AUTO,
        timeout: int = 60,
        enable_docker: bool = True,
        workspace: Optional[Path] = None,
    ):
        """
        初始化混合执行器

        Args:
            mode: 执行模式
            timeout: 超时时间
            enable_docker: 是否启用 Docker
            workspace: 工作目录
        """
        super().__init__()
        self.mode = mode
        self.timeout = timeout
        self.enable_docker = enable_docker
        self.workspace = workspace

        # 初始化各种执行器
        self.jupyter_executor = None
        self.subprocess_executor = None
        self.docker_executor = None

    def _choose_executor(
        self, code: str, language: str, trusted: bool = False
    ) -> str:
        """
        选择最优执行器

        Args:
            code: 代码内容
            language: 编程语言
            trusted: 是否为可信代码

        Returns:
            执行器类型 ("jupyter", "subprocess", "docker")
        """
        if self.mode != ExecutionMode.AUTO:
            return self.mode.value

        # 自动选择策略
        if language == "python" and trusted:
            # Python 且可信 -> Jupyter（支持交互）
            return "jupyter"

        if not self.enable_docker:
            # 未启用 Docker -> Subprocess
            return "subprocess"

        # 根据代码特征选择
        if len(code) > 10000:
            # 大型代码 -> Docker（更好的隔离）
            return "docker"

        if "import requests" in code or "http" in code.lower():
            # 需要网络 -> Docker（可控网络）
            return "docker"

        if language in ["javascript", "java", "golang", "rust"]:
            # 非 Python 语言 -> Docker（环境完整）
            return "docker"

        # 默认使用 subprocess
        return "subprocess"

    async def execute(
        self,
        code: str,
        language: str = "python",
        trusted: bool = False,
        force_mode: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """
        执行代码

        Args:
            code: 代码内容
            language: 编程语言
            trusted: 是否为可信代码
            force_mode: 强制使用指定模式

        Returns:
            (输出, 是否成功)
        """
        # 选择执行器
        executor_type = force_mode or self._choose_executor(code, language, trusted)

        logger.info(f"Using {executor_type} executor for {language} code")

        try:
            if executor_type == "jupyter":
                if not self.jupyter_executor:
                    self.jupyter_executor = MultiKernelExecutor.from_language(language)
                return await self.jupyter_executor.run(code, language=language)

            elif executor_type == "subprocess":
                if not self.subprocess_executor:
                    self.subprocess_executor = SubprocessLanguageExecutor(
                        timeout=self.timeout, workspace=self.workspace
                    )
                return await self.subprocess_executor.execute(code, language=language)

            elif executor_type == "docker":
                if not self.docker_executor:
                    self.docker_executor = DockerLanguageExecutor(
                        timeout=self.timeout,
                        memory_limit="1g",
                        enable_network=True,
                        workspace=self.workspace,
                    )
                return await self.docker_executor.execute(code, language=language)

            else:
                return f"Unknown executor type: {executor_type}", False

        except Exception as e:
            logger.error(f"Execution failed with {executor_type}: {e}")
            # 降级策略：尝试使用其他执行器
            if executor_type != "subprocess":
                logger.info("Falling back to subprocess executor")
                if not self.subprocess_executor:
                    self.subprocess_executor = SubprocessLanguageExecutor(
                        timeout=self.timeout
                    )
                return await self.subprocess_executor.execute(code, language=language)
            return f"Error: {str(e)}", False

    async def run(self, code: str, **kwargs) -> Tuple[str, bool]:
        """Action 接口实现"""
        return await self.execute(code, **kwargs)

    async def cleanup(self):
        """清理所有执行器"""
        if self.jupyter_executor:
            await self.jupyter_executor.terminate()
        if self.docker_executor:
            self.docker_executor.cleanup()
```

### 4.2 使用示例

```python
from metagpt.actions.di.execute_hybrid import HybridLanguageExecutor, ExecutionMode

# 自动选择模式
executor = HybridLanguageExecutor(mode=ExecutionMode.AUTO)

# Python 代码（可信） -> 自动选择 Jupyter
python_code = """
import numpy as np
arr = np.array([1, 2, 3, 4, 5])
print(f"Mean: {arr.mean()}")
"""
output, success = await executor.execute(python_code, language="python", trusted=True)

# JavaScript 代码 -> 自动选择 Docker
js_code = """
const arr = [1, 2, 3, 4, 5];
console.log('Sum:', arr.reduce((a, b) => a + b, 0));
"""
output, success = await executor.execute(js_code, language="javascript")

# 强制使用特定模式
output, success = await executor.execute(
    python_code,
    language="python",
    force_mode="docker"  # 强制使用 Docker
)

# 清理
await executor.cleanup()
```

---

## 集成到 DataInterpreter

### 5.1 修改 DataInterpreter

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
支持多语言的 DataInterpreter
文件: metagpt/roles/di/data_interpreter_multilang.py
"""
from metagpt.roles.di.data_interpreter import DataInterpreter
from metagpt.actions.di.execute_hybrid import HybridLanguageExecutor, ExecutionMode


class MultiLangDataInterpreter(DataInterpreter):
    """支持多语言的 Data Interpreter"""

    def __init__(
        self,
        execution_mode: ExecutionMode = ExecutionMode.AUTO,
        enable_docker: bool = True,
        *args,
        **kwargs
    ):
        # 使用混合执行器替换原来的 execute_code
        execute_code = HybridLanguageExecutor(
            mode=execution_mode,
            enable_docker=enable_docker,
        )

        super().__init__(execute_code=execute_code, *args, **kwargs)

    async def _write_and_exec_code(self, max_retry: int = 3):
        """重写代码执行逻辑，支持多语言"""
        counter = 0
        success = False

        # 计划状态
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

        while not success and counter < max_retry:
            # 编写代码
            code, cause_by = await self._write_code(counter, plan_status, tool_info)

            # 检测语言
            language = self._detect_code_language(code)

            # 添加到工作记忆
            self.working_memory.add(
                Message(content=f"[{language}]\n{code}", role="assistant", cause_by=cause_by)
            )

            # 执行代码（支持多语言）
            result, success = await self.execute_code.execute(
                code, language=language, trusted=True
            )
            print(result)

            self.working_memory.add(
                Message(content=result, role="user", cause_by=type(self.execute_code))
            )

            counter += 1

        return code, result, success

    def _detect_code_language(self, code: str) -> str:
        """检测代码语言"""
        # 简单检测
        if "```python" in code:
            return "python"
        elif "```javascript" in code or "```js" in code:
            return "javascript"
        elif "```typescript" in code or "```ts" in code:
            return "typescript"
        elif "```java" in code:
            return "java"
        elif "```go" in code or "```golang" in code:
            return "golang"
        elif "```rust" in code:
            return "rust"
        elif "```cpp" in code or "```c++" in code:
            return "cpp"
        elif "```c" in code:
            return "c"

        # 默认 Python
        return "python"
```

### 5.2 使用多语言 DataInterpreter

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多语言 Software Company 示例
文件: examples/di/software_company_multilang.py
"""
import fire
from metagpt.roles.di.data_interpreter_multilang import MultiLangDataInterpreter
from metagpt.actions.di.execute_hybrid import ExecutionMode


async def main():
    prompt = """
This is a software requirement:
```text
Create a full-stack web application with:
1. Backend API in Python (Flask)
2. Frontend in JavaScript (React)
3. Database queries in SQL
```
---
1. Write Python backend code (Flask API)
2. Write JavaScript frontend code (React)
3. Write database schema and queries
4. Test each component
5. Integrate all components
Note: All required dependencies and environments have been fully installed and configured.
"""

    # 创建支持多语言的 DataInterpreter
    di = MultiLangDataInterpreter(
        execution_mode=ExecutionMode.AUTO,  # 自动选择执行模式
        enable_docker=True,  # 启用 Docker
        tools=[
            "WritePRD",
            "WriteDesign",
            "WritePlan",
            "WriteCode",
            "RunCode",
            "DebugError",
        ]
    )

    await di.run(prompt)


if __name__ == "__main__":
    fire.Fire(main)
```

---

## 使用示例

### 示例 1: JavaScript/Node.js 项目

```python
from metagpt.roles.di.data_interpreter_multilang import MultiLangDataInterpreter
from metagpt.actions.di.execute_hybrid import ExecutionMode

di = MultiLangDataInterpreter(
    execution_mode=ExecutionMode.DOCKER,
    tools=["WritePRD", "WriteDesign", "WriteCode", "RunCode"]
)

prompt = """
Create a Node.js REST API with the following features:
1. Express.js server
2. CRUD endpoints for a Todo list
3. MongoDB connection
4. Input validation
5. Error handling
"""

await di.run(prompt)
```

### 示例 2: Go 微服务

```python
di = MultiLangDataInterpreter(
    execution_mode=ExecutionMode.DOCKER,
)

prompt = """
Create a Go microservice with:
1. HTTP server using Gin framework
2. RESTful API endpoints
3. PostgreSQL database connection
4. JWT authentication
5. Docker deployment configuration
"""

await di.run(prompt)
```

### 示例 3: 混合语言项目

```python
di = MultiLangDataInterpreter(
    execution_mode=ExecutionMode.AUTO,
    enable_docker=True,
)

prompt = """
Create a data pipeline with:
1. Python script for data extraction (requests, pandas)
2. JavaScript visualization (D3.js)
3. Shell script for deployment
4. SQL queries for data transformation
"""

await di.run(prompt)
```

---

## 部署指南

### 方案一部署（Jupyter Kernel）

```bash
# 1. 安装 Jupyter
pip install jupyter jupyterlab nbclient nbformat

# 2. 安装各语言 Kernel
# JavaScript
npm install -g ijavascript
ijsinstall

# Java
wget https://github.com/SpencerPark/IJava/releases/download/v1.3.0/ijava-1.3.0.zip
unzip ijava-1.3.0.zip
cd ijava-1.3.0
python install.py --sys-prefix

# Go
go install github.com/gopherdata/gophernotes@latest
mkdir -p ~/.local/share/jupyter/kernels/gophernotes
cp -r "$(go env GOPATH)"/pkg/mod/github.com/gopherdata/gophernotes*/kernel/* \
   ~/.local/share/jupyter/kernels/gophernotes

# Rust
cargo install evcxr_jupyter
evcxr_jupyter --install

# 3. 验证安装
jupyter kernelspec list

# 4. 安装 MetaGPT 扩展
pip install -e .
```

### 方案二部署（Subprocess）

```bash
# 1. 安装各语言运行时
# Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Java
sudo apt-get install -y openjdk-17-jdk

# Go
wget https://go.dev/dl/go1.21.5.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf go1.21.5.linux-amd64.tar.gz
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# C/C++
sudo apt-get install -y gcc g++

# 2. 验证安装
node --version
java --version
go version
rustc --version
gcc --version

# 3. 安装 MetaGPT
pip install -e .
```

### 方案三部署（Docker）

```bash
# 1. 安装 Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# 2. 拉取常用镜像
docker pull python:3.11-slim
docker pull node:18-alpine
docker pull openjdk:17-alpine
docker pull golang:1.21-alpine
docker pull rust:1.74-alpine
docker pull gcc:13-alpine

# 3. 安装 Python Docker SDK
pip install docker

# 4. 安装 MetaGPT
pip install -e .
```

### Docker Compose 部署

```yaml
# docker-compose.yml
version: '3.8'

services:
  metagpt-multilang:
    build: .
    container_name: metagpt-multilang
    volumes:
      - ./workspace:/workspace
      - /var/run/docker.sock:/var/run/docker.sock  # Docker-in-Docker
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - WORKSPACE_PATH=/workspace
    networks:
      - metagpt-network
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 8G

networks:
  metagpt-network:
    driver: bridge
```

```dockerfile
# Dockerfile
FROM python:3.11-slim

# 安装 Docker CLI
RUN apt-get update && \
    apt-get install -y docker.io && \
    rm -rf /var/lib/apt/lists/*

# 安装 MetaGPT
WORKDIR /app
COPY . .
RUN pip install -e .

CMD ["python", "examples/di/software_company_multilang.py"]
```

---

## 最佳实践

### 1. 选择合适的执行模式

| 场景 | 推荐模式 | 原因 |
|-----|---------|------|
| 数据分析（Python） | Jupyter | 交互式、可视化 |
| 快速原型 | Subprocess | 启动快、资源少 |
| 生产环境 | Docker | 隔离好、可复现 |
| 多租户 SaaS | Docker | 安全隔离 |
| CI/CD | Docker | 环境一致 |

### 2. 资源限制配置

```python
# 生产环境推荐配置
docker_executor = DockerLanguageExecutor(
    timeout=300,            # 5 分钟超时
    memory_limit="2g",      # 2GB 内存
    cpu_quota=100000,       # 100% CPU (单核)
    enable_network=True,    # 启用网络（按需）
)
```

### 3. 错误处理

```python
async def safe_execute(executor, code, language):
    """带重试的安全执行"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            output, success = await executor.execute(code, language=language)
            if success:
                return output, True
            logger.warning(f"Attempt {attempt + 1} failed: {output}")
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} error: {e}")
            if attempt == max_retries - 1:
                return f"Failed after {max_retries} attempts: {str(e)}", False
            await asyncio.sleep(2 ** attempt)  # 指数退避
    return "Max retries exceeded", False
```

### 4. 监控和日志

```python
import time
from metagpt.logs import logger

async def execute_with_monitoring(executor, code, language):
    """带监控的执行"""
    start_time = time.time()

    logger.info(f"Starting execution: language={language}, code_size={len(code)}")

    output, success = await executor.execute(code, language=language)

    duration = time.time() - start_time

    logger.info(
        f"Execution complete: "
        f"language={language}, "
        f"success={success}, "
        f"duration={duration:.2f}s, "
        f"output_size={len(output)}"
    )

    return output, success
```

### 5. 清理和资源管理

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def language_executor(language: str, mode: str = "docker"):
    """上下文管理器，自动清理资源"""
    if mode == "docker":
        executor = DockerLanguageExecutor()
    elif mode == "jupyter":
        executor = MultiKernelExecutor.from_language(language)
    else:
        executor = SubprocessLanguageExecutor()

    try:
        yield executor
    finally:
        # 清理资源
        if hasattr(executor, 'cleanup'):
            executor.cleanup()
        if hasattr(executor, 'terminate'):
            await executor.terminate()

# 使用
async with language_executor("javascript", mode="docker") as executor:
    output, success = await executor.execute(js_code)
```

### 6. 安全配置

```python
# 1. 禁用网络（敏感环境）
executor = DockerLanguageExecutor(enable_network=False)

# 2. 限制文件系统访问
executor = DockerLanguageExecutor()
# 只挂载必要的目录，使用只读模式
# volumes={"/data": {"bind": "/data", "mode": "ro"}}

# 3. 使用安全的 Docker 镜像
# 使用官方镜像，定期更新
docker pull python:3.11-slim
docker pull node:18-alpine

# 4. 代码审查
def is_code_safe(code: str) -> bool:
    """简单的代码安全检查"""
    dangerous_patterns = [
        r"import\s+os",
        r"subprocess",
        r"eval\(",
        r"exec\(",
        r"__import__",
        r"open\(['\"]\/",  # 打开根目录文件
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, code):
            return False
    return True
```

---

## 总结

### 方案对比总结

| 特性 | Jupyter Kernel | Subprocess | Docker | 混合策略 |
|-----|---------------|-----------|---------|---------|
| **易用性** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| **性能** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **隔离性** | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **可复现性** | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **资源消耗** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
| **语言支持** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **部署难度** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ |

### 推荐使用场景

- **开发/测试**: 混合策略（自动模式）
- **生产环境**: Docker
- **数据分析**: Jupyter Kernel
- **CI/CD**: Docker
- **快速原型**: Subprocess

### 下一步

1. ✅ 实现基础的多语言支持
2. ✅ 添加 Docker 容器化执行
3. ⏭ 添加语言检测优化
4. ⏭ 实现代码安全检查
5. ⏭ 添加性能监控
6. ⏭ 编写单元测试

---

**文档版本**: 1.0
**最后更新**: 2025-11-16
**作者**: Claude
**相关文档**:
- [Software Company 实现细节](./software_company_implementation.md)
- [代码执行环境隔离机制](./software_company_code_execution_isolation.md)
