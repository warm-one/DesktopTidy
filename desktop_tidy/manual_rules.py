"""自定义规则编辑模块(纯本地,不依赖 AI,离线可用)。

规则与 AI 生成的完全同构:{"keywords": [...], "folder": "..."}
手动编辑的规则与 AI 规则共用同一套校验/执行通道,
AI 只是"自动填表"的便利手段,不是必需品。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .ai_rules import sanitize_folder
from .config import load_config, save_config

logger = logging.getLogger(__name__)

MAX_KEYWORDS_PER_RULE = 20  # 与 AI 规则一致的上限


def normalize_rule(rule: Any) -> Optional[Dict[str, Any]]:
    """清洗一条规则,无效返回 None。

    keywords 支持:字符串(逗号/空格分隔)或列表;
    folder 经 sanitize_folder 校验(非法字符/超长/保留名拒绝)。
    """
    if not isinstance(rule, dict):
        return None

    raw = rule.get("keywords", [])
    if isinstance(raw, str):
        # 全角(U+FF0C)/半角逗号、空格都作为分隔符
        raw = [k.strip() for k in raw.replace(",", " ").replace("\uff0c", " ").split()]
    if not isinstance(raw, list):
        return None

    keywords: List[str] = []
    for k in raw:
        k = str(k).strip()
        if k and k.lower() not in [x.lower() for x in keywords]:
            keywords.append(k)
    keywords = keywords[:MAX_KEYWORDS_PER_RULE]

    folder = sanitize_folder(rule.get("folder", ""))
    if not keywords or not folder:
        return None
    return {"keywords": keywords, "folder": folder}


def load_rules() -> List[Dict[str, Any]]:
    """读取已保存的自定义规则(config.json 的 manual_rules 字段)。"""
    cfg = load_config()
    rules = cfg.get("manual_rules", [])
    if not isinstance(rules, list):
        return []
    return [normalized for normalized in (normalize_rule(r) for r in rules) if normalized]


def save_rules(rules: List[Dict[str, Any]]) -> None:
    """保存自定义规则(全部经过清洗校验,坏条目丢弃)。"""
    clean = [r for r in (normalize_rule(rule) for rule in rules) if r]
    cfg = load_config()
    cfg["manual_rules"] = clean
    save_config(cfg)


def add_rule(keywords: Any, folder: str) -> Optional[Dict[str, Any]]:
    """新增一条规则并保存,返回清洗后的规则(无效返回 None)。"""
    normalized = normalize_rule({"keywords": keywords, "folder": folder})
    if normalized is None:
        return None
    rules = load_rules()
    rules.append(normalized)
    save_rules(rules)
    return normalized


def remove_rule(index: int) -> bool:
    """按索引删除一条规则,越界返回 False。"""
    rules = load_rules()
    if 0 <= index < len(rules):
        del rules[index]
        save_rules(rules)
        return True
    return False
