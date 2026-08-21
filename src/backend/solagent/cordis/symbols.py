"""Cordis 框架内部使用的符号常量定义。

本模块集中定义了跨模块共享的字符串符号常量（模拟 TypeScript 的 Symbol.for），
用于标识内部属性、上下文操作、服务生命周期钩子、事件名称以及 Fiber 状态等。
这些常量是 Cordis 运行时协议的基石，确保各模块间对特殊属性和状态的识别一致。
"""

from __future__ import annotations

# 内部追踪相关符号
SHADOW = "cordis.shadow"        # 标记影子上下文
RECEIVER = "cordis.receiver"    # 标记接收者
ORIGINAL = "cordis.original"    # 指向原始对象的引用
METADATA = "cordis.metadata"    # 存储元数据的属性键
INIT_HOOKS = "__cordis_init_hooks__"  # 类初始化钩子列表
CHECK_PROTO = "cordis.checkProto"     # 协议检查标记

# 上下文操作符号
EFFECT = "cordis.effect"        # 副作用/清理函数注册
FILTER = "cordis.filter"        # 上下文事件过滤器
ISOLATE = "cordis.isolate"      # 隔离作用域
INTERCEPT = "cordis.intercept"  # 拦截配置

# 服务生命周期符号
INIT = "__cordis_init__"        # 服务初始化钩子
CHECK = "cordis.check"          # 服务可用性检查
CONFIG = "cordis.config"        # 服务配置
INVOKE = "cordis.invoke"        # 服务调用
EXTEND = "cordis.extend"        # 服务扩展
TRACKER = "cordis.tracker"      # 服务追踪器配置
RESOLVE_CONFIG = "cordis.resolveConfig"  # 配置解析

# Fiber 状态标记
INACTIVE = "__INACTIVE__"       # 依赖未就绪时的 epoch 哨兵值

# 内部事件名称常量
INTERNAL_PLUGIN = "internal/plugin"
INTERNAL_STATUS = "internal/status"
INTERNAL_CONFIG = "internal/config"
INTERNAL_SERVICE = "internal/service"
INTERNAL_UPDATE = "internal/update"
INTERNAL_GET = "internal/get"
INTERNAL_SET = "internal/set"
INTERNAL_LISTENER = "internal/listener"
INTERNAL_DISPATCH = "internal/dispatch"

# Fiber 状态机枚举值
FIBER_PENDING = 0     # 等待依赖就绪
FIBER_LOADING = 1     # 正在加载
FIBER_ACTIVE = 2      # 已激活正常运行
FIBER_FAILED = 3      # 加载失败
FIBER_DISPOSED = 4    # 已释放
FIBER_UNLOADING = 5   # 正在卸载