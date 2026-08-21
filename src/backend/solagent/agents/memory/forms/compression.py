"""Auto-compression form. Reference: nanobot Consolidator, deer-flow SummarizationMiddleware."""
class AutoCompression:
    def __init__(self, max_tokens: int = 100000, warning_threshold: float = 0.75):
        self.max_tokens = max_tokens
        self.warning_threshold = warning_threshold

    def should_compress(self, current_tokens: int) -> bool:
        return current_tokens >= self.max_tokens * self.warning_threshold