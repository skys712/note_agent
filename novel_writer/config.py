import os


def get_config() -> dict:
    return {
        "api_key": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        "base_url": os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic"),
        "model": os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro"),
        "max_tokens": int(os.environ.get("ANTHROPIC_MAX_TOKENS", "8192")),
    }
