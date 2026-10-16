"""整理日志模块:JSONL 追加写入,是撤销的凭据。

- 日志放 %LOCALAPPDATA%\\DesktopOrganizer\\logs\\(本机 Local 目录,不放 Roaming,
  避免域环境漫游、多机日志错乱)
- 每次整理一个 batch_id,一个批次一个 .jsonl 文件
- 追加模式写入,程序崩溃不丢已写记录
- 保留最近 30 次,更早的由调用方触发清理(必须提示用户,不静默删除)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_KEEP_BATCHES = 30  # 日志保留最近 30 次


def default_log_dir() -> str:
    """日志目录:%LOCALAPPDATA%\\DesktopOrganizer\\logs。"""
    local = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local"
    )
    return os.path.join(local, "DesktopOrganizer", "logs")


def new_batch_id() -> str:
    # 微秒级时间戳:保证同一秒内的多个批次也能按文件名正确排序
    return f"batch-{datetime.now().strftime('%Y%m%d-%H%M%S%f')}-{uuid.uuid4().hex[:8]}"


def append_record(batch_path: str, record: dict) -> None:
    """以追加模式写入一行 JSON,程序崩溃也不丢已写记录。"""
    with open(batch_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_batch(batch_path: str) -> List[dict]:
    """读取一个批次文件的全部记录,坏行跳过不中断。"""
    records: List[dict] = []
    try:
        with open(batch_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("跳过无法解析的日志行: %s", line[:100])
    except OSError as e:
        logger.warning("读取日志失败 %s: %s", batch_path, e)
    return records


def list_batches(log_dir: Optional[str] = None) -> List[str]:
    """按文件名(含时间戳)顺序列出全部批次文件,旧 → 新。"""
    log_dir = log_dir or default_log_dir()
    if not os.path.isdir(log_dir):
        return []
    return sorted(
        os.path.join(log_dir, name)
        for name in os.listdir(log_dir)
        if name.endswith(".jsonl")
    )


def latest_organize_batch(log_dir: Optional[str] = None) -> Optional[str]:
    """最近一次可撤销的整理批次:含 move 记录且没有被撤销过。"""
    for batch_path in reversed(list_batches(log_dir)):
        records = read_batch(batch_path)
        # 已撤销的批次(batch_undone 标记)不能再作为撤销目标
        if any(r.get("action") == "batch_undone" for r in records):
            continue
        if any(r.get("action") == "move" for r in records):
            return batch_path
    return None


def cleanup_old_batches(
    log_dir: Optional[str] = None, keep: int = DEFAULT_KEEP_BATCHES
) -> List[str]:
    """删除超出保留数量的旧日志文件,返回被删除的路径(调用方负责提示用户)。"""
    log_dir = log_dir or default_log_dir()
    batches = list_batches(log_dir)
    removed = batches[: max(0, len(batches) - keep)]
    for path in removed:
        try:
            os.remove(path)
        except OSError as e:
            logger.warning("删除旧日志失败 %s: %s", path, e)
    return removed


class BatchLogger:
    """一次整理(或撤销)的日志记录器。"""

    def __init__(self, log_dir: Optional[str] = None, batch_id: Optional[str] = None):
        self.log_dir = log_dir or default_log_dir()
        os.makedirs(self.log_dir, exist_ok=True)
        self.batch_id = batch_id or new_batch_id()
        self.batch_path = os.path.join(self.log_dir, self.batch_id + ".jsonl")

    def log(
        self, action: str, src: str, dst: str, reason: str = "", size: int = 0
    ) -> None:
        """写入一条记录。action 取值:move / skip / fail / undo / batch_undone。

        日志的 action 字段为 B 方案预留新类型(如 arrange_icon)。
        """
        append_record(
            self.batch_path,
            {
                "batch_id": self.batch_id,
                "action": action,
                "src": src,
                "dst": dst,
                "reason": reason,
                "size": size,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
