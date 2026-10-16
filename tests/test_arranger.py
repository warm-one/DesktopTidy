"""图标分区排列模块的单元测试(纯数据逻辑,不碰真实桌面)。"""
import unittest

from desktop_tidy.arranger import DesktopIcon, _grid_metrics, is_auto_arrange_on


def make_icons(coords):
    return [DesktopIcon(i, f"item{i}", x, y) for i, (x, y) in enumerate(coords)]


class TestAutoArrangeHeuristic(unittest.TestCase):
    def test_packed_grid_is_on(self):
        # 自动排列开启:槽位按列优先从 0 连续填满
        coords = [(14, 2), (14, 100), (14, 198), (90, 2), (90, 100)]
        self.assertTrue(is_auto_arrange_on(make_icons(coords)))

    def test_last_column_partial_is_on(self):
        # 只有最后一列不满是自动排列的正常现象
        coords = [(14, 2), (14, 100), (14, 198), (90, 2)]
        self.assertTrue(is_auto_arrange_on(make_icons(coords)))

    def test_bottom_hole_in_middle_column_is_off(self):
        # 中间列底部空着但后面还有列 → 有空洞 → 关闭
        coords = [(14, 2), (14, 100), (14, 198), (90, 2), (166, 2), (166, 100)]
        self.assertFalse(is_auto_arrange_on(make_icons(coords)))

    def test_middle_hole_is_off(self):
        # 列中间缺一格 → 关闭
        coords = [(14, 2), (14, 198), (90, 2), (90, 100), (90, 198)]
        self.assertFalse(is_auto_arrange_on(make_icons(coords)))

    def test_empty_middle_column_is_off(self):
        # 中间整列空缺(图标跳到隔列)→ 关闭
        coords = [(14, 2), (14, 100), (90, 2), (90, 100), (242, 2)]
        self.assertFalse(is_auto_arrange_on(make_icons(coords)))

    def test_off_grid_icon_is_off(self):
        # 有图标不在网格上 → 关闭
        coords = [(14, 2), (14, 100), (90, 2), (200, 2)]
        self.assertFalse(is_auto_arrange_on(make_icons(coords)))

    def test_single_icon_counts_as_on(self):
        self.assertTrue(is_auto_arrange_on([DesktopIcon(0, "a", 14, 2)]))
        self.assertTrue(is_auto_arrange_on([]))


class TestGridMetrics(unittest.TestCase):
    def test_pitch_and_rows(self):
        coords = [(14, 2), (14, 100), (90, 2), (90, 100), (166, 2)]
        icons = make_icons(coords)
        ox, oy, col, row = _grid_metrics(icons, 1000)
        self.assertEqual(ox, 14)
        self.assertEqual(oy, 2)
        self.assertEqual(col, 76)
        self.assertEqual(row, 98)
        rows = (1000 - 2) // row
        self.assertEqual(rows, 10)


if __name__ == "__main__":
    unittest.main()
