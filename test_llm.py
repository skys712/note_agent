"""Test DeepSeek native API via OpenAI SDK."""
import sys

# Ensure UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from novel_writer.config import get_config
from novel_writer.core.llm import LLMClient

cfg = get_config()
print("=== Config ===")
print(f"base_url: {cfg['base_url']}")
print(f"model: {cfg['model']}")
print(f"max_tokens: {cfg['max_tokens']}")
print()

llm = LLMClient()

# Test 1: Basic chat
print("=== Test 1: Basic chat ===")
try:
    resp = llm.chat(
        messages=[{"role": "user", "content": "Say hello in exactly one sentence."}],
        max_tokens=100,
    )
    print(f"[OK] Response: {resp.content.strip()}")
    print(f"     Input: {resp.input_tokens}tk, Output: {resp.output_tokens}tk, Model: {resp.model}")
except Exception as e:
    print(f"[FAIL] {e}")

# Test 2: With system prompt (Chinese)
print("\n=== Test 2: With system prompt ===")
try:
    resp = llm.chat(
        messages=[{"role": "user", "content": "请用一句话介绍你自己。"}],
        system="请始终用中文回复。",
        max_tokens=200,
    )
    print(f"[OK] Response: {resp.content.strip()}")
    print(f"     Input: {resp.input_tokens}tk, Output: {resp.output_tokens}tk")
except Exception as e:
    print(f"[FAIL] {e}")

# Test 3: Longer response (like novel writing)
print("\n=== Test 3: Longer response ===")
try:
    resp = llm.chat(
        messages=[{"role": "user", "content": "写一段200字左右的场景描写：一个雨夜的街道。"}],
        system="你是一个小说写作助手。请用中文回复。",
        max_tokens=1000,
    )
    print(f"[OK] Response ({len(resp.content)} chars):")
    print(resp.content[:300])
    if len(resp.content) > 300:
        print("    ... (truncated)")
    print(f"    Input: {resp.input_tokens}tk, Output: {resp.output_tokens}tk")
except Exception as e:
    print(f"[FAIL] {e}")

print("\n=== All tests complete ===")
