# Software Company - 测试用例生成扩展方案

## 目录

1. [概述](#概述)
2. [当前流程分析](#当前流程分析)
3. [测试生成集成点](#测试生成集成点)
4. [核心设计](#核心设计)
5. [实现方案](#实现方案)
6. [测试框架支持](#测试框架支持)
7. [完整工作流程](#完整工作流程)
8. [使用示例](#使用示例)
9. [最佳实践](#最佳实践)
10. [扩展功能](#扩展功能)

---

## 概述

### 目标

在 Software Company 的研发流程中增加**自动化测试用例生成**功能，实现：

- ✅ 根据代码自动生成单元测试
- ✅ 根据设计文档生成集成测试
- ✅ 根据 PRD 生成端到端测试
- ✅ 自动执行测试并反馈结果
- ✅ 测试失败时自动修复代码
- ✅ 生成测试覆盖率报告

### 价值

1. **提高代码质量** - 自动发现 bug
2. **加速开发** - 减少手动编写测试的时间
3. **保证回归** - 防止新代码破坏已有功能
4. **文档化** - 测试即文档，说明代码如何使用
5. **持续集成** - 支持 CI/CD 流程

---

## 当前流程分析

### 现有工作流程

```
用户需求
    ↓
WritePRD (产品需求文档)
    ↓
WriteDesign (系统设计)
    ↓
WritePlan (项目计划)
    ↓
WriteCode (代码实现)
    ↓
RunCode (代码执行)
    ↓
[❌ 缺少测试环节]
    ↓
Git 提交
```

### 缺失的测试环节

当前流程中：
- ❌ 没有自动生成测试用例
- ❌ 没有测试覆盖率检查
- ❌ 没有测试驱动开发（TDD）支持
- ❌ 没有回归测试机制

---

## 测试生成集成点

### 方案对比

| 集成点 | 时机 | 优势 | 劣势 | 推荐度 |
|-------|------|------|------|--------|
| **PRD 后** | 生成设计前 | 测试先行（TDD） | 设计可能变化 | ⭐⭐⭐ |
| **设计后** | 生成代码前 | 有明确接口定义 | 实现可能不同 | ⭐⭐⭐⭐ |
| **代码后** | 执行代码前 | 基于实际代码 | 发现问题晚 | ⭐⭐⭐⭐⭐ |
| **执行后** | 运行失败时 | 针对性强 | 可能太晚 | ⭐⭐⭐ |
| **多阶段** | 全流程 | 全面覆盖 | 复杂度高 | ⭐⭐⭐⭐⭐ |

### 推荐方案：多阶段测试生成

```
WritePRD
    ↓
WriteDesign
    ↓
[新增] GenerateInterfaceTests (接口测试用例)
    ↓
WritePlan
    ↓
WriteCode
    ↓
[新增] GenerateUnitTests (单元测试用例)
    ↓
[新增] RunTests (执行测试)
    ↓
    成功 → Git 提交
    ↓
    失败 → DebugCode → WriteCode (循环)
```

---

## 核心设计

### 架构图

```
┌─────────────────────────────────────────────────────────┐
│              Test Generation System                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────┐      ┌──────────────────┐        │
│  │  Test Generator  │      │  Test Executor   │        │
│  │  (生成测试)       │      │  (执行测试)       │        │
│  └──────────────────┘      └──────────────────┘        │
│           │                         │                   │
│           ▼                         ▼                   │
│  ┌──────────────────────────────────────────┐          │
│  │         Test Framework Adapters          │          │
│  │  (pytest, unittest, jest, junit, etc.)   │          │
│  └──────────────────────────────────────────┘          │
│           │                                             │
└───────────┼─────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────┐
│              Test Analysis & Feedback                    │
│  - 覆盖率分析                                             │
│  - 失败原因分析                                           │
│  - 修复建议生成                                           │
└─────────────────────────────────────────────────────────┘
```

### 核心组件

1. **TestCaseGenerator** - 测试用例生成器
2. **TestExecutor** - 测试执行器
3. **CoverageAnalyzer** - 覆盖率分析器
4. **TestFixer** - 测试修复器

---

## 实现方案

### 1. 测试用例生成器

#### 1.1 GenerateUnitTests - 单元测试生成

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单元测试生成器
文件: metagpt/actions/generate_unit_tests.py
"""
from pathlib import Path
from typing import List, Optional

from metagpt.actions import Action
from metagpt.logs import logger
from metagpt.schema import Document
from metagpt.utils.common import CodeParser


UNIT_TEST_PROMPT = """
# Role
You are an expert software test engineer specializing in writing comprehensive unit tests.

# Task
Generate unit tests for the following code.

# Code to Test
## File: {filename}
```{language}
{code}
```

# Requirements
1. **Framework**: Use {test_framework} for writing tests
2. **Coverage**: Aim for 100% code coverage
3. **Test Cases**: Include:
   - Happy path scenarios
   - Edge cases (empty input, null, boundary values)
   - Error handling (exceptions, invalid input)
   - Mock external dependencies
4. **Naming**: Use descriptive test names (test_function_name_when_condition_then_expected_result)
5. **Assertions**: Use specific assertions (assertEqual, assertRaises, etc.)
6. **Setup/Teardown**: Use fixtures/setup methods when needed
7. **Documentation**: Add docstrings explaining what each test verifies

# Design Context (if available)
{design_context}

# Output Format
Return ONLY the test code in a code block, nothing else.

## Test File: {test_filename}
```{language}
# Test code here
```
"""


class GenerateUnitTests(Action):
    """生成单元测试用例"""

    name: str = "GenerateUnitTests"

    # 测试框架映射
    TEST_FRAMEWORKS = {
        "python": "pytest",
        "javascript": "jest",
        "typescript": "jest",
        "java": "junit",
        "golang": "testing",
        "rust": "cargo test",
        "c": "gtest",
        "cpp": "gtest",
    }

    # 测试文件命名规则
    TEST_FILE_PATTERNS = {
        "python": "test_{filename}.py",
        "javascript": "{filename}.test.js",
        "typescript": "{filename}.test.ts",
        "java": "{classname}Test.java",
        "golang": "{filename}_test.go",
        "rust": "{filename}_test.rs",
    }

    async def run(
        self,
        code: str,
        filename: str,
        language: str = "python",
        design_doc: Optional[Document] = None,
        test_framework: Optional[str] = None,
    ) -> str:
        """
        生成单元测试

        Args:
            code: 源代码
            filename: 文件名
            language: 编程语言
            design_doc: 设计文档（可选）
            test_framework: 测试框架（可选）

        Returns:
            生成的测试代码
        """
        # 确定测试框架
        framework = test_framework or self.TEST_FRAMEWORKS.get(language, "pytest")

        # 生成测试文件名
        test_filename = self._generate_test_filename(filename, language)

        # 构建提示词
        design_context = ""
        if design_doc:
            design_context = f"Design Document:\n{design_doc.content}"

        prompt = UNIT_TEST_PROMPT.format(
            filename=filename,
            language=language,
            code=code,
            test_framework=framework,
            design_context=design_context,
            test_filename=test_filename,
        )

        # 调用 LLM 生成测试
        logger.info(f"Generating unit tests for {filename} using {framework}")
        response = await self._aask(prompt)

        # 解析测试代码
        test_code = CodeParser.parse_code(response, language)

        logger.info(f"Generated {len(test_code.split('def test_'))} test cases")

        return test_code

    def _generate_test_filename(self, filename: str, language: str) -> str:
        """生成测试文件名"""
        pattern = self.TEST_FILE_PATTERNS.get(language, "test_{filename}")
        base_name = Path(filename).stem

        if language == "java":
            # Java: 提取类名
            class_name = self._extract_class_name(base_name)
            return pattern.format(classname=class_name)
        else:
            return pattern.format(filename=base_name)

    def _extract_class_name(self, filename: str) -> str:
        """从文件名提取类名（Java）"""
        # 简单实现：假设文件名就是类名
        return filename.replace("_", "").capitalize()
```

#### 1.2 GenerateIntegrationTests - 集成测试生成

```python
"""
集成测试生成器
文件: metagpt/actions/generate_integration_tests.py
"""

INTEGRATION_TEST_PROMPT = """
# Role
You are an expert in integration testing, skilled at testing component interactions.

# Task
Generate integration tests based on the system design.

# System Design
{design}

# Components to Test
{components}

# Requirements
1. **Framework**: Use {test_framework}
2. **Test Scope**: Test interactions between components:
   - API endpoints (HTTP requests/responses)
   - Database operations (CRUD, transactions)
   - Message queues (publish/subscribe)
   - External services (mocked or test instances)
3. **Test Data**: Set up test data and clean up after tests
4. **Test Cases**: Include:
   - Normal flow (happy path)
   - Error scenarios (network errors, timeouts)
   - Data validation
   - Authentication/Authorization
5. **Isolation**: Each test should be independent
6. **Documentation**: Explain the integration scenario

# Output Format
```{language}
# Integration test code
```
"""


class GenerateIntegrationTests(Action):
    """生成集成测试"""

    async def run(
        self,
        design_doc: Document,
        components: List[str],
        language: str = "python",
        test_framework: Optional[str] = None,
    ) -> str:
        """
        生成集成测试

        Args:
            design_doc: 系统设计文档
            components: 要测试的组件列表
            language: 编程语言
            test_framework: 测试框架

        Returns:
            集成测试代码
        """
        framework = test_framework or GenerateUnitTests.TEST_FRAMEWORKS.get(language, "pytest")

        prompt = INTEGRATION_TEST_PROMPT.format(
            design=design_doc.content,
            components="\n".join(f"- {comp}" for comp in components),
            test_framework=framework,
            language=language,
        )

        logger.info(f"Generating integration tests for {len(components)} components")
        response = await self._aask(prompt)

        test_code = CodeParser.parse_code(response, language)
        return test_code
```

#### 1.3 GenerateE2ETests - 端到端测试生成

```python
"""
端到端测试生成器
文件: metagpt/actions/generate_e2e_tests.py
"""

E2E_TEST_PROMPT = """
# Role
You are an expert in end-to-end testing, simulating real user scenarios.

# Task
Generate E2E tests based on the Product Requirements Document (PRD).

# PRD
{prd}

# User Stories
{user_stories}

# Requirements
1. **Framework**: Use {test_framework} (e.g., Selenium, Playwright, Cypress)
2. **Test Scope**: Simulate complete user journeys:
   - User registration and login
   - Main user workflows
   - Data input and validation
   - Expected outputs and UI states
3. **Test Cases**: Cover all user stories
4. **Assertions**: Verify UI elements, data, navigation
5. **Best Practices**:
   - Use Page Object Model (POM) pattern
   - Add waiting strategies for async operations
   - Take screenshots on failure
   - Clean up test data

# Output Format
```{language}
# E2E test code
```
"""


class GenerateE2ETests(Action):
    """生成端到端测试"""

    async def run(
        self,
        prd_doc: Document,
        user_stories: List[str],
        language: str = "python",
        test_framework: str = "playwright",
    ) -> str:
        """
        生成 E2E 测试

        Args:
            prd_doc: PRD 文档
            user_stories: 用户故事列表
            language: 编程语言
            test_framework: 测试框架

        Returns:
            E2E 测试代码
        """
        prompt = E2E_TEST_PROMPT.format(
            prd=prd_doc.content,
            user_stories="\n".join(f"- {story}" for story in user_stories),
            test_framework=test_framework,
            language=language,
        )

        logger.info(f"Generating E2E tests for {len(user_stories)} user stories")
        response = await self._aask(prompt)

        test_code = CodeParser.parse_code(response, language)
        return test_code
```

### 2. 测试执行器

```python
"""
测试执行器
文件: metagpt/actions/run_tests.py
"""
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from metagpt.actions import Action
from metagpt.logs import logger


class RunTests(Action):
    """执行测试并生成报告"""

    name: str = "RunTests"

    # 测试命令映射
    TEST_COMMANDS = {
        "python": {
            "pytest": "pytest {test_files} -v --cov={src_dir} --cov-report=json --cov-report=html",
            "unittest": "python -m unittest discover -s {test_dir} -v",
        },
        "javascript": {
            "jest": "jest {test_files} --coverage --json --outputFile={output}",
            "mocha": "mocha {test_files} --reporter json > {output}",
        },
        "java": {
            "junit": "mvn test",
            "gradle": "gradle test",
        },
        "golang": {
            "testing": "go test ./... -v -coverprofile=coverage.out",
        },
    }

    async def run(
        self,
        test_files: List[str],
        src_dir: str,
        language: str = "python",
        test_framework: str = "pytest",
        workspace: Optional[Path] = None,
    ) -> Tuple[bool, Dict]:
        """
        执行测试

        Args:
            test_files: 测试文件列表
            src_dir: 源代码目录
            language: 编程语言
            test_framework: 测试框架
            workspace: 工作目录

        Returns:
            (是否成功, 测试报告)
        """
        workspace = workspace or Path.cwd()

        # 获取测试命令
        cmd_template = self.TEST_COMMANDS.get(language, {}).get(test_framework)
        if not cmd_template:
            return False, {"error": f"Unsupported test framework: {test_framework}"}

        # 构建命令
        output_file = workspace / "test_results.json"
        cmd = cmd_template.format(
            test_files=" ".join(test_files),
            src_dir=src_dir,
            test_dir=workspace / "tests",
            output=output_file,
        )

        logger.info(f"Running tests: {cmd}")

        try:
            # 执行测试
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workspace,
            )

            stdout, stderr = process.communicate(timeout=300)  # 5分钟超时

            # 解析结果
            success = process.returncode == 0

            # 读取测试报告
            report = self._parse_test_report(
                output_file, stdout.decode(), stderr.decode(), language, test_framework
            )

            logger.info(
                f"Tests {'passed' if success else 'failed'}: "
                f"{report.get('passed', 0)}/{report.get('total', 0)} tests"
            )

            return success, report

        except subprocess.TimeoutExpired:
            logger.error("Test execution timeout")
            return False, {"error": "Timeout"}
        except Exception as e:
            logger.error(f"Test execution error: {e}")
            return False, {"error": str(e)}

    def _parse_test_report(
        self,
        output_file: Path,
        stdout: str,
        stderr: str,
        language: str,
        framework: str,
    ) -> Dict:
        """解析测试报告"""
        report = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "coverage": 0.0,
            "failures": [],
            "stdout": stdout,
            "stderr": stderr,
        }

        try:
            if framework == "pytest" and output_file.exists():
                # 解析 pytest JSON 报告
                with open(output_file) as f:
                    data = json.load(f)
                    report["coverage"] = data.get("totals", {}).get("percent_covered", 0.0)

            elif framework == "jest" and output_file.exists():
                # 解析 Jest JSON 报告
                with open(output_file) as f:
                    data = json.load(f)
                    report["total"] = data.get("numTotalTests", 0)
                    report["passed"] = data.get("numPassedTests", 0)
                    report["failed"] = data.get("numFailedTests", 0)

            # 从 stdout 提取测试统计
            if "pytest" in stdout:
                # 示例: "5 passed, 2 failed in 1.23s"
                import re
                match = re.search(r"(\d+) passed", stdout)
                if match:
                    report["passed"] = int(match.group(1))
                match = re.search(r"(\d+) failed", stdout)
                if match:
                    report["failed"] = int(match.group(1))
                report["total"] = report["passed"] + report["failed"]

        except Exception as e:
            logger.warning(f"Failed to parse test report: {e}")

        return report
```

### 3. 覆盖率分析器

```python
"""
测试覆盖率分析器
文件: metagpt/actions/analyze_coverage.py
"""
from pathlib import Path
from typing import Dict, List

from metagpt.actions import Action
from metagpt.logs import logger


class AnalyzeCoverage(Action):
    """分析测试覆盖率并提供改进建议"""

    name: str = "AnalyzeCoverage"

    async def run(
        self, coverage_report: Dict, target_coverage: float = 80.0
    ) -> Dict:
        """
        分析覆盖率

        Args:
            coverage_report: 覆盖率报告
            target_coverage: 目标覆盖率（百分比）

        Returns:
            分析结果和建议
        """
        current_coverage = coverage_report.get("coverage", 0.0)

        analysis = {
            "current_coverage": current_coverage,
            "target_coverage": target_coverage,
            "meets_target": current_coverage >= target_coverage,
            "gap": target_coverage - current_coverage if current_coverage < target_coverage else 0,
            "uncovered_files": [],
            "recommendations": [],
        }

        # 查找未覆盖的文件
        files_data = coverage_report.get("files", {})
        for file_path, file_coverage in files_data.items():
            if file_coverage.get("percent_covered", 0) < target_coverage:
                analysis["uncovered_files"].append({
                    "file": file_path,
                    "coverage": file_coverage.get("percent_covered", 0),
                    "missing_lines": file_coverage.get("missing_lines", []),
                })

        # 生成建议
        if not analysis["meets_target"]:
            analysis["recommendations"] = await self._generate_recommendations(
                analysis["uncovered_files"]
            )

        return analysis

    async def _generate_recommendations(self, uncovered_files: List[Dict]) -> List[str]:
        """生成改进建议"""
        recommendations = []

        for file_info in uncovered_files[:5]:  # 只处理前5个文件
            file_path = file_info["file"]
            missing_lines = file_info.get("missing_lines", [])

            if missing_lines:
                recommendations.append(
                    f"Add tests for {file_path} to cover lines: {missing_lines}"
                )
            else:
                recommendations.append(
                    f"Increase test coverage for {file_path} (currently {file_info['coverage']:.1f}%)"
                )

        # 通用建议
        if len(uncovered_files) > 5:
            recommendations.append(
                f"Focus on the {len(uncovered_files)} files with low coverage"
            )

        return recommendations
```

### 4. 测试修复器

```python
"""
测试失败修复器
文件: metagpt/actions/fix_test_failures.py
"""
from typing import Dict, List, Tuple

from metagpt.actions import Action
from metagpt.logs import logger
from metagpt.utils.common import CodeParser


FIX_TEST_PROMPT = """
# Role
You are an expert debugger specializing in fixing test failures.

# Task
Fix the failing tests or the code being tested.

# Failed Test
{test_code}

# Test Failure Details
{failure_details}

# Source Code (being tested)
{source_code}

# Analysis
1. Understand why the test is failing
2. Determine if the test is correct or the source code has bugs
3. Fix either the test or the source code

# Output Format
Provide TWO code blocks:

## Fixed Test Code (if test needs fixing)
```{language}
# Fixed test code or "NO_CHANGE" if test is correct
```

## Fixed Source Code (if source needs fixing)
```{language}
# Fixed source code or "NO_CHANGE" if source is correct
```

## Explanation
Explain what was wrong and what you fixed.
"""


class FixTestFailures(Action):
    """修复测试失败"""

    name: str = "FixTestFailures"

    async def run(
        self,
        test_code: str,
        source_code: str,
        failure_details: str,
        language: str = "python",
    ) -> Tuple[str, str, str]:
        """
        修复测试失败

        Args:
            test_code: 测试代码
            source_code: 源代码
            failure_details: 失败详情
            language: 编程语言

        Returns:
            (修复后的测试代码, 修复后的源代码, 解释)
        """
        prompt = FIX_TEST_PROMPT.format(
            test_code=test_code,
            failure_details=failure_details,
            source_code=source_code,
            language=language,
        )

        logger.info("Analyzing test failure and generating fixes")
        response = await self._aask(prompt)

        # 解析响应
        fixed_test = self._extract_code_block(response, "Fixed Test Code", language)
        fixed_source = self._extract_code_block(response, "Fixed Source Code", language)
        explanation = self._extract_explanation(response)

        return fixed_test, fixed_source, explanation

    def _extract_code_block(self, response: str, section: str, language: str) -> str:
        """提取代码块"""
        import re

        # 查找指定section后的代码块
        pattern = rf"{section}.*?```{language}\s*(.*?)\s*```"
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)

        if match:
            code = match.group(1).strip()
            return "" if code == "NO_CHANGE" else code
        return ""

    def _extract_explanation(self, response: str) -> str:
        """提取解释"""
        import re

        match = re.search(r"## Explanation\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""
```

---

## 测试框架支持

### 支持的测试框架

| 语言 | 单元测试 | 集成测试 | E2E 测试 | 覆盖率工具 |
|-----|---------|---------|---------|-----------|
| **Python** | pytest, unittest | pytest | Selenium, Playwright | coverage.py |
| **JavaScript/TypeScript** | Jest, Mocha | Supertest | Cypress, Playwright | Istanbul |
| **Java** | JUnit 5, TestNG | Spring Test | Selenium | JaCoCo |
| **Go** | testing | testing | - | go test -cover |
| **Rust** | cargo test | cargo test | - | tarpaulin |
| **C/C++** | Google Test | Google Test | - | gcov, lcov |

### 框架配置

```python
# metagpt/configs/test_config.py
from pydantic import BaseModel

class TestConfig(BaseModel):
    """测试配置"""

    # 测试框架
    unit_test_framework: str = "pytest"
    integration_test_framework: str = "pytest"
    e2e_test_framework: str = "playwright"

    # 覆盖率要求
    min_unit_coverage: float = 80.0
    min_integration_coverage: float = 70.0
    min_overall_coverage: float = 75.0

    # 测试执行
    test_timeout: int = 300  # 秒
    parallel_tests: bool = True
    max_test_retries: int = 2

    # 失败处理
    auto_fix_failures: bool = True
    max_fix_attempts: int = 3

    # 报告
    generate_html_report: bool = True
    generate_json_report: bool = True
```

---

## 完整工作流程

### 扩展后的 DataInterpreter

```python
"""
支持测试生成的 DataInterpreter
文件: metagpt/roles/di/data_interpreter_with_tests.py
"""
from metagpt.roles.di.data_interpreter import DataInterpreter
from metagpt.actions.generate_unit_tests import GenerateUnitTests
from metagpt.actions.run_tests import RunTests
from metagpt.actions.analyze_coverage import AnalyzeCoverage
from metagpt.actions.fix_test_failures import FixTestFailures


class DataInterpreterWithTests(DataInterpreter):
    """支持自动测试的 DataInterpreter"""

    def __init__(
        self,
        enable_unit_tests: bool = True,
        enable_integration_tests: bool = False,
        enable_e2e_tests: bool = False,
        min_coverage: float = 80.0,
        auto_fix: bool = True,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.enable_unit_tests = enable_unit_tests
        self.enable_integration_tests = enable_integration_tests
        self.enable_e2e_tests = enable_e2e_tests
        self.min_coverage = min_coverage
        self.auto_fix = auto_fix

        # 测试相关的 actions
        self.test_generator = GenerateUnitTests()
        self.test_executor = RunTests()
        self.coverage_analyzer = AnalyzeCoverage()
        self.test_fixer = FixTestFailures()

    async def _write_and_exec_code(self, max_retry: int = 3):
        """重写代码执行逻辑，增加测试环节"""
        counter = 0
        success = False

        # 获取计划和工具信息（与原实现相同）
        plan_status = self.planner.get_plan_status() if self.use_plan else ""
        tool_info = await self.tool_recommender.get_recommended_tool_info(...) if self.tool_recommender else ""
        await self._check_data()

        while not success and counter < max_retry:
            # 1. 编写代码
            code, cause_by = await self._write_code(counter, plan_status, tool_info)
            self.working_memory.add(Message(content=code, role="assistant", cause_by=cause_by))

            # 2. 生成单元测试
            if self.enable_unit_tests:
                test_code = await self._generate_tests(code, "unit")
                self.working_memory.add(Message(content=f"[Tests]\n{test_code}", role="assistant"))

            # 3. 执行代码
            result, code_success = await self.execute_code.run(code)
            print(f"Code execution: {result}")
            self.working_memory.add(Message(content=result, role="user", cause_by=ExecuteNbCode))

            if not code_success:
                counter += 1
                continue

            # 4. 执行测试
            if self.enable_unit_tests:
                test_success, test_report = await self._run_tests(test_code, code)
                print(f"Test results: {test_report.get('passed', 0)}/{test_report.get('total', 0)} passed")

                if not test_success:
                    if self.auto_fix:
                        # 5. 自动修复测试失败
                        code, test_code = await self._fix_test_failures(code, test_code, test_report)
                        counter += 1
                        continue
                    else:
                        counter += 1
                        continue

                # 6. 检查覆盖率
                coverage_ok = await self._check_coverage(test_report)
                if not coverage_ok:
                    # 生成额外的测试用例
                    additional_tests = await self._generate_missing_tests(code, test_report)
                    test_code += "\n\n" + additional_tests
                    # 重新执行测试
                    test_success, test_report = await self._run_tests(test_code, code)

            success = code_success and (not self.enable_unit_tests or test_success)
            counter += 1

        return code, result, success

    async def _generate_tests(self, code: str, test_type: str = "unit") -> str:
        """生成测试用例"""
        logger.info(f"Generating {test_type} tests")

        if test_type == "unit":
            test_code = await self.test_generator.run(
                code=code,
                filename="main.py",  # 可以从上下文获取
                language="python",
            )
        # elif test_type == "integration":
        #     test_code = await self.integration_test_generator.run(...)
        # elif test_type == "e2e":
        #     test_code = await self.e2e_test_generator.run(...)

        return test_code

    async def _run_tests(self, test_code: str, source_code: str) -> Tuple[bool, Dict]:
        """执行测试"""
        # 保存测试代码到文件
        test_file = self.config.workspace.path / "test_main.py"
        test_file.write_text(test_code)

        # 保存源代码
        src_file = self.config.workspace.path / "main.py"
        src_file.write_text(source_code)

        # 执行测试
        success, report = await self.test_executor.run(
            test_files=[str(test_file)],
            src_dir=str(self.config.workspace.path),
            language="python",
            test_framework="pytest",
        )

        return success, report

    async def _check_coverage(self, test_report: Dict) -> bool:
        """检查覆盖率"""
        analysis = await self.coverage_analyzer.run(
            coverage_report=test_report,
            target_coverage=self.min_coverage
        )

        if not analysis["meets_target"]:
            logger.warning(
                f"Coverage {analysis['current_coverage']:.1f}% below target {self.min_coverage}%"
            )
            for rec in analysis["recommendations"]:
                logger.info(f"Recommendation: {rec}")

        return analysis["meets_target"]

    async def _fix_test_failures(
        self, source_code: str, test_code: str, test_report: Dict
    ) -> Tuple[str, str]:
        """修复测试失败"""
        # 提取失败详情
        failures = test_report.get("failures", [])
        if not failures:
            return source_code, test_code

        failure_details = "\n".join(str(f) for f in failures[:3])  # 只修复前3个

        # 请求修复
        fixed_test, fixed_source, explanation = await self.test_fixer.run(
            test_code=test_code,
            source_code=source_code,
            failure_details=failure_details,
            language="python",
        )

        logger.info(f"Fix explanation: {explanation}")

        # 应用修复
        if fixed_source:
            source_code = fixed_source
        if fixed_test:
            test_code = fixed_test

        return source_code, test_code

    async def _generate_missing_tests(self, code: str, coverage_report: Dict) -> str:
        """生成缺失的测试用例"""
        # 基于覆盖率报告生成额外的测试
        uncovered_lines = []
        for file_info in coverage_report.get("files", {}).values():
            uncovered_lines.extend(file_info.get("missing_lines", []))

        if not uncovered_lines:
            return ""

        prompt = f"""
Generate additional test cases to cover the following uncovered lines in the code:

Uncovered lines: {uncovered_lines}

Code:
```python
{code}
```

Requirements:
- Focus on testing the logic in the uncovered lines
- Use pytest framework
- Return only the test code
"""

        response = await self.llm.aask(prompt)
        additional_tests = CodeParser.parse_code(response, "python")

        return additional_tests
```

---

## 使用示例

### 示例 1: 基础使用

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
带测试的 Software Company 示例
文件: examples/di/software_company_with_tests.py
"""
import fire
from metagpt.roles.di.data_interpreter_with_tests import DataInterpreterWithTests


async def main():
    prompt = """
Create a calculator module with the following features:
1. Add two numbers
2. Subtract two numbers
3. Multiply two numbers
4. Divide two numbers (handle division by zero)
5. Calculate square root (handle negative numbers)

Requirements:
- Write clean, well-documented code
- Generate comprehensive unit tests
- Ensure 100% code coverage
- Handle all edge cases
"""

    di = DataInterpreterWithTests(
        enable_unit_tests=True,
        enable_integration_tests=False,
        enable_e2e_tests=False,
        min_coverage=80.0,
        auto_fix=True,
        tools=[
            "WritePRD",
            "WriteDesign",
            "WriteCode",
            "RunCode",
        ]
    )

    await di.run(prompt)


if __name__ == "__main__":
    fire.Fire(main)
```

**输出示例**:

```
[Step 1/4] WritePRD
✓ PRD generated: workspace/calculator/docs/prd.json

[Step 2/4] WriteDesign
✓ Design generated: workspace/calculator/docs/system_design.json

[Step 3/4] WriteCode
✓ Code generated: workspace/calculator/calculator.py

[Step 4/4] GenerateTests & RunTests
Generating unit tests...
✓ Generated 15 test cases

Running tests...
============================== test session starts ===============================
test_calculator.py::test_add_positive_numbers PASSED                       [  6%]
test_calculator.py::test_add_negative_numbers PASSED                       [ 13%]
test_calculator.py::test_add_zero PASSED                                   [ 20%]
test_calculator.py::test_subtract_positive_numbers PASSED                  [ 26%]
test_calculator.py::test_multiply_by_zero PASSED                           [ 33%]
test_calculator.py::test_divide_normal PASSED                              [ 40%]
test_calculator.py::test_divide_by_zero PASSED                             [ 46%]
test_calculator.py::test_sqrt_positive PASSED                              [ 53%]
test_calculator.py::test_sqrt_zero PASSED                                  [ 60%]
test_calculator.py::test_sqrt_negative PASSED                              [ 66%]
...
============================== 15 passed in 0.83s ================================

Coverage: 100%
✓ All tests passed with full coverage!

Git commit created: "feat: implement calculator with full test coverage"
```

### 示例 2: TDD 模式（测试驱动开发）

```python
from metagpt.roles.di.data_interpreter_with_tests import DataInterpreterWithTests

# TDD 模式：先生成测试，再生成代码
di = DataInterpreterWithTests(
    enable_unit_tests=True,
    min_coverage=100.0,
    auto_fix=True,
)

prompt = """
[TDD Mode]
First write tests, then implement the code.

Feature: User Authentication
1. User can register with email and password
2. Password must be at least 8 characters
3. Email must be valid format
4. User can login with credentials
5. Invalid credentials return error

Steps:
1. Write test cases for all scenarios
2. Implement the authentication module
3. Ensure all tests pass
"""

await di.run(prompt)
```

### 示例 3: 完整 Web 应用（包含集成测试）

```python
di = DataInterpreterWithTests(
    enable_unit_tests=True,
    enable_integration_tests=True,
    enable_e2e_tests=True,
    min_coverage=80.0,
)

prompt = """
Create a REST API for a Todo application:

Features:
1. Create todo item
2. List all todos
3. Update todo item
4. Delete todo item
5. Mark todo as complete

Requirements:
- Use Flask framework
- SQLite database
- Input validation
- Error handling

Testing:
- Unit tests for business logic
- Integration tests for API endpoints
- E2E tests for complete user flows
"""

await di.run(prompt)
```

---

## 最佳实践

### 1. 测试金字塔

遵循测试金字塔原则：

```
       /\
      /  \  E2E Tests (10%)
     /____\
    /      \  Integration Tests (20%)
   /________\
  /          \  Unit Tests (70%)
 /____________\
```

配置：
```python
di = DataInterpreterWithTests(
    enable_unit_tests=True,        # 70% 的测试
    enable_integration_tests=True, # 20% 的测试
    enable_e2e_tests=False,        # 10% 的测试（可选）
    min_coverage=80.0,
)
```

### 2. 覆盖率目标

| 项目类型 | 单元测试覆盖率 | 集成测试覆盖率 | 总体覆盖率 |
|---------|--------------|--------------|----------|
| 核心库 | 95%+ | 80%+ | 90%+ |
| 业务应用 | 80%+ | 70%+ | 75%+ |
| 原型/POC | 60%+ | 50%+ | 60%+ |

### 3. 测试命名规范

```python
# ✅ 好的测试名称
def test_user_login_with_valid_credentials_returns_token():
    ...

def test_divide_by_zero_raises_value_error():
    ...

def test_empty_list_sum_returns_zero():
    ...

# ❌ 不好的测试名称
def test_1():
    ...

def test_function():
    ...
```

### 4. 测试独立性

```python
import pytest

@pytest.fixture
def clean_database():
    """每个测试前清理数据库"""
    db.clear()
    yield
    db.clear()

def test_create_user(clean_database):
    # 独立的测试，不依赖其他测试
    user = create_user("test@example.com")
    assert user.email == "test@example.com"
```

### 5. Mock 外部依赖

```python
from unittest.mock import patch

def test_fetch_weather_data():
    # Mock 外部 API 调用
    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = {"temp": 25}

        weather = fetch_weather("Beijing")
        assert weather["temp"] == 25
```

---

## 扩展功能

### 1. 性能测试生成

```python
"""性能测试生成器"""
class GeneratePerformanceTests(Action):
    async def run(self, code: str, benchmark_requirements: Dict) -> str:
        """
        生成性能测试

        Args:
            code: 源代码
            benchmark_requirements: 性能要求
                {
                    "max_response_time": 100,  # ms
                    "min_throughput": 1000,    # req/s
                    "max_memory": 512          # MB
                }
        """
        ...
```

### 2. 安全测试生成

```python
"""安全测试生成器"""
class GenerateSecurityTests(Action):
    async def run(self, code: str) -> str:
        """
        生成安全测试

        检测:
        - SQL 注入
        - XSS 攻击
        - CSRF 攻击
        - 认证/授权问题
        - 敏感数据泄露
        """
        ...
```

### 3. 回归测试管理

```python
"""回归测试管理器"""
class RegressionTestManager:
    async def save_baseline(self, test_results: Dict):
        """保存测试基线"""
        ...

    async def compare_with_baseline(self, current_results: Dict) -> Dict:
        """与基线对比，检测回归"""
        ...
```

### 4. 测试数据生成

```python
"""测试数据生成器"""
class GenerateTestData(Action):
    async def run(self, schema: Dict, num_records: int = 100) -> List[Dict]:
        """
        生成测试数据

        Args:
            schema: 数据模式
            num_records: 生成记录数

        Returns:
            测试数据列表
        """
        ...
```

### 5. 视觉回归测试

```python
"""视觉回归测试生成器"""
class GenerateVisualTests(Action):
    async def run(self, ui_components: List[str]) -> str:
        """
        生成 UI 视觉回归测试

        使用 Percy, Applitools 等工具
        """
        ...
```

---

## 总结

### 核心价值

✅ **自动化** - 自动生成和执行测试，无需手动编写
✅ **高质量** - 通过测试确保代码质量
✅ **快速反馈** - 立即发现问题并修复
✅ **可维护** - 测试即文档，易于理解代码
✅ **持续集成** - 支持 CI/CD 流程

### 实现路径

1. **阶段一**：单元测试生成和执行 ✅
2. **阶段二**：覆盖率分析和自动修复 ✅
3. **阶段三**：集成测试和 E2E 测试 🔄
4. **阶段四**：性能测试和安全测试 🔜
5. **阶段五**：完整的测试平台 🔜

### 下一步

- [ ] 实现基础的单元测试生成
- [ ] 集成到 DataInterpreter
- [ ] 添加多语言支持
- [ ] 实现自动修复机制
- [ ] 添加覆盖率报告
- [ ] 支持 CI/CD 集成

---

**文档版本**: 1.0
**最后更新**: 2025-11-16
**作者**: Claude
**相关文档**:
- [Software Company 实现细节](./software_company_implementation.md)
- [多语言支持扩展](./software_company_multilanguage_support.md)
