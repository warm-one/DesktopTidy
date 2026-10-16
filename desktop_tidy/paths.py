"""桌面路径解析模块。

安全铁律 11:桌面路径必须通过注册表 User Shell Folders 或 SHGetKnownFolderPath
获取,兼容 OneDrive 重定向,禁止硬编码 C:\\Users\\...\\Desktop。
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Windows 已知文件夹 FOLDERID_Desktop 的 GUID
FOLDERID_DESKTOP = UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")


def get_desktop_path() -> str:
    """获取当前用户桌面路径。

    按优先级依次尝试:注册表 → SHGetKnownFolderPath → 用户主目录兜底。
    全部失败时抛出 RuntimeError。
    """
    if sys.platform == "win32":
        path = _from_registry()
        if path:
            return os.path.abspath(path)
        path = _from_known_folder()
        if path:
            return os.path.abspath(path)

    # 兜底:用户主目录下的 Desktop(非 Windows 平台,或前两步均失败)
    fallback = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(fallback):
        return os.path.abspath(fallback)

    raise RuntimeError("无法定位当前用户的桌面路径,请检查系统设置。")


def _from_registry() -> Optional[str]:
    """从注册表 User Shell Folders 读取桌面路径(首选,兼容 OneDrive 重定向)。"""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        finally:
            winreg.CloseKey(key)
        # 注册表里是 REG_EXPAND_SZ,可能含 %USERPROFILE% 之类的变量,需要展开
        expanded = os.path.expandvars(value)
        if expanded and os.path.isdir(expanded):
            return expanded
        logger.warning("注册表中的桌面路径无效: %s", value)
        return None
    except OSError as e:
        logger.warning("读取注册表桌面路径失败: %s", e)
        return None


def _from_known_folder() -> Optional[str]:
    """通过 Windows API SHGetKnownFolderPath 获取桌面路径(备用方案)。"""
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        guid = _GUID()
        guid.Data1 = FOLDERID_DESKTOP.time_low
        guid.Data2 = FOLDERID_DESKTOP.time_mid
        guid.Data3 = FOLDERID_DESKTOP.time_hi_version
        for i, b in enumerate(FOLDERID_DESKTOP.bytes[8:]):
            guid.Data4[i] = b

        path_ptr = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
        )
        if result != 0:
            logger.warning("SHGetKnownFolderPath 调用失败,错误码: %s", result)
            return None
        try:
            return path_ptr.value
        finally:
            # 必须 CoTaskMemFree 释放 COM 内存,避免泄漏
            ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(path_ptr.value))
    except Exception as e:  # 非 Windows 平台会抛 AttributeError 等
        logger.warning("SHGetKnownFolderPath 方式失败: %s", e)
        return None
