"""scanner 只读扫描的单元测试。"""
import os
import sys
import tempfile
import unittest

from desktop_tidy.scanner import scan_desktop


def make_file(root: str, name: str, content: bytes = b"x") -> str:
    path = os.path.join(root, name)
    with open(path, "wb") as f:
        f.write(content)
    return path


class TestScanner(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.desktop = tmp.name

    def test_scan_returns_files_and_dirs(self):
        make_file(self.desktop, "photo.png", b"12345")
        make_file(self.desktop, "notes.txt")
        make_file(self.desktop, "setup.exe")
        make_file(self.desktop, "README")
        os.mkdir(os.path.join(self.desktop, "旧文件夹"))

        result = scan_desktop(self.desktop)
        names = {i.name: i for i in result.items}

        self.assertEqual(len(result.items), 5)
        self.assertEqual(names["photo.png"].ext, "png")
        self.assertEqual(names["photo.png"].size, 5)
        self.assertFalse(names["photo.png"].is_dir)
        self.assertEqual(names["README"].ext, "")
        self.assertTrue(names["旧文件夹"].is_dir)
        self.assertEqual(names["旧文件夹"].size, 0)
        self.assertEqual(
            names["photo.png"].path, os.path.join(self.desktop, "photo.png")
        )

    def test_desktop_ini_excluded(self):
        make_file(self.desktop, "desktop.ini")
        make_file(self.desktop, "a.txt")
        result = scan_desktop(self.desktop)
        self.assertEqual([i.name for i in result.items], ["a.txt"])
        self.assertEqual(result.skipped, 1)

    @unittest.skipIf(sys.platform != "win32", "仅 Windows 有隐藏属性")
    def test_hidden_file_excluded(self):
        import ctypes

        path = make_file(self.desktop, "secret.txt")
        # FILE_ATTRIBUTE_HIDDEN = 0x2
        ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)
        make_file(self.desktop, "normal.txt")

        result = scan_desktop(self.desktop)
        self.assertEqual({i.name for i in result.items}, {"normal.txt"})
        self.assertEqual(result.skipped, 1)

    def test_empty_desktop(self):
        result = scan_desktop(self.desktop)
        self.assertEqual(result.items, [])
        self.assertEqual(result.skipped, 0)

    def test_scan_is_read_only(self):
        # 扫描前后目录内容不应有任何变化
        make_file(self.desktop, "a.txt")
        before = sorted(os.listdir(self.desktop))
        scan_desktop(self.desktop)
        self.assertEqual(sorted(os.listdir(self.desktop)), before)


if __name__ == "__main__":
    unittest.main()
