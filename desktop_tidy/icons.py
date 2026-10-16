"""图标提取模块:获取文件/文件夹的真实系统图标,供概略图显示。

通过 Windows Shell API SHGetFileInfoW 拿到图标句柄,
再用 GetIconInfo + GetDIBits 转成 PIL 图像。结果按路径缓存。
Pillow 是 CustomTkinter 自带依赖,不额外引入第三方库。
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Dict, Optional

from PIL import Image

logger = logging.getLogger(__name__)

if ctypes.windll:  # 仅 Windows 有效;非 Windows 平台所有函数返回 None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32

# SHGetFileInfoW 标志
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000  # 32x32
SHGFI_USEFILEATTRIBUTES = 0x000000010  # 按扩展名取图标,文件可以不存在
FILE_ATTRIBUTE_DIRECTORY = 0x10

ICON_SIZE = 32  # 与 SHGFI_LARGEICON 一致


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", wintypes.LPVOID),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]


# 显式声明参数类型:64 位句柄若按默认 c_int 传参会在数值超过 32 位时溢出
shell32.SHGetFileInfoW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(SHFILEINFOW),
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.GetObjectW.argtypes = [wintypes.HBITMAP, wintypes.INT, wintypes.LPVOID]
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
]
gdi32.DeleteObject.argtypes = [wintypes.HBITMAP]


_cache: Dict[str, Optional[Image.Image]] = {}


def get_file_icon(path: str) -> Optional[Image.Image]:
    """获取文件/文件夹的真实系统图标(按完整路径缓存)。"""
    if path in _cache:
        return _cache[path]
    icon = _extract_icon(path, use_file_attributes=False)
    _cache[path] = icon
    return icon


def get_virtual_icon(path: str, is_dir: bool = True) -> Optional[Image.Image]:
    """获取尚不存在的路径的图标(按扩展名/目录属性,用于规划中的新文件夹)。"""
    key = f"virtual:{path}:{is_dir}"
    if key in _cache:
        return _cache[key]
    icon = _extract_icon(path, use_file_attributes=True, is_dir=is_dir)
    _cache[key] = icon
    return icon


def _extract_icon(
    path: str, use_file_attributes: bool = False, is_dir: bool = False
) -> Optional[Image.Image]:
    try:
        info = SHFILEINFOW()
        flags = SHGFI_ICON | SHGFI_LARGEICON
        file_attributes = 0
        if use_file_attributes:
            flags |= SHGFI_USEFILEATTRIBUTES
            file_attributes = FILE_ATTRIBUTE_DIRECTORY if is_dir else 0x80  # FILE_ATTRIBUTE_NORMAL
        result = shell32.SHGetFileInfoW(
            path,
            file_attributes,
            ctypes.byref(info),
            ctypes.sizeof(SHFILEINFOW),
            flags,
        )
        if not result or not info.hIcon:
            return None
        try:
            return _hicon_to_pil(info.hIcon)
        finally:
            user32.DestroyIcon(info.hIcon)
    except Exception as e:
        logger.warning("提取图标失败 %s: %s", path, e)
        return None


def _hicon_to_pil(hicon: int) -> Optional[Image.Image]:
    """把 HICON 转成 PIL RGBA 图像(GetIconInfo + GetDIBits)。"""
    info = ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(info)):
        return None
    try:
        bmp = BITMAP()
        if not gdi32.GetObjectW(
            info.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bmp)
        ):
            return None
        width, height = bmp.bmWidth, abs(bmp.bmHeight)
        if width <= 0 or height <= 0:
            return None

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # 负值 = 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(width * height * 4)
        hdc = user32.GetDC(None)
        try:
            gdi32.GetDIBits(
                hdc, info.hbmColor, 0, height, buf, ctypes.byref(bmi), 0
            )
        finally:
            user32.ReleaseDC(None, hdc)

        return Image.frombytes("RGBA", (width, height), buf.raw, "raw", "BGRA")
    finally:
        gdi32.DeleteObject(info.hbmColor)
        gdi32.DeleteObject(info.hbmMask)
