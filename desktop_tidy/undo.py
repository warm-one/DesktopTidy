"""撤销模块:基于日志反向移动,默认针对最近一次整理。

规则(与执行同样安全):
- 原位置已存在同名文件 → 跳过并记录冲突,绝不覆盖
- 文件已不在整理后的位置 → 跳过并记录
- 文件被占用 → 记录失败,不中断
- 撤销完成后给批次打 batch_undone 标记,防止重复撤销同一批次
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from .executor import ExecuteResult, is_inside
from .logger import append_record, latest_organize_batch, read_batch

logger = logging.getLogger(__name__)


def undo_last(desktop_path: str, log_dir: Optional[str] = None) -> Optional[ExecuteResult]:
    """撤销最近一次整理,把成功移动的文件移回原位置。

    没有可撤销的批次时返回 None。
    撤销结果同样追加写入原批次日志(凭据完整)。
    """
    batch_path = latest_organize_batch(log_dir)
    if batch_path is None:
        return None

    # 只反向处理成功移动过的记录
    moves = [r for r in read_batch(batch_path) if r.get("action") == "move"]
    batch_id = os.path.splitext(os.path.basename(batch_path))[0]
    result = ExecuteResult()

    def record(status: str, src: str, dst: str, reason: str) -> None:
        append_record(
            batch_path,
            {
                "batch_id": batch_id,
                "action": status,
                "src": src,
                "dst": dst,
                "reason": reason,
                "size": 0,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        result.details.append((status, src, dst, reason))

    # 倒序还原:后移动的先放回去,尽量恢复移动前的状态
    for item in reversed(moves):
        src = item.get("src", "")   # 原位置(桌面顶层)
        dst = item.get("dst", "")   # 现位置(分类文件夹)

        # 撤销同样只允许桌面内部的移动(铁律 5)
        if not is_inside(src, desktop_path) or not is_inside(dst, desktop_path):
            result.skipped += 1
            record("skip", dst, src, "路径超出桌面范围,已拒绝撤销")
            continue

        if not os.path.isfile(dst):
            result.skipped += 1
            record("skip", dst, src, "文件已不在整理后的位置(可能被手动移动或删除)")
            continue

        if os.path.exists(src):
            result.skipped += 1
            record("skip", dst, src, "原位置已存在同名文件,为避免覆盖跳过")
            continue

        try:
            os.rename(dst, src)
        except PermissionError as e:
            result.failed += 1
            record("fail", dst, src, f"文件被占用或无权限: {e}")
            continue
        except OSError as e:
            result.failed += 1
            record("fail", dst, src, f"撤销失败: {e}")
            continue

        result.moved += 1
        record("undo", dst, src, "已还原到原位置")

    # 给批次打"已撤销"标记,之后的 undo 会跳过它
    append_record(
        batch_path,
        {
            "batch_id": batch_id,
            "action": "batch_undone",
            "src": "",
            "dst": "",
            "reason": "",
            "size": 0,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return result
