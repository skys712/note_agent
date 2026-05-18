import time
from dataclasses import dataclass

from openai import OpenAI

from novel_writer.config import get_config


@dataclass
class LLMResponse:
    """LLM 调用结果"""
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLMClient:
    """OpenAI SDK 封装，使用 DeepSeek 原生 API"""

    def __init__(self):
        cfg = get_config()
        self.client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            timeout=600.0,
        )
        self.model = cfg["model"]
        self.default_max_tokens = cfg["max_tokens"]
        self.thinking = cfg.get("thinking")

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int | None = None,
        on_progress: "callable | None" = None,
    ) -> LLMResponse:
        """发送聊天请求。on_progress(total_chars) 在流式接收时回调。"""
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        kwargs: dict = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": max_tokens or self.default_max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.thinking:
            kwargs["extra_body"] = {"thinking": self.thinking}

        last_error = None
        for attempt in range(3):
            try:
                stream = self.client.chat.completions.create(**kwargs)
                content_parts: list[str] = []
                usage = None
                model = self.model
                total_chars = 0
                for chunk in stream:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            text = delta.content
                            content_parts.append(text)
                            total_chars += len(text)
                        elif hasattr(delta, "reasoning_content") and delta.reasoning_content:
                            total_chars += len(delta.reasoning_content)
                        if on_progress and total_chars > 0:
                            on_progress(total_chars)
                    if chunk.usage:
                        usage = chunk.usage
                    if chunk.model:
                        model = chunk.model

                return LLMResponse(
                    content="".join(content_parts),
                    input_tokens=usage.prompt_tokens if usage else 0,
                    output_tokens=usage.completion_tokens if usage else 0,
                    model=model,
                )
            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM 调用失败，已重试 3 次: {last_error}")
