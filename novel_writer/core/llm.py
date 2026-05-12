import time

from anthropic import Anthropic

from novel_writer.config import get_config


class LLMClient:
    """Anthropic SDK 封装，使用 DeepSeek 兼容 API"""

    def __init__(self):
        cfg = get_config()
        self.client = Anthropic(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
        )
        self.model = cfg["model"]
        self.default_max_tokens = cfg["max_tokens"]

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.default_max_tokens,
        }
        if system:
            kwargs["system"] = system

        last_error = None
        for attempt in range(3):
            try:
                resp = self.client.messages.create(**kwargs)
                for block in resp.content:
                    if block.type == "text":
                        return block.text
                # 如果没有找到 text 块, 尝试返回第一个块的内容
                return str(resp.content[0]) if resp.content else ""
            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM 调用失败，已重试 3 次: {last_error}")
