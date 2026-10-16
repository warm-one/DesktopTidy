"""执行模块的单元测试,重点覆盖安全边界(AGENT.md 第 11 节要求)。"""
import os
import tempfile
import unittest
from unittest import mock

from desktop_tidy.actions import MoveFileAction
from desktop_tidy.executor import execute, unique_dst
from desktop_tidy.logger import BatchLogger, read_batch


class TestExecutor(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.desktop = tmp.name
        log_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(log_tmp.cleanup)
        self.log_dir = log_tmp.name  # 故意放在桌面之外,兼作"越界路径"测试素材

    def make_action(self, name, folder="图片"):
        return MoveFileAction(
            src=os.path.join(self.desktop, name),
            dst=os.path.join(self.desktop, folder, name),
            reason="测试",
        )

    def run_execute(self, actions):
        batch = BatchLogger(log_dir=self.log_dir)
        result = execute(actions, self.desktop, batch)
        return result, batch

    def test_move_file_into_category_folder(self):
        with open(os.path.join(self.desktop, "a.png"), "wb") as f:
            f.write(b"png-data")
        result, batch = self.run_execute([self.make_action("a.png")])

        self.assertEqual((result.moved, result.skipped, result.failed), (1, 0, 0))
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "图片", "a.png")))
        self.assertFalse(os.path.exists(os.path.join(self.desktop, "a.png")))

        records = read_batch(batch.batch_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["action"], "move")
        self.assertEqual(records[0]["size"], 8)
        self.assertTrue(records[0]["batch_id"].startswith("batch-"))

    def test_never_overwrite_existing_dst(self):
        # 目标已有同名文件 → 自动加 (1),原文件内容绝不被覆盖
        with open(os.path.join(self.desktop, "a.png"), "wb") as f:
            f.write(b"new")
        os.makedirs(os.path.join(self.desktop, "图片"))
        with open(os.path.join(self.desktop, "图片", "a.png"), "wb") as f:
            f.write(b"old-kept")

        result, _ = self.run_execute([self.make_action("a.png")])
        self.assertEqual(result.moved, 1)

        with open(os.path.join(self.desktop, "图片", "a.png"), "rb") as f:
            self.assertEqual(f.read(), b"old-kept")  # 原文件完好
        with open(os.path.join(self.desktop, "图片", "a (1).png"), "rb") as f:
            self.assertEqual(f.read(), b"new")  # 新文件落到 (1)

    def test_multiple_collisions(self):
        with open(os.path.join(self.desktop, "a.png"), "wb") as f:
            f.write(b"new")
        os.makedirs(os.path.join(self.desktop, "图片"))
        for name in ("a.png", "a (1).png", "a (2).png"):
            with open(os.path.join(self.desktop, "图片", name), "wb") as f:
                f.write(b"old")

        result, _ = self.run_execute([self.make_action("a.png")])
        self.assertEqual(result.moved, 1)
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "图片", "a (3).png")))

    def test_unique_dst(self):
        dst = os.path.join(self.desktop, "a.png")
        self.assertEqual(unique_dst(dst), dst)  # 不存在 → 原名
        with open(dst, "wb") as f:
            f.write(b"x")
        self.assertEqual(unique_dst(dst), os.path.join(self.desktop, "a (1).png"))

    def test_skip_when_src_missing(self):
        result, batch = self.run_execute([self.make_action("不存在.txt", "文档")])
        self.assertEqual((result.moved, result.skipped, result.failed), (0, 1, 0))
        records = read_batch(batch.batch_path)
        self.assertEqual(records[0]["action"], "skip")

    def test_skip_directory_src(self):
        # 铁律 4:绝不移动文件夹
        os.makedirs(os.path.join(self.desktop, "文件夹"))
        action = MoveFileAction(
            src=os.path.join(self.desktop, "文件夹"),
            dst=os.path.join(self.desktop, "文档", "文件夹"),
            reason="测试",
        )
        result, _ = self.run_execute([action])
        self.assertEqual((result.moved, result.skipped, result.failed), (0, 1, 0))
        self.assertTrue(os.path.isdir(os.path.join(self.desktop, "文件夹")))
        self.assertFalse(os.path.exists(os.path.join(self.desktop, "文档")))

    def test_reject_paths_outside_desktop(self):
        # 铁律 5:只操作桌面内部,越界一律拒绝、原封不动
        outside = os.path.join(self.log_dir, "outside.txt")
        with open(outside, "wb") as f:
            f.write(b"x")
        action = MoveFileAction(
            src=outside,
            dst=os.path.join(self.desktop, "文档", "outside.txt"),
            reason="测试",
        )
        result, _ = self.run_execute([action])
        self.assertEqual((result.moved, result.skipped, result.failed), (0, 1, 0))
        self.assertTrue(os.path.exists(outside))

    def test_locked_file_recorded_as_fail(self):
        # 文件被占用 → 记录失败、继续运行,不崩溃、不中断
        with open(os.path.join(self.desktop, "locked.txt"), "wb") as f:
            f.write(b"x")
        action = self.make_action("locked.txt", "文档")
        with mock.patch(
            "desktop_tidy.executor.os.rename",
            side_effect=PermissionError(13, "文件被占用"),
        ):
            result, batch = self.run_execute([action])

        self.assertEqual((result.moved, result.skipped, result.failed), (0, 0, 1))
        records = read_batch(batch.batch_path)
        self.assertEqual(records[0]["action"], "fail")
        self.assertIn("占用", records[0]["reason"])
        self.assertTrue(os.path.exists(os.path.join(self.desktop, "locked.txt")))

    def test_failure_does_not_stop_later_moves(self):
        # 中途失败不中断:第一个失败,第二个照常移动
        with open(os.path.join(self.desktop, "a.png"), "wb") as f:
            f.write(b"a")
        with open(os.path.join(self.desktop, "b.png"), "wb") as f:
            f.write(b"b")
        actions = [self.make_action("a.png"), self.make_action("b.png")]
        real_rename = os.rename

        def flaky_rename(src, dst):
            if os.path.basename(src) == "a.png":
                raise PermissionError(13, "文件被占用")
            return real_rename(src, dst)

        batch = BatchLogger(log_dir=self.log_dir)
        with mock.patch("desktop_tidy.executor.os.rename", side_effect=flaky_rename):
            result = execute(actions, self.desktop, batch)

        self.assertEqual((result.moved, result.failed), (1, 1))
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "图片", "b.png")))
        self.assertTrue(os.path.exists(os.path.join(self.desktop, "a.png")))


if __name__ == "__main__":
    unittest.main()
