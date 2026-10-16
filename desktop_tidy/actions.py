"""动作抽象层(为 B 方案预留)。

本期只有 MoveFileAction(移动文件);后续 B 方案可新增 ArrangeIconAction
(排列图标),预览 / 日志 / 撤销都基于统一的动作模型,不需要改动其他层。
"""
from __future__ import annotations

from dataclasses import dataclass


class Action:
    """所有可执行动作的统一接口(标记基类)。

    约定:每个动作必须携带 reason(解释动作为什么产生,预览时展示给用户)。
    日志的 action 类型字段同样为 B 方案预留(如 arrange_icon)。
    """

    reason: str


@dataclass
class MoveFileAction(Action):
    """把一个文件从 src 移动到 dst(桌面内同盘移动)。"""

    src: str
    dst: str
    reason: str = ""
