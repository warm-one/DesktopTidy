"""AI 转规则模块的单元测试(只测解析/校验,不访问网络)。"""
import json
import unittest

from desktop_tidy.ai_rules import (
    AIError,
    build_user_prompt,
    parse_rules,
    sanitize_folder,
)


class TestSanitizeFolder(unittest.TestCase):
    def test_valid_names(self):
        self.assertEqual(sanitize_folder("论文资料"), "论文资料")
        self.assertEqual(sanitize_folder(" Papers 2024 "), "Papers 2024")

    def test_invalid_names(self):
        self.assertEqual(sanitize_folder(""), "")
        self.assertEqual(sanitize_folder(".."), "")
        self.assertEqual(sanitize_folder("a/b"), "")  # 路径分隔符
        self.assertEqual(sanitize_folder('a"b:c'), "")
        self.assertEqual(sanitize_folder("x" * 41), "")  # 超长


class TestParseRules(unittest.TestCase):
    def test_plain_json(self):
        rules = parse_rules('{"rules": [{"keywords": ["论文"], "folder": "学术"}]}')
        self.assertEqual(rules, [{"keywords": ["论文"], "folder": "学术"}])

    def test_markdown_fence_tolerated(self):
        text = '```json\n{"rules": [{"keywords": ["发票"], "folder": "票据"}]}\n```'
        self.assertEqual(parse_rules(text)[0]["folder"], "票据")

    def test_invalid_entries_skipped(self):
        text = (
            '{"rules": ['
            '{"keywords": ["论文"], "folder": "学术"}, '  # 有效
            '{"keywords": [], "folder": "空关键词"}, '  # 关键词为空 → 跳过
            '{"keywords": ["x"], "folder": "坏/名"}, '  # 文件夹名非法 → 跳过
            '"not-a-dict"'  # 非对象 → 跳过
            "]}"
        )
        rules = parse_rules(text)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["folder"], "学术")

    def test_limits_enforced(self):
        many = json.dumps(
            {"rules": [{"keywords": [f"k{i}" for i in range(30)], "folder": "测试"}]}
        )
        rules = parse_rules(many)
        self.assertEqual(len(rules), 1)
        self.assertEqual(len(rules[0]["keywords"]), 20)  # 关键词数量截断

    def test_error_cases(self):
        with self.assertRaises(AIError):
            parse_rules("我不是 JSON")
        with self.assertRaises(AIError):
            parse_rules('{"rules": []}')
        with self.assertRaises(AIError):
            parse_rules('{"rules": [{"keywords": ["a"], "folder": "坏/名"}]}')

    def test_build_user_prompt_truncates_names(self):
        names = [f"file{i}.txt" for i in range(500)]
        prompt = build_user_prompt("整理", names)
        self.assertNotIn("file300.txt", prompt)  # 超出上限的文件名被截断
        self.assertIn("整理", prompt)


if __name__ == "__main__":
    unittest.main()
