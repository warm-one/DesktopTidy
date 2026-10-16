"""规则引擎的单元测试。"""
import os
import tempfile
import time
import unittest

from desktop_tidy.rules import build_plan_from_rules, category_of, generate_plans
from desktop_tidy.scanner import DesktopItem


class TestRules(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.desktop = tmp.name

    def make_item(self, name, ext, is_dir=False, days_old=0):
        return DesktopItem(
            name=name,
            ext=ext,
            size=10,
            mtime=time.time() - days_old * 86400,
            path=os.path.join(self.desktop, name),
            is_dir=is_dir,
        )

    def test_category_of(self):
        self.assertEqual(category_of("png"), "图片")
        self.assertEqual(category_of("EXE"), "安装包")
        self.assertIsNone(category_of("xyz"))

    def test_conservative_plan(self):
        items = [
            self.make_item("old_setup.exe", "exe", days_old=40),
            self.make_item("new_setup.exe", "exe", days_old=1),
            self.make_item("old_photo.png", "png", days_old=40),  # 旧但不是安装包/压缩包
            self.make_item("老压缩包.zip", "zip", days_old=60),
            self.make_item("文件夹", "", is_dir=True),
        ]
        plans = generate_plans(items, self.desktop)
        conservative = plans[0]
        self.assertEqual(conservative.name, "保守")
        moved = {os.path.basename(a.src) for a in conservative.actions}
        self.assertEqual(moved, {"old_setup.exe", "老压缩包.zip"})
        # 目标必须是桌面内的分类文件夹
        dst = next(a for a in conservative.actions if "zip" in a.src).dst
        self.assertEqual(dst, os.path.join(self.desktop, "压缩包", "老压缩包.zip"))

    def test_standard_plan(self):
        items = [
            self.make_item("photo.png", "png"),
            self.make_item("报告.docx", "docx"),
            self.make_item("setup.exe", "exe"),
            self.make_item("未知文件", ""),  # 未识别类型 → 保持不动
            self.make_item("文件夹", "", is_dir=True),  # 文件夹 → 永不处理
        ]
        plans = generate_plans(items, self.desktop)
        standard = plans[1]
        self.assertEqual(standard.name, "标准")
        by_name = {os.path.basename(a.src): a for a in standard.actions}
        self.assertEqual(set(by_name), {"photo.png", "报告.docx", "setup.exe"})
        self.assertEqual(
            by_name["photo.png"].dst, os.path.join(self.desktop, "图片", "photo.png")
        )
        self.assertEqual(
            by_name["报告.docx"].dst, os.path.join(self.desktop, "文档", "报告.docx")
        )

    def test_no_actions_when_no_categorized_files(self):
        plans = generate_plans([self.make_item("未知文件", "")], self.desktop)
        self.assertEqual(plans[0].total, 0)
        self.assertEqual(plans[1].total, 0)

    def test_shortcuts_never_moved(self):
        # 快捷方式硬约束:任何方案都不得移动快捷方式
        from desktop_tidy.rules import is_shortcut

        lnk = self.make_item("微信.lnk", "lnk")
        url = self.make_item("游戏官网.url", "url")
        fake = self.make_item("仿冒论文.lnk", "lnk")  # 就算名字命中关键词也不动
        rules = [{"keywords": ["论文", "微信", "官网"], "folder": "学术"}]

        for item in (lnk, url, fake):
            self.assertTrue(is_shortcut(item))
            plans = generate_plans([item], self.desktop)
            self.assertEqual(plans[0].total, 0)
            self.assertEqual(plans[1].total, 0)
            custom = build_plan_from_rules([item], self.desktop, rules)
            self.assertEqual(custom.total, 0)

    def test_build_plan_from_rules(self):
        items = [
            self.make_item("毕业论文v3.docx", "docx"),
            self.make_item("Paper-Notes.txt", "txt"),  # 大小写不敏感匹配 paper
            self.make_item("游戏.exe", "exe"),  # 未命中 → 保留
            self.make_item("文件夹", "", is_dir=True),  # 文件夹 → 永不处理
        ]
        rules = [
            {"keywords": ["论文", "paper"], "folder": "学术"},
            {"keywords": ["游戏"], "folder": "娱乐"},
        ]
        plan = build_plan_from_rules(items, self.desktop, rules)
        self.assertEqual(plan.name, "自定义")
        by_name = {os.path.basename(a.src): a for a in plan.actions}
        # 命中第一条规则的"论文" → 学术;paper 不区分大小写命中
        self.assertEqual(
            by_name["毕业论文v3.docx"].dst, os.path.join(self.desktop, "学术", "毕业论文v3.docx")
        )
        self.assertEqual(
            by_name["Paper-Notes.txt"].dst, os.path.join(self.desktop, "学术", "Paper-Notes.txt")
        )
        # "游戏" 命中第二条规则;未命中与文件夹不出现
        self.assertIn("游戏.exe", by_name)
        self.assertEqual(len(plan.actions), 3)


if __name__ == "__main__":
    unittest.main()
