"""规则引擎:基于扫描结果生成整理方案(保守 / 标准)。

规则优先级:时间 > 类型 > 关键词。本期内置模板只用到时间与类型,
关键词规则为后续 AI 转规则(第 7 步)预留。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .actions import MoveFileAction
from .scanner import DesktopItem

# 分类文件夹名 → 扩展名集合
CATEGORY_FOLDERS = {
    "图片": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
    "文档": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".txt", ".md", ".csv", ".rtf"},
    "视频": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"},
    "安装包": {".exe", ".msi"},
    "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
}

# 保守方案的适用类型:安装包 + 压缩包
CONSERVATIVE_EXTS = CATEGORY_FOLDERS["安装包"] | CATEGORY_FOLDERS["压缩包"]

# 保守方案的时间阈值:30 天未动
STALE_DAYS = 30

# 快捷方式硬约束:一律保留在桌面,任何方案都不得移动
# (快捷方式是用户直达应用的入口,移动会打乱使用习惯;AI 规则也越不过这道闸)
SHORTCUT_EXTS = {".lnk", ".url", ".desklink", ".appref-ms"}


def is_shortcut(item: DesktopItem) -> bool:
    """判断条目是否为快捷方式。"""
    return bool(item.ext) and ("." + item.ext) in SHORTCUT_EXTS


@dataclass
class Plan:
    """一个整理方案 = 名称 + 说明 + 一组待执行的移动动作。"""

    name: str
    description: str
    actions: List[MoveFileAction] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.actions)


def category_of(ext: str) -> Optional[str]:
    """按扩展名返回分类文件夹名,未匹配返回 None。"""
    dotted = "." + ext.lower().lstrip(".")
    for folder, exts in CATEGORY_FOLDERS.items():
        if dotted in exts:
            return folder
    return None


def generate_plans(items: List[DesktopItem], desktop_path: str) -> List[Plan]:
    """生成内置整理方案列表:[保守, 标准, 按时间]。文件夹一律不处理(铁律 4)。"""
    files = [i for i in items if not i.is_dir]
    return [
        _build_conservative(files, desktop_path),
        _build_standard(files, desktop_path),
        _build_by_time(files, desktop_path),
    ]


def _build_conservative(files: List[DesktopItem], desktop_path: str) -> Plan:
    """保守方案:只移动 30 天未动的安装包/压缩包(时间规则优先于类型规则)。"""
    threshold = time.time() - STALE_DAYS * 86400
    actions: List[MoveFileAction] = []
    for item in files:
        folder = category_of(item.ext)
        # 类型必须是安装包/压缩包,且超过阈值天数未修改;快捷方式一律不动
        if (
            folder in ("安装包", "压缩包")
            and item.mtime < threshold
            and not is_shortcut(item)
        ):
            actions.append(
                MoveFileAction(
                    src=item.path,
                    dst=os.path.join(desktop_path, folder, item.name),
                    reason=f"超过 {STALE_DAYS} 天未动的{folder}",
                )
            )
    return Plan("保守", f"只移动 {STALE_DAYS} 天未动的安装包/压缩包", actions)


def _build_standard(files: List[DesktopItem], desktop_path: str) -> Plan:
    """标准方案:按类型把文件分进对应文件夹,未识别类型的文件保持不动。"""
    actions: List[MoveFileAction] = []
    for item in files:
        folder = category_of(item.ext)
        # 快捷方式不在任何分类里,天然不会被选中;显式判断以防未来新增分类
        if folder and not is_shortcut(item):
            actions.append(
                MoveFileAction(
                    src=item.path,
                    dst=os.path.join(desktop_path, folder, item.name),
                    reason=f"按类型整理:{folder}",
                )
            )
    return Plan("标准", "按类型分类:图片、文档、视频、安装包、压缩包", actions)


def _build_by_time(files: List[DesktopItem], desktop_path: str) -> Plan:
    """按时间方案:按最后修改月份归档到「2026-09」样式文件夹,快捷方式保留。"""
    actions: List[MoveFileAction] = []
    for item in files:
        if is_shortcut(item):
            continue
        month = time.strftime("%Y-%m", time.localtime(item.mtime))
        actions.append(
            MoveFileAction(
                src=item.path,
                dst=os.path.join(desktop_path, month, item.name),
                reason=f"按修改时间归档:{month}",
            )
        )
    return Plan("按时间", "按最后修改月份归档到 2026-09 样式的文件夹", actions)


def build_plan_from_rules(
    items: List[DesktopItem],
    desktop_path: str,
    rules: List[dict],
    name: str = "自定义",
    description: str = "AI 根据你的描述生成的关键词规则",
) -> Plan:
    """自定义方案:按文件名关键词把文件分组(只作用于普通文件,文件夹永不处理)。

    rules 来自 AI 转规则(ai_rules.parse_rules),已通过校验:
    [{"keywords": [...], "folder": "..."}]
    关键词按文件名包含匹配(不区分大小写),命中第一条规则即分组。
    """
    actions: List[MoveFileAction] = []
    for item in items:
        if item.is_dir or is_shortcut(item):
            continue  # 铁律 4:文件夹一律不处理;快捷方式硬约束保留在桌面
        folder = _match_keywords(item.name, rules)
        if folder:
            actions.append(
                MoveFileAction(
                    src=item.path,
                    dst=os.path.join(desktop_path, folder, item.name),
                    reason=f"关键词规则:{folder}",
                )
            )
    return Plan(name, description, actions)


def _match_keywords(filename: str, rules: List[dict]) -> Optional[str]:
    """按文件名包含匹配关键词,返回分类文件夹名,未命中返回 None。"""
    lower = filename.lower()
    for rule in rules:
        keywords = rule.get("keywords", [])
        if any(str(k).lower() in lower for k in keywords):
            folder = rule.get("folder", "")
            return folder or None
    return None
