"""本地手动规则模块的单元测试。"""
import os
import tempfile
import unittest
from unittest import mock

from desktop_tidy import manual_rules


class TestNormalizeRule(unittest.TestCase):
    def test_valid_string_keywords(self):
        rule = manual_rules.normalize_rule({"keywords": "论文, 报告", "folder": "学术资料"})
        self.assertEqual(rule, {"keywords": ["论文", "报告"], "folder": "学术资料"})

    def test_full_width_comma_separator(self):
        rule = manual_rules.normalize_rule({"keywords": "论文，报告", "folder": "学术资料"})
        self.assertEqual(rule["keywords"], ["论文", "报告"])

    def test_list_keywords_dedup_ignore_case(self):
        rule = manual_rules.normalize_rule({"keywords": ["论文", "论文", "报告"], "folder": "学术资料"})
        self.assertEqual(rule["keywords"], ["论文", "报告"])

    def test_empty_keywords_rejected(self):
        self.assertIsNone(manual_rules.normalize_rule({"keywords": "  ", "folder": "学术资料"}))

    def test_illegal_folder_chars_rejected(self):
        for bad in ("a\\b", "a/b", "a:b", "a*b", 'a"b', "a<b", "a>b", "a|b"):
            self.assertIsNone(manual_rules.normalize_rule({"keywords": "论文", "folder": bad}))

    def test_non_dict_rejected(self):
        self.assertIsNone(manual_rules.normalize_rule("论文 -> 学术资料"))

    def test_folder_trimmed_and_whitespace_only_rejected(self):
        self.assertIsNone(manual_rules.normalize_rule({"keywords": "论文", "folder": "   "}))


class TestRuleStore(unittest.TestCase):
    """add/load/remove 全流程:真实读写 config.json(隔离到临时 APPDATA)。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"APPDATA": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_add_load_remove_roundtrip(self):
        added = manual_rules.add_rule("论文, 报告", "学术资料")
        self.assertEqual(added, {"keywords": ["论文", "报告"], "folder": "学术资料"})
        self.assertEqual(manual_rules.load_rules(), [added])

        # 同一 APPDATA 环境下直接再加一条,序号删除要按列表位置
        manual_rules.add_rule("发票", "票据")
        self.assertTrue(manual_rules.remove_rule(0))
        rules = manual_rules.load_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["folder"], "票据")

    def test_add_invalid_rule_returns_none(self):
        self.assertIsNone(manual_rules.add_rule("", "学术资料"))
        self.assertIsNone(manual_rules.add_rule("论文", "a/b"))
        self.assertEqual(manual_rules.load_rules(), [])

    def test_remove_out_of_range(self):
        manual_rules.add_rule("论文", "学术资料")
        self.assertFalse(manual_rules.remove_rule(1))
        self.assertFalse(manual_rules.remove_rule(-3))
        self.assertEqual(len(manual_rules.load_rules()), 1)

    def test_load_discards_corrupt_entries_and_bad_field_type(self):
        # 手工写坏数据:非 dict 条目、缺 keywords 的条目都应被丢弃
        from desktop_tidy.config import save_config, load_config
        cfg = load_config()
        cfg["manual_rules"] = ["不是字典", {"folder": "学术资料"}, {"keywords": "论文", "folder": "学术资料"}]
        save_config(cfg)
        rules = manual_rules.load_rules()
        self.assertEqual(rules, [{"keywords": ["论文"], "folder": "学术资料"}])

    def test_manual_rules_field_not_list_falls_back_empty(self):
        from desktop_tidy.config import load_config, save_config
        cfg = load_config()
        cfg["manual_rules"] = {"keywords": "论文", "folder": "学术资料"}
        save_config(cfg)
        self.assertEqual(manual_rules.load_rules(), [])


if __name__ == "__main__":
    unittest.main()
