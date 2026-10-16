"""用户配置模块。

配置放 %APPDATA%\\DesktopOrganizer\\config.json,与日志(%LOCALAPPDATA%)分开
(AGENT.md 第 6 节)。AI 设置也存放在此。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: Dict[str, Any] = {
    "first_run": True,  # 首次运行引导标记
    "ai": {
        "base_url": "https://api.deepseek.com",  # OpenAI 兼容接口
        "model": "deepseek-chat",
        "api_key": "",
    },
}


def config_dir() -> str:
    appdata = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming"
    )
    return os.path.join(appdata, "DesktopOrganizer")


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def load_config() -> Dict[str, Any]:
    """读取配置;文件不存在或损坏时返回默认值。"""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝默认值
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return cfg
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取配置失败,使用默认配置: %s", e)
        return cfg

    if not isinstance(data, dict):
        return cfg
    for key, value in data.items():
        if key == "ai" and isinstance(value, dict):
            cfg["ai"].update(value)  # 嵌套合并,保留未填写的默认项
        else:
            cfg[key] = value
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    """保存配置。失败只记录日志,不影响主流程。"""
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("保存配置失败: %s", e)
