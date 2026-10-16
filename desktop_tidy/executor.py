"""执行模块:确定性代码,逐个移动文件,安全第一。

- 目标同名自动加 (1),绝不覆盖(铁律 2)
- 文件被占用 / 无权限(PermissionError)→ 记录失败,不中断(铁律 9)
- 每移动一个文件立即写日志(铁律 8)
- 只执行桌面内部的移动,越界路径一律拒绝(铁律 5)
- 只移动文件,绝不移动文件夹(铁律 4)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from .actions import MoveFileAction
from .logger import BatchLogger

logger = logging.getLogger(__name__)

# 同名避让的最大尝试次数,防止极端情况下死循环
MAX_RENAME_ATTEMPTS = 100


@dataclass
class ExecuteResult:
    """一次整理(或撤销)的执行结果统计。"""

    moved: int = 0
    skipped: int = 0
    failed: int = 0
    details: List[Tuple[str, str, str, str]] = field(default_factory=list)  # (状态, src, dst, 原因)


def is_inside(path: str, root: str) -> bool:
    """判断 path 是否位于 root 目录内(防越界校验)。"""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def unique_dst(dst: str) -> str:
    """目标已存在时自动追加 (1)、(2)…,绝不覆盖(铁律 2)。"""
    if not os.path.exists(dst):
        return dst
    base, ext = os.path.splitext(dst)
    for i in range(1, MAX_RENAME_ATTEMPTS + 1):
        candidate = f"{base} ({i}){ext}"
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError(f"无法为目标生成唯一文件名: {dst}")


def execute(
    actions: List[MoveFileAction], desktop_path: str, batch: BatchLogger
) -> ExecuteResult:
    """逐个执行移动动作。宁可跳过,不可覆盖;单条失败不中断。"""
    result = ExecuteResult()

    def record(status: str, src: str, dst: str, reason: str, size: int = 0) -> None:
        batch.log(status, src, dst, reason, size=size)
        result.details.append((status, src, dst, reason))

    for action in actions:
        # 安全校验:源和目标都必须在桌面内部(铁律 5)
        if not is_inside(action.src, desktop_path) or not is_inside(
            action.dst, desktop_path
        ):
            result.skipped += 1
            record("skip", action.src, action.dst, "路径超出桌面范围,已拒绝执行")
            continue

        # 源必须是存在的文件:绝不移动文件夹(铁律 4)
        if not os.path.isfile(action.src):
            result.skipped += 1
            record("skip", action.src, action.dst, "源文件不存在或不是文件(文件夹不处理)")
            continue

        size = 0
        try:
            size = os.path.getsize(action.src)
        except OSError:
            pass  # 取不到大小不影响移动,日志里记 0

        try:
            os.makedirs(os.path.dirname(action.dst), exist_ok=True)
            moved_dst = _rename_with_avoid(action.src, action.dst)
        except PermissionError as e:
            # 文件被占用或无权限 → 记录失败,继续处理下一个(铁律 9)
            result.failed += 1
            record("fail", action.src, action.dst, f"文件被占用或无权限: {e}")
            continue
        except OSError as e:
            result.failed += 1
            record("fail", action.src, action.dst, f"移动失败: {e}")
            continue

        result.moved += 1
        record("move", action.src, moved_dst, action.reason, size=size)

    return result


def _rename_with_avoid(src: str, dst: str) -> str:
    """带同名避让的移动,返回实际落入的目标路径。

    os.rename 在 Windows 上目标已存在会抛 FileExistsError(不会覆盖),
    正好满足"绝不覆盖";捕获后换下一个编号重试即可。
    """
    last_error: OSError = OSError("未执行任何移动尝试")
    for _ in range(MAX_RENAME_ATTEMPTS):
        candidate = unique_dst(dst)
        try:
            os.rename(src, candidate)
            return candidate
        except FileExistsError as e:
            # 极小概率竞态:检查完到移动前有别的程序创建了同名文件,换编号重试
            last_error = e
    raise last_error
