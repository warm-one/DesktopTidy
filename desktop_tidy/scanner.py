"""只读扫描模块:列出桌面顶层条目,绝不做任何写操作。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, NamedTuple, Optional

from .paths import get_desktop_path

logger = logging.getLogger(__name__)

# Windows 文件属性常量(仅 Windows 的 stat 结果带 st_file_attributes)
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4

# 永不处理的名字:desktop.ini 存放文件夹视图设置,移动会破坏自定义
EXCLUDED_NAMES = {"desktop.ini"}


@dataclass
class DesktopItem:
    """桌面上的一个条目(文件或文件夹)。"""

    name: str      # 文件名
    ext: str       # 小写扩展名,不含点;无扩展名为空字符串
    size: int      # 字节数,文件夹为 0
    mtime: float   # 最后修改时间戳
    path: str      # 完整路径
    is_dir: bool   # 文件夹标记为"不处理",预览中显示为"保留"


class ScanResult(NamedTuple):
    """扫描结果:条目列表 + 被排除(系统/隐藏/读取失败)的数量。"""

    items: List[DesktopItem]
    skipped: int


def scan_desktop(desktop_path: Optional[str] = None) -> ScanResult:
    """只读扫描桌面顶层(不递归子文件夹),返回文件与文件夹列表。"""
    if desktop_path is None:
        desktop_path = get_desktop_path()

    items: List[DesktopItem] = []
    skipped = 0

    try:
        entries = list(os.scandir(desktop_path))
    except OSError as e:
        raise RuntimeError(f"无法读取桌面目录 {desktop_path}: {e}") from e

    for entry in entries:
        try:
            if entry.name.lower() in EXCLUDED_NAMES:
                skipped += 1
                continue

            st = entry.stat(follow_symlinks=False)
            # 隐藏/系统文件一律排除(st_file_attributes 仅 Windows 存在,其他平台为 0)
            attrs = getattr(st, "st_file_attributes", 0)
            if attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                skipped += 1
                continue

            is_dir = entry.is_dir(follow_symlinks=False)
            items.append(
                DesktopItem(
                    name=entry.name,
                    ext=os.path.splitext(entry.name)[1].lower().lstrip("."),
                    size=0 if is_dir else st.st_size,
                    mtime=st.st_mtime,
                    path=os.path.join(desktop_path, entry.name),
                    is_dir=is_dir,
                )
            )
        except OSError as e:
            # 单个条目读取失败只跳过并记录,不中断整个扫描(铁律 9)
            logger.warning("跳过无法读取的条目 %s: %s", entry.name, e)
            skipped += 1

    return ScanResult(items, skipped)
