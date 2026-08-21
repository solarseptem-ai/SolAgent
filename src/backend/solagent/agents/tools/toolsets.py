"""工具集预设。对标 hermes-agent toolsets.py。"""

BUILTIN_TOOLSETS = {
    "core":     ["read", "write", "edit", "shell", "glob", "grep"],
    "search":   ["web_search", "web_fetch"],
    "memory":   ["remember", "recall", "forget"],
    "interact": ["clarify", "present_file", "skill_view"],
    "meta":     ["subagent", "get_current_time", "get_token_usage", "tool_search"],
    "patch":    ["apply_patch"],
}

DEFAULT_ENABLED_TOOLSETS = ["core", "search", "memory", "interact", "meta"]
