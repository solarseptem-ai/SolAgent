"""
技能模板解析模块。

解析 Markdown 格式的 SKILL.md 文件，提取 YAML frontmatter 作为技能元数据，
正文部分作为技能内容。
"""
from dataclasses import dataclass, field

import yaml


@dataclass
class SkillTemplate:
    """技能模板数据类，承载从 SKILL.md 解析出的全部信息。

    Attributes:
        name: 技能名称。
        description: 技能描述。
        content: 技能正文内容（Markdown frontmatter 之后的部分）。
        source: 来源标识。
        source_path: 来源路径。
        category: 分类，默认 "general"。
        tags: 标签列表。
        allowed_tools: 该技能允许使用的工具列表。
        disallowed_tools: 该技能禁止使用的工具列表。
        always_active: 是否始终激活。
        triggers: 触发词列表，当用户输入包含这些词时自动激活技能。
    """

    name: str
    description: str = ""
    content: str = ""
    source: str = ""
    source_path: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    always_active: bool = False
    triggers: list[str] = field(default_factory=list)

    @classmethod
    def from_markdown(cls, path, source: str = "", source_path: str = "") -> "SkillTemplate":
        """从 Markdown 文件或文本解析技能模板。

        解析规则：
        - 若文件以 `---` 开头，则提取 YAML frontmatter 作为元数据。
        - 剩余部分作为 content。

        Args:
            path: 文件路径（Path 对象）或文本字符串。
            source: 来源标识。
            source_path: 来源路径，若 path 为文件且未指定则自动取父目录。

        Returns:
            解析后的 SkillTemplate 实例。
        """
        if hasattr(path, "read_text"):
            text = path.read_text()
            if source_path == "":
                source_path = str(path.parent)
        else:
            text = path
        lines = text.split("\n")
        frontmatter = {}
        content_start = 0
        # 检测并解析 YAML frontmatter（以 --- 包裹）
        if lines and lines[0].strip() == "---":
            end_idx = None
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    end_idx = i
                    content_start = i + 1
                    break
            if end_idx is not None:
                yaml_text = "\n".join(lines[1:end_idx])
                try:
                    parsed = yaml.safe_load(yaml_text)
                    if isinstance(parsed, dict):
                        frontmatter = parsed
                except yaml.YAMLError:
                    pass
        content = "\n".join(lines[content_start:]).strip()
        name = frontmatter.get("name", frontmatter.get("title", ""))
        return cls(
            name=name,
            description=frontmatter.get("description", ""),
            content=content,
            source=source,
            source_path=source_path,
            category=frontmatter.get("category", "general"),
            tags=_parse_list(frontmatter.get("tags", [])),
            allowed_tools=_parse_list(frontmatter.get("allowed_tools", [])),
            disallowed_tools=_parse_list(frontmatter.get("disallowed_tools", [])),
            always_active=str(frontmatter.get("always", "false")).lower() == "true",
            triggers=_parse_list(frontmatter.get("triggers", [])),
        )


def _parse_list(value) -> list[str]:
    """将 frontmatter 中的值标准化为字符串列表。

    支持 list 和逗号分隔的字符串两种形式。
    """
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return []