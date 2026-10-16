"""用户配置模块的单元测试。"""
import json
import os
import tempfile
import unittest
from unittest import mock

from desktop_tidy.config import config_path, load_config, save_config


class TestConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # 把 APPDATA 指到临时目录,避免碰真实配置
        patcher = mock.patch.dict(os.environ, {"APPDATA": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_defaults_when_missing(self):
        cfg = load_config()
        self.assertTrue(cfg["first_run"])
        self.assertEqual(cfg["ai"]["model"], "deepseek-chat")
        self.assertEqual(cfg["ai"]["api_key"], "")

    def test_save_load_roundtrip(self):
        cfg = load_config()
        cfg["first_run"] = False
        cfg["ai"]["api_key"] = "sk-test"
        save_config(cfg)

        loaded = load_config()
        self.assertFalse(loaded["first_run"])
        self.assertEqual(loaded["ai"]["api_key"], "sk-test")
        self.assertEqual(loaded["ai"]["model"], "deepseek-chat")  # 默认项保留

    def test_partial_ai_merge_keeps_defaults(self):
        # 手工写一个只有 api_key 的 ai 字段,其余默认项应保留
        os.makedirs(os.path.dirname(config_path()), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump({"ai": {"api_key": "sk-x"}}, f)
        cfg = load_config()
        self.assertEqual(cfg["ai"]["api_key"], "sk-x")
        self.assertEqual(cfg["ai"]["model"], "deepseek-chat")

    def test_corrupted_file_returns_defaults(self):
        os.makedirs(os.path.dirname(config_path()), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as f:
            f.write("这不是JSON{{{")
        cfg = load_config()
        self.assertTrue(cfg["first_run"])  # 回退到默认值


if __name__ == "__main__":
    unittest.main()
