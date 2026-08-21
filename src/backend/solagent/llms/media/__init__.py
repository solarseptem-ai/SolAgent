"""媒体处理子包的入口模块。

导出 MediaHandler，用于对多模态输入中的图片进行去重、压缩和尺寸调整等预处理。
"""
from solagent.llms.media.handler import MediaHandler

__all__ = ["MediaHandler"]