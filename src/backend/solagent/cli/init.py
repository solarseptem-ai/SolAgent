"""
CLI init 命令模块。

提供项目脚手架功能：创建新项目目录并复制模板文件（配置文件、入口脚本等）。
"""
from __future__ import annotations

import keyword
from pathlib import Path

# 保留名称集合，禁止用户将项目命名为这些名称
RESERVED_NAMES = {"solagent", "solarseptem", "test", "tests"}


def validate_name(name: str) -> str:
    """校验项目名称的合法性。

    规则：
    - 不能为空
    - 不能包含空格
    - 不能是 Python 关键字
    - 不能以数字开头
    - 不能是保留名称

    Args:
        name: 用户输入的项目名称。

    Returns:
        校验通过的项目名称。

    Raises:
        ValueError: 名称不符合任一规则时。
    """
    if not name:
        raise ValueError("Project name cannot be empty")
    if " " in name:
        raise ValueError("Project name cannot contain spaces")
    if keyword.iskeyword(name):
        raise ValueError(f"Project name '{name}' is a Python keyword")
    if name[0].isdigit():
        raise ValueError("Project name cannot start with a digit")
    if name.lower() in RESERVED_NAMES:
        raise ValueError(f"Project name '{name}' is reserved")
    return name


def _copy_template(template_name: str, target_dir: Path, name: str) -> None:
    """从模板目录复制单个模板文件到目标目录，替换 {{name}} 占位符。

    Args:
        template_name: 模板文件名。
        target_dir: 目标项目目录。
        name: 项目名称，用于替换占位符。
    """
    template_dir = Path(__file__).parent / "templates"
    src = template_dir / template_name
    dst = target_dir / template_name

    content = src.read_text(encoding="utf-8")
    content = content.replace("{{name}}", name)
    dst.write_text(content, encoding="utf-8")


def init_project(name: str, target_dir: Path | None = None) -> Path:
    """初始化一个新的 SolAgent 项目。

    创建项目目录并复制所有模板文件。

    Args:
        name: 项目名称。
        target_dir: 目标目录，默认为当前目录 / 项目名。

    Returns:
        创建的项目目录路径。

    Raises:
        FileExistsError: 目标目录已存在时。
    """
    validate_name(name)

    if target_dir is None:
        target_dir = Path.cwd() / name

    if target_dir.exists():
        raise FileExistsError(f"Directory '{target_dir}' already exists")

    target_dir.mkdir(parents=True)

    # 项目初始化模板文件列表
    templates = [
        "solagent.yaml",
        "agents.yaml",
        "tasks.yaml",
        "main.py",
        "pyproject.toml",
        "README.md",
        "AGENTS.md",
        ".gitignore",
        ".env",
    ]

    for template in templates:
        _copy_template(template, target_dir, name)

    return target_dir