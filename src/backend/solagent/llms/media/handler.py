"""媒体预处理模块。

对多模态输入中的图片进行去重、压缩和尺寸限制等预处理，
降低 API 调用时的传输开销，并避免重复图片导致的不必要成本。
依赖 Pillow 库进行实际的图像操作。
"""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO

from solagent.schema.messages import ImageBlock, ImageSource, ImageSourceType


class MediaHandler:
    """媒体预处理器，负责图片去重、压缩和分辨率控制。

    属性:
        max_image_bytes: 单张图片的最大字节数，超限将触发压缩。
        max_resolution: 图片长/宽的最大像素值，超限将按比例缩放。
        quality: JPEG 压缩质量（1-100）。
        strip_metadata: 是否去除图片元数据。
        _seen_hashes: 已处理图片的 SHA256 哈希集合，用于去重。
    """

    def __init__(self, max_image_bytes: int = 20 * 1024 * 1024, max_resolution: int = 4096,
                 quality: int = 85, strip_metadata: bool = True):
        self.max_image_bytes = max_image_bytes
        self.max_resolution = max_resolution
        self.quality = quality
        self.strip_metadata = strip_metadata
        self._seen_hashes: set[str] = set()

    def deduplicate(self, blocks: list) -> list:
        """移除重复的图片块，保留首次出现的图片。"""
        result = []
        for block in blocks:
            if isinstance(block, ImageBlock) and block.source.type == ImageSourceType.BASE64 and block.source.data:
                h = hashlib.sha256(block.source.data.encode()).hexdigest()
                if h in self._seen_hashes:
                    continue
                self._seen_hashes.add(h)
            result.append(block)
        return result

    def compress(self, block: ImageBlock) -> ImageBlock:
        """对超出大小限制的图片进行压缩和分辨率缩放。

        使用 Pillow 将图片转为 JPEG 格式并调整质量/尺寸，
        若未安装 Pillow 则原样返回。
        """
        if block.source.type != ImageSourceType.BASE64 or not block.source.data:
            return block
        data = block.source.data
        if len(data) > self.max_image_bytes:
            try:
                from PIL import Image
                img = BytesIO(base64.b64decode(data))
                pil_img = Image.open(img)
                if self.strip_metadata:
                    pil_img = pil_img.copy()
                if max(pil_img.size) > self.max_resolution:
                    ratio = self.max_resolution / max(pil_img.size)
                    new_size = (int(pil_img.size[0] * ratio), int(pil_img.size[1] * ratio))
                    pil_img = pil_img.resize(new_size, Image.Resampling.LANCZOS)
                buf = BytesIO()
                pil_img.save(buf, format="JPEG", quality=self.quality)
                compressed = base64.b64encode(buf.getvalue()).decode()
                return ImageBlock(type="image", source=ImageSource(type=ImageSourceType.BASE64, data=compressed, media_type="image/jpeg"))
            except ImportError:
                pass
        return block

    def resize(self, block: ImageBlock, max_width: int, max_height: int) -> ImageBlock:
        """将图片缩放到指定的最大宽度和高度范围内（保持纵横比）。"""
        if block.source.type != ImageSourceType.BASE64 or not block.source.data:
            return block
        try:
            from PIL import Image
            img = BytesIO(base64.b64decode(block.source.data))
            pil_img = Image.open(img)
            pil_img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            buf = BytesIO()
            pil_img.save(buf, format="JPEG", quality=self.quality)
            data = base64.b64encode(buf.getvalue()).decode()
            return ImageBlock(type="image", source=ImageSource(type=ImageSourceType.BASE64, data=data, media_type="image/jpeg"))
        except ImportError:
            return block

    def process(self, blocks: list) -> list:
        """执行完整的预处理流水线：去重 → 压缩。"""
        deduped = self.deduplicate(blocks)
        return [self.compress(b) if isinstance(b, ImageBlock) else b for b in deduped]

    def reset(self) -> None:
        """清空已记录的图片哈希集合，释放内存。"""
        self._seen_hashes.clear()