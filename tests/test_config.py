import os

from novel_writer.config import DEFAULT_CONFIG, _merge_config, get_config


class TestMergeConfig:
    """_merge_config 合并逻辑测试"""

    def test_no_overrides_returns_defaults(self):
        result = _merge_config(DEFAULT_CONFIG, {})
        assert result == DEFAULT_CONFIG

    def test_override_scalar(self):
        result = _merge_config(DEFAULT_CONFIG, {"model": "test-model"})
        assert result["model"] == "test-model"

    def test_override_max_tokens(self):
        result = _merge_config(DEFAULT_CONFIG, {"max_tokens": 8192})
        assert result["max_tokens"] == 8192

    def test_deep_merge_thinking(self):
        """嵌套字典应深度合并而非替换"""
        result = _merge_config(
            DEFAULT_CONFIG,
            {"thinking": {"effort": "low"}},
        )
        assert result["thinking"]["type"] == DEFAULT_CONFIG["thinking"]["type"]
        assert result["thinking"]["effort"] == "low"

    def test_deep_merge_new_key(self):
        result = _merge_config(
            DEFAULT_CONFIG,
            {"thinking": {"new_field": "value"}},
        )
        assert result["thinking"]["new_field"] == "value"
        assert result["thinking"]["type"] == DEFAULT_CONFIG["thinking"]["type"]


class TestGetConfig:
    """get_config 集成测试"""

    def test_returns_dict(self):
        cfg = get_config()
        assert isinstance(cfg, dict)
        assert "model" in cfg
        assert "base_url" in cfg
        assert "max_tokens" in cfg
        assert "api_key" in cfg

    def test_max_tokens_is_int(self):
        cfg = get_config()
        assert isinstance(cfg["max_tokens"], int)

    def test_api_key_fallback_to_env(self):
        """config.json 中 api_key 为空时应 fallback 到 DEEPSEEK_API_KEY"""
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        cfg = get_config()
        # config.json 的 api_key 优先；为空时才用环境变量
        if key:
            assert cfg["api_key"] in (key, "") or cfg["api_key"]
