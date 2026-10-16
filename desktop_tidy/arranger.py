"""图标分区排列模块(B 方案第一版)。

用户选择了"整理后自动排序":整理后把桌面图标排成紧凑网格,
分区顺序:系统图标 → 文件夹 → 快捷方式 → 其他文件。

实现方式(不依赖 COM,全部走已验证的跨进程 ListView 消息):
- 读取图标名称与坐标:LVM_GETITEMTEXTW / LVM_GETITEMPOSITION(远程内存)
- 判断是否开启自动排列:列内坐标空洞分析(自动排列开启时列内连续无空洞)
- 摆放:LVM_SETITEMPOSITION(仅自动排列关闭时可持久生效)
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import byref, c_long, create_unicode_buffer, sizeof, wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .rules import is_shortcut

if ctypes.windll:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

logger = logging.getLogger(__name__)

LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETITEMPOSITION = LVM_FIRST + 16
LVM_SETITEMPOSITION = LVM_FIRST + 15
LVM_GETITEMTEXTW = LVM_FIRST + 115

PROCESS_VM_OPERATION = 0x8
PROCESS_VM_READ = 0x10
PROCESS_VM_WRITE = 0x20
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x4
MEM_RELEASE = 0x8000

LVIF_TEXT = 0x1

MARGIN_X = 14
MARGIN_Y = 2


class POINT(ctypes.Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("iItem", ctypes.c_int),
        ("iSubItem", wintypes.UINT),
        ("state", wintypes.UINT),
        ("stateMask", wintypes.UINT),
        ("pszText", wintypes.LPWSTR),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", wintypes.LPARAM),
        ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int),
        ("cColumns", wintypes.UINT),
        ("puColumns", wintypes.UINT),
        ("piColFmt", ctypes.c_int),
        ("iGroup", ctypes.c_int),
    ]


@dataclass
class DesktopIcon:
    index: int
    name: str
    x: int
    y: int


def find_desktop_listview() -> Optional[int]:
    """找到桌面图标列表窗口(SHELLDLL_DefView 的 SysListView32 子窗口)。"""
    progman = user32.FindWindowW("Progman", None)
    defview = None
    if progman:
        defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
    if not defview:
        # 动态壁纸等场景下 DefView 可能挂在 WorkerW 下
        found = []

        _ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [_ENUMPROC, wintypes.LPARAM]

        def _cb(hwnd, _lp):
            buf = create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, buf, 64)
            if buf.value == "WorkerW":
                child = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
                if child:
                    found.append(child)
                    return False
            return True

        cb = _ENUMPROC(_cb)
        user32.EnumWindows(cb, 0)
        defview = found[0] if found else None
    if not defview:
        return None
    return user32.FindWindowExW(defview, None, "SysListView32", None)


def _open_listview_process(hwnd_list: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd_list, byref(pid))
    proc = kernel32.OpenProcess(
        PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE, False, pid.value
    )
    if not proc:
        raise OSError("无法打开桌面进程(权限不足)")
    return proc


def read_icons(hwnd_list: Optional[int] = None) -> List[DesktopIcon]:
    """读取桌面全部图标的名称与坐标。失败时抛出 OSError。"""
    if hwnd_list is None:
        hwnd_list = find_desktop_listview()
    if not hwnd_list:
        raise OSError("未找到桌面图标窗口")

    count = user32.SendMessageW(hwnd_list, LVM_GETITEMCOUNT, 0, 0)
    if count <= 0:
        return []

    proc = _open_listview_process(hwnd_list)
    try:
        remote_pt = kernel32.VirtualAllocEx(
            proc, None, sizeof(POINT), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        remote_item = kernel32.VirtualAllocEx(
            proc, None, sizeof(LVITEMW), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        text_buf_size = 520  # 最多 260 个 UTF-16 字符
        remote_text = kernel32.VirtualAllocEx(
            proc, None, text_buf_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not (remote_pt and remote_item and remote_text):
            raise OSError("远程内存分配失败")

        icons: List[DesktopIcon] = []
        read = ctypes.c_size_t()
        for i in range(count):
            # 坐标
            user32.SendMessageW(hwnd_list, LVM_GETITEMPOSITION, i, remote_pt)
            pt = POINT()
            kernel32.ReadProcessMemory(
                proc, remote_pt, byref(pt), sizeof(POINT), byref(read)
            )
            # 名称
            item = LVITEMW()
            item.mask = LVIF_TEXT
            item.iItem = i
            item.iSubItem = 0
            item.pszText = ctypes.cast(remote_text, wintypes.LPWSTR)
            item.cchTextMax = text_buf_size // 2
            kernel32.WriteProcessMemory(
                proc, remote_item, byref(item), sizeof(LVITEMW), byref(read)
            )
            user32.SendMessageW(hwnd_list, LVM_GETITEMTEXTW, i, remote_item)
            buf = create_unicode_buffer(260)
            kernel32.ReadProcessMemory(
                proc, remote_text, buf, text_buf_size, byref(read)
            )
            icons.append(DesktopIcon(i, buf.value, pt.x, pt.y))
        return icons
    finally:
        for addr in (locals().get("remote_pt"), locals().get("remote_item"), locals().get("remote_text")):
            if addr:
                kernel32.VirtualFreeEx(proc, addr, 0, MEM_RELEASE)
        kernel32.CloseHandle(proc)


def is_auto_arrange_on(icons: List[DesktopIcon]) -> bool:
    """启发式判断自动排列是否开启。

    自动排列开启 ⇔ 图标按"列优先"顺序从左上角连续填满槽位,没有任何空洞
    (包括:列中间的空洞、某列底部空着但后面列还有图标、整列空缺)。
    做法:把每个图标映射到 (列, 行) 槽位编号,槽位必须恰好是 0..n-1。
    """
    if len(icons) < 2:
        return True
    origin_x = min(ic.x for ic in icons)
    origin_y = min(ic.y for ic in icons)
    xs = sorted({ic.x for ic in icons})
    ys = sorted({ic.y for ic in icons})
    x_diffs = [b - a for a, b in zip(xs, xs[1:])]
    y_diffs = [b - a for a, b in zip(ys, ys[1:])]
    if not x_diffs or not y_diffs:
        return True
    col_pitch = min(x_diffs)
    row_pitch = min(y_diffs)

    rows = int((max(ys) - origin_y) / row_pitch) + 1  # 每列的槽位数(行数)
    slots = sorted(
        int((ic.x - origin_x) / col_pitch) * rows + int((ic.y - origin_y) / row_pitch)
        for ic in icons
    )
    # 槽位必须从 0 开始连续,没有任何空洞
    return slots == list(range(len(icons)))


def _grid_metrics(icons: List[DesktopIcon], screen_height: int) -> Tuple[int, int, int, int]:
    """从现有图标坐标推断列宽/行高,并计算每列行数。"""
    xs = sorted({ic.x for ic in icons})
    ys = sorted({ic.y for ic in icons})
    xs_diff = [b - a for a, b in zip(xs, xs[1:]) if b > a]
    ys_diff = [b - a for a, b in zip(ys, ys[1:]) if b > a]
    col_pitch = min(xs_diff) if xs_diff else 76
    row_pitch = min(ys_diff) if ys_diff else 98
    origin_x = min(xs) if xs else MARGIN_X
    origin_y = min(ys) if ys else MARGIN_Y
    rows = max(1, (screen_height - origin_y) // row_pitch)
    return origin_x, origin_y, col_pitch, row_pitch


def arrange(
    zone_of: Dict[str, int],
    hwnd_list: Optional[int] = None,
    screen_height: Optional[int] = None,
) -> int:
    """按分区摆放桌面图标,返回摆放数量。

    zone_of: 图标名 → 分区号(越小越靠左;同一分区内按名称排序)。
    仅当自动排列关闭时位置才能持久生效,调用方应先用 is_auto_arrange_on 判断。
    """
    if screen_height is None:
        rect = wintypes.RECT()
        if user32.SystemParametersInfoW(0x0030, 0, byref(rect), 0):  # SPI_GETWORKAREA
            screen_height = rect.bottom
        else:
            screen_height = user32.GetSystemMetrics(1)
    if hwnd_list is None:
        hwnd_list = find_desktop_listview()
    if not hwnd_list:
        raise OSError("未找到桌面图标窗口")

    icons = read_icons(hwnd_list)
    origin_x, origin_y, col_pitch, row_pitch = _grid_metrics(icons, screen_height)
    rows = max(1, (screen_height - origin_y) // row_pitch)

    # 排序:分区号 → 名称
    ordered = sorted(icons, key=lambda ic: (zone_of.get(ic.name, 0), ic.name.lower()))

    placed = 0
    for slot, ic in enumerate(ordered):
        col, row = divmod(slot, rows)
        x = origin_x + col * col_pitch
        y = origin_y + row * row_pitch
        # LVM_SETITEMPOSITION:x/y 打包进 lParam,无需远程内存
        lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
        user32.SendMessageW(hwnd_list, LVM_SETITEMPOSITION, ic.index, lparam)
        placed += 1
    return placed
