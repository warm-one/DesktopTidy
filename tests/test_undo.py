"""撤销模块的单元测试,重点覆盖撤销边界(AGENT.md 第 11 节要求)。"""
import os
import tempfile
import unittest

from desktop_tidy.executor import execute
from desktop_tidy.logger import BatchLogger
from desktop_tidy.rules import generate_plans
from desktop_tidy.scanner import scan_desktop
from desktop_tidy.undo import undo_last


class TestUndo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.desktop = tmp.name
        log_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(log_tmp.cleanup)
        self.log_dir = log_tmp.name

    def make_file(self, name, content=b"data"):
        path = os.path.join(self.desktop, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def organize(self, plan_index=1):
        """跑一次真实的整理流程(扫描 → 方案 → 执行),返回执行结果。"""
        result = scan_desktop(self.desktop)
        plans = generate_plans(result.items, self.desktop)
        batch = BatchLogger(log_dir=self.log_dir)
        return execute(plans[plan_index].actions, self.desktop, batch)

    def test_undo_restores_files(self):
        self.make_file("a.png", b"png-data")
        self.make_file("b.docx", b"doc-data")
        self.assertEqual(self.organize().moved, 2)
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "图片", "a.png")))

        summary = undo_last(self.desktop, log_dir=self.log_dir)
        self.assertIsNotNone(summary)
        self.assertEqual((summary.moved, summary.skipped, summary.failed), (2, 0, 0))
        # 文件回到桌面顶层原位,内容不变
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "a.png")))
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "b.docx")))
        with open(os.path.join(self.desktop, "a.png"), "rb") as f:
            self.assertEqual(f.read(), b"png-data")
        self.assertFalse(os.path.exists(os.path.join(self.desktop, "图片", "a.png")))

    def test_undo_conflict_when_original_occupied(self):
        # 撤销时原位置被占用 → 跳过并记录冲突,绝不覆盖
        self.make_file("a.png", b"original")
        self.organize()
        self.make_file("a.png", b"new-occupies")

        summary = undo_last(self.desktop, log_dir=self.log_dir)
        self.assertEqual(summary.moved, 0)
        self.assertEqual(summary.skipped, 1)
        # 双方都完好:桌面上的新文件 + 文件夹里的旧文件
        with open(os.path.join(self.desktop, "a.png"), "rb") as f:
            self.assertEqual(f.read(), b"new-occupies")
        with open(os.path.join(self.desktop, "图片", "a.png"), "rb") as f:
            self.assertEqual(f.read(), b"original")

    def test_undo_missing_dst_skipped(self):
        # 整理后文件被手动移走/删除 → 撤销跳过
        self.make_file("a.png")
        self.organize()
        os.remove(os.path.join(self.desktop, "图片", "a.png"))

        summary = undo_last(self.desktop, log_dir=self.log_dir)
        self.assertEqual(summary.moved, 0)
        self.assertEqual(summary.skipped, 1)

    def test_undo_only_once_per_batch(self):
        # 同一批次只能撤销一次:第二次 undo 无目标
        self.make_file("a.png")
        self.organize()
        first = undo_last(self.desktop, log_dir=self.log_dir)
        self.assertEqual(first.moved, 1)
        second = undo_last(self.desktop, log_dir=self.log_dir)
        self.assertIsNone(second)

    def test_undo_after_two_batches_targets_latest(self):
        # 连续两次整理:undo 只撤销最近一次
        self.make_file("a.png")
        self.organize()
        self.make_file("b.png")
        self.organize()
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "图片", "b.png")))

        summary = undo_last(self.desktop, log_dir=self.log_dir)
        self.assertEqual(summary.moved, 1)
        # b.png 回到桌面,a.png 仍在文件夹里(属于更早的批次)
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "b.png")))
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "图片", "a.png")))

    def test_nothing_to_undo(self):
        self.assertIsNone(undo_last(self.desktop, log_dir=self.log_dir))


if __name__ == "__main__":
    unittest.main()
