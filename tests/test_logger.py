"""日志模块的单元测试。"""
import os
import tempfile
import unittest

from desktop_tidy.logger import (
    BatchLogger,
    cleanup_old_batches,
    list_batches,
    read_batch,
)


class TestLogger(unittest.TestCase):
    def test_append_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            batch = BatchLogger(log_dir=d)
            batch.log("move", "C:/a.png", "C:/图片/a.png", "测试", size=3)
            batch.log("skip", "C:/b.txt", "C:/文档/b.txt", "原因")

            records = read_batch(batch.batch_path)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["action"], "move")
            self.assertEqual(records[0]["src"], "C:/a.png")
            self.assertEqual(records[0]["size"], 3)
            self.assertEqual(records[0]["batch_id"], batch.batch_id)
            self.assertEqual(records[1]["reason"], "原因")

    def test_batch_ids_unique(self):
        with tempfile.TemporaryDirectory() as d:
            b1 = BatchLogger(log_dir=d)
            b1.log("move", "a", "b", "")
            b2 = BatchLogger(log_dir=d)
            b2.log("move", "c", "d", "")
            self.assertNotEqual(b1.batch_id, b2.batch_id)
            self.assertEqual(len(list_batches(d)), 2)

    def test_cleanup_keeps_most_recent(self):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i in range(35):
                p = os.path.join(d, f"batch-20260101-0000{i:02d}-{i:08d}.jsonl")
                with open(p, "w", encoding="utf-8") as f:
                    f.write("")
                paths.append(p)

            removed = cleanup_old_batches(log_dir=d, keep=30)
            self.assertEqual(len(removed), 5)
            self.assertEqual(removed, paths[:5])  # 删的是最旧的 5 个
            self.assertEqual(len(list_batches(d)), 30)

    def test_read_bad_lines_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            batch = BatchLogger(log_dir=d)
            batch.log("move", "a", "b", "")
            with open(batch.batch_path, "a", encoding="utf-8") as f:
                f.write("这不是JSON{{{\n")
            records = read_batch(batch.batch_path)
            self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
