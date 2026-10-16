"""GUI 第一版(CustomTkinter)。

遵循 AGENT.md 第 8 节:
- 干净、现代、不吓人:浅色主题、主按钮蓝色、卡片式布局
- 首次运行四步引导:① 扫描桌面 → ② 选择方案 → ③ 预览 → ④ 确认执行
- 文件列表每个文件可勾选,文件夹显示为"保留(不处理)"
- 预览区两个页签:
  · 整理后概览:用卡片模拟整理后的桌面(分类文件夹 + 保留的文件)
  · 从 → 到 列表:逐条显示移动明细,可勾选排除
- B 方案入口预留:底部"排列图标"按钮置灰并标注"即将推出"
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk

from . import icons
from . import arranger
from . import manual_rules
from .actions import MoveFileAction
from .ai_rules import AIError, generate_rules
from .config import load_config, save_config
from .executor import execute
from .logger import BatchLogger, cleanup_old_batches
from .paths import get_desktop_path
from .rules import Plan, build_plan_from_rules, generate_plans, is_shortcut
from .scanner import ScanResult, scan_desktop
from .undo import undo_last

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

INTRO_TEXT = "把桌面上的零散文件安全地收进分类文件夹:可预览、可撤销、绝不删除。"
GUIDE_TEXT = "四步整理:① 扫描桌面 → ② 选择方案 → ③ 预览 → ④ 确认执行"
PLAN_NAMES = ("保守", "标准", "按时间", "自定义")

# 卡片配色:蓝色 = 将创建的分类文件夹;浅灰 = 保留在桌面
FOLDER_TILE_FG = "#dbeafe"
FOLDER_TILE_HOVER = "#bfdbfe"
FOLDER_TILE_TEXT = "#1e3a8a"
IDLE_TILE_FG = "#f4f4f5"
IDLE_TILE_TEXT_DIR = "gray45"
IDLE_TILE_TEXT_FILE = "gray25"
LEGEND_TEXT = "蓝色卡片 = 整理后新增的分类文件夹(点击可整体排除/恢复);灰色 = 保留在桌面不动"


def human_size(size: int) -> str:
    """字节数 → 人类可读大小。"""
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024 ** 3:.2f} GB"


def format_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def shorten(name: str, limit: int = 14) -> str:
    """卡片里过长的名字截断显示。"""
    return name if len(name) <= limit else name[: limit - 1] + "…"


class DesktopTidyApp(ctk.CTk):
    """主窗口:左栏桌面文件列表,右栏方案选择与预览,底部主操作。"""

    def __init__(self) -> None:
        super().__init__()
        self.title("桌面整理助手 v1.1(自动分区排列版)")
        self.geometry("940x680")
        self.minsize(800, 580)

        self.desktop = get_desktop_path()
        self.config = load_config()
        # 自定义规则池:手动编辑 + AI 生成,统一存在 config.json 的 manual_rules。
        # 兼容旧版本:若存在 ai_rules,一次性迁移进规则池。
        rules = manual_rules.load_rules()
        legacy = self.config.get("ai_rules")
        if isinstance(legacy, list) and legacy:
            merged = {r["folder"]: r for r in rules}
            for raw in legacy:
                normalized = manual_rules.normalize_rule(raw)
                if normalized and normalized["folder"] not in merged:
                    merged[normalized["folder"]] = normalized
            rules = list(merged.values())
            manual_rules.save_rules(rules)
        self.config.pop("ai_rules", None)
        self.custom_rules: Optional[List[dict]] = rules or None
        self.scan_result: Optional[ScanResult] = None
        self._file_vars: Dict[str, ctk.BooleanVar] = {}  # 文件名 → 勾选状态
        self._action_vars: List[Tuple[MoveFileAction, ctk.BooleanVar]] = []
        self._icon_refs: List[ctk.CTkImage] = []  # 持有图片引用,防止被 GC
        # 目标文件夹名 → 该文件夹对应的一组 (动作, 勾选状态)
        self._folder_actions: Dict[str, List[Tuple[MoveFileAction, ctk.BooleanVar]]] = {}

        self._build_ui()
        self.refresh_scan()
        self.after(400, self._maybe_show_guide)  # 首次运行四步引导

    # ---------- 界面搭建 ----------

    def _build_ui(self) -> None:
        # 顶部:标题 + 一句话说明 + 四步引导
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            header, text="桌面整理助手", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w")
        ctk.CTkLabel(header, text=INTRO_TEXT, text_color="gray30").pack(anchor="w")
        ctk.CTkLabel(header, text=GUIDE_TEXT, text_color="gray40").pack(anchor="w")

        # 主体:左右两栏卡片
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=6)
        body.grid_columnconfigure(0, weight=1, uniform="cols")
        body.grid_columnconfigure(1, weight=1, uniform="cols")
        body.grid_rowconfigure(0, weight=1)

        # 左栏:桌面文件(可勾选)
        left = ctk.CTkFrame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(
            top, text="桌面文件", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(side="left")
        self.count_label = ctk.CTkLabel(top, text="", text_color="gray40")
        self.count_label.pack(side="right", padx=8)
        ctk.CTkButton(
            top, text="重新扫描", width=90, command=self.refresh_scan
        ).pack(side="right")

        self.file_list = ctk.CTkScrollableFrame(left)
        self.file_list.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        # 右栏:整理方案 + 预览(概略图 / 明细列表)
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        plan_card = ctk.CTkFrame(right)
        plan_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(
            plan_card, text="整理方案", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 0))
        self.plan_desc = ctk.CTkLabel(
            plan_card, text="", text_color="gray40", wraplength=340, justify="left"
        )
        self.plan_desc.pack(anchor="w", padx=10)
        self.plan_var = ctk.StringVar(value=PLAN_NAMES[0])
        for name in PLAN_NAMES:
            ctk.CTkRadioButton(
                plan_card,
                text=name,
                variable=self.plan_var,
                value=name,
                command=self.refresh_preview,
            ).pack(anchor="w", padx=14, pady=2)

        # 自定义规则:本地手动编辑(免费离线)或 AI 生成(可选增强),两者同一个规则池
        ctk.CTkButton(
            plan_card,
            text="编辑自定义规则(无需 AI)",
            height=26,
            command=self.on_edit_custom_rules,
        ).pack(fill="x", padx=10, pady=(6, 2))

        # AI 自定义方案:一句话描述 → 关键词规则(只生成规则,不直接操作文件)
        ai_row = ctk.CTkFrame(plan_card, fg_color="transparent")
        ai_row.pack(fill="x", padx=10, pady=(2, 2))
        self.ai_entry = ctk.CTkEntry(
            ai_row,
            placeholder_text="AI(可选):一句话描述,例:把论文和报告放一起",
        )
        self.ai_entry.pack(side="left", fill="x", expand=True)
        self.ai_button = ctk.CTkButton(
            ai_row, text="生成", width=54, command=self.on_ai_generate
        )
        self.ai_button.pack(side="left", padx=(6, 0))
        ctk.CTkButton(
            plan_card,
            text="AI 设置",
            width=70,
            height=24,
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "gray90"),
            command=self.on_ai_settings,
        ).pack(anchor="e", padx=10, pady=(2, 8))

        preview_card = ctk.CTkFrame(right)
        preview_card.grid(row=1, column=0, sticky="nsew")
        preview_card.grid_rowconfigure(0, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)

        self.preview_tabs = ctk.CTkTabview(preview_card)
        self.preview_tabs.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.preview_tabs.add("整理后概览")
        self.preview_tabs.add("从 → 到 列表")

        # 页签 1:整理后桌面概略图
        tab_overview = self.preview_tabs.tab("整理后概览")
        tab_overview.grid_rowconfigure(1, weight=1)
        tab_overview.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab_overview, text=LEGEND_TEXT, text_color="gray40", wraplength=380, justify="left").grid(
            row=0, column=0, sticky="ew", padx=4, pady=(2, 4)
        )
        self.schematic_frame = ctk.CTkScrollableFrame(tab_overview, fg_color="transparent")
        self.schematic_frame.grid(row=1, column=0, sticky="nsew")

        # 页签 2:从 → 到 明细列表
        tab_list = self.preview_tabs.tab("从 → 到 列表")
        tab_list.grid_rowconfigure(0, weight=1)
        tab_list.grid_columnconfigure(0, weight=1)
        self.action_list = ctk.CTkScrollableFrame(tab_list, fg_color="transparent")
        self.action_list.grid(row=0, column=0, sticky="nsew")

        # 底部:主按钮 + 撤销 + B 方案预留入口(置灰)+ 状态
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(2, 12))
        self.run_button = ctk.CTkButton(
            bottom,
            text="开始整理",
            width=170,
            height=40,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.on_run,
            state="disabled",
        )
        self.run_button.pack(side="left")
        ctk.CTkButton(
            bottom, text="撤销", width=100, height=40, command=self.on_undo
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            bottom,
            text="分区排列图标",
            width=200,
            height=40,
            command=self.on_arrange_icons,  # B 方案第一版:文件夹→快捷方式→文件 分区紧凑排列
        ).pack(side="right")
        self.status_label = ctk.CTkLabel(bottom, text="", text_color="gray40")
        self.status_label.pack(side="right", padx=12)

    # ---------- 数据与刷新 ----------

    def refresh_scan(self) -> None:
        """① 扫描桌面:只读扫描,重建文件列表,再刷新方案与预览。"""
        try:
            self.scan_result = scan_desktop(self.desktop)
        except Exception as e:
            messagebox.showerror("扫描失败", str(e))
            return

        for widget in self.file_list.winfo_children():
            widget.destroy()
        self._file_vars.clear()

        items = sorted(
            self.scan_result.items, key=lambda i: (i.is_dir, i.name.lower())
        )
        for item in items:
            row = ctk.CTkFrame(self.file_list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            if item.is_dir:
                # 文件夹标记为"不处理"(铁律 4)
                ctk.CTkLabel(
                    row, text=f"{item.name}(文件夹,保留)", text_color="gray40"
                ).pack(side="left")
            else:
                var = ctk.BooleanVar(value=True)
                self._file_vars[item.name] = var
                ctk.CTkCheckBox(
                    row,
                    text=item.name,
                    variable=var,
                    command=self.refresh_preview,
                    checkbox_width=18,
                    checkbox_height=18,
                ).pack(side="left")
                ctk.CTkLabel(
                    row,
                    text=f"{human_size(item.size)} · {format_time(item.mtime)}",
                    text_color="gray40",
                ).pack(side="right")

        files = sum(1 for i in items if not i.is_dir)
        self.count_label.configure(
            text=f"{files} 个文件,{len(items) - files} 个文件夹"
        )
        self.status_label.configure(text=f"桌面:{self.desktop}")
        self.refresh_preview()

    def refresh_preview(self) -> None:
        """③ 预览:基于勾选文件与所选方案,重建概略图和明细列表。"""
        if self.scan_result is None:
            return
        selected_items = [
            item
            for item in self.scan_result.items
            if item.is_dir or self._file_vars[item.name].get()
        ]
        plans = generate_plans(selected_items, self.desktop)
        if self.custom_rules:
            plans.append(
                build_plan_from_rules(
                    selected_items,
                    self.desktop,
                    self.custom_rules,
                    description=f"自定义关键词规则 x {len(self.custom_rules)}(可手动编辑或 AI 生成)",
                )
            )
        plan = next(
            (p for p in plans if p.name == self.plan_var.get()), plans[0]
        )
        self.plan_desc.configure(text=plan.description)

        self._action_vars.clear()
        self._folder_actions.clear()
        for action in plan.actions:
            self._action_vars.append((action, ctk.BooleanVar(value=True)))

        self._refresh_schematic()
        self._refresh_action_list()
        self._update_run_state()

    # ---------- 预览:整理后概略图 ----------

    def _make_tile(
        self,
        text: str,
        icon_pil,
        fg: str,
        hover: str,
        color: str,
        command=None,
    ) -> ctk.CTkButton:
        """构建概略图卡片:真实图标在上、文字在下。"""
        image = None
        if icon_pil is not None:
            image = ctk.CTkImage(
                light_image=icon_pil, size=(icons.ICON_SIZE, icons.ICON_SIZE)
            )
            self._icon_refs.append(image)  # 持有引用,防止被 GC

        return ctk.CTkButton(
            self.schematic_frame,
            text=text,
            image=image,
            compound="top",
            width=124,
            height=104,
            fg_color=fg,
            hover_color=hover,
            text_color=color,
            corner_radius=10,
            state="disabled" if command is None else "normal",
            command=command,
        )

    def _refresh_schematic(self) -> None:
        """用卡片模拟整理后的桌面:分类文件夹 + 保留的文件/文件夹。"""
        for widget in self.schematic_frame.winfo_children():
            widget.destroy()
        self._icon_refs.clear()
        self._folder_actions.clear()

        # 目标文件夹 → 一组动作(含被排除的,排除后该文件会"留在桌面")
        folder_map: Dict[str, List[Tuple[MoveFileAction, ctk.BooleanVar]]] = {}
        for action, var in self._action_vars:
            folder = os.path.basename(os.path.dirname(action.dst))
            folder_map.setdefault(folder, []).append((action, var))

        columns = 3
        index = 0
        # 规划中的新文件夹尚不存在,用通用文件夹图标
        generic_folder_icon = icons.get_virtual_icon("folder")

        # 新建的分类文件夹卡片(蓝色,可点击整体排除/恢复)
        for folder, pairs in folder_map.items():
            self._folder_actions[folder] = pairs
            included = sum(1 for _, v in pairs if v.get())
            if included:
                text = f"{folder}\n{included} 个文件"
                fg, hover, color = FOLDER_TILE_FG, FOLDER_TILE_HOVER, FOLDER_TILE_TEXT
            else:
                text = f"{folder}\n(已全部排除)"
                fg, hover, color = IDLE_TILE_FG, IDLE_TILE_FG, "gray55"
            button = self._make_tile(
                text,
                icon_pil=generic_folder_icon,
                fg=fg,
                hover=hover,
                color=color,
                command=lambda f=folder: self._toggle_folder(f),
            )
            button.grid(
                row=index // columns,
                column=index % columns,
                padx=5,
                pady=5,
                sticky="n",
            )
            index += 1

        # 保留在桌面的文件(未匹配类型、或被用户排除的),按名称排序展示
        included_names = {
            os.path.basename(a.src) for a, v in self._action_vars if v.get()
        }
        staying_files = sorted(
            (
                i
                for i in self.scan_result.items
                if not i.is_dir and i.name not in included_names
            ),
            key=lambda i: i.name.lower(),
        )
        # 已有文件夹(保留,不处理)
        existing_dirs = sorted(
            (i for i in self.scan_result.items if i.is_dir),
            key=lambda i: i.name.lower(),
        )

        for item in staying_files + existing_dirs:
            if item.is_dir:
                text = f"{shorten(item.name)}\n(文件夹,保留)"
                color = IDLE_TILE_TEXT_DIR
            else:
                text = f"{shorten(item.name)}\n(文件,保留)"
                color = IDLE_TILE_TEXT_FILE
            button = self._make_tile(
                text,
                icon_pil=icons.get_file_icon(item.path),
                fg=IDLE_TILE_FG,
                hover=IDLE_TILE_FG,
                color=color,
            )
            button.grid(
                row=index // columns,
                column=index % columns,
                padx=5,
                pady=5,
                sticky="n",
            )
            index += 1

        if index == 0:
            ctk.CTkLabel(
                self.schematic_frame, text="没有需要整理的文件,桌面将保持不变",
                text_color="gray40",
            ).grid(row=0, column=0, padx=8, pady=8)

    def _toggle_folder(self, folder: str) -> None:
        """点击概略图中的分类文件夹卡片:整体排除/恢复该文件夹的移动。"""
        pairs = self._folder_actions.get(folder, [])
        if not pairs:
            return
        # 只要有任何一个被勾选就整体排除,否则整体恢复
        target = not any(v.get() for _, v in pairs)
        for _, var in pairs:
            var.set(target)
        self._refresh_schematic()
        self._refresh_action_list()
        self._update_run_state()

    # ---------- 预览:从 → 到 明细列表 ----------

    def _refresh_action_list(self) -> None:
        """逐条显示移动明细,勾选框与概略图联动。"""
        for widget in self.action_list.winfo_children():
            widget.destroy()

        if not self._action_vars:
            ctk.CTkLabel(
                self.action_list, text="没有需要整理的文件", text_color="gray40"
            ).pack(anchor="w", padx=4, pady=6)
            return

        for action, var in self._action_vars:
            row = ctk.CTkFrame(self.action_list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkCheckBox(
                row,
                text=(
                    f"{os.path.basename(action.src)}  →  "
                    f"{os.path.relpath(os.path.dirname(action.dst), self.desktop)}"
                ),
                variable=var,
                command=self._on_action_toggled,
                checkbox_width=18,
                checkbox_height=18,
            ).pack(side="left")
            ctk.CTkLabel(row, text=action.reason, text_color="gray40").pack(side="right")

    def _on_action_toggled(self) -> None:
        """明细列表里勾选/取消一条,概略图同步刷新。"""
        self._refresh_schematic()
        self._update_run_state()

    def _update_run_state(self) -> None:
        any_included = any(var.get() for _, var in self._action_vars)
        self.run_button.configure(state="normal" if any_included else "disabled")

    # ---------- AI 转规则与设置 ----------

    def on_ai_generate(self) -> None:
        """AI 转规则:自然语言 → 关键词规则(只生成规则,不执行任何移动)。"""
        if self.scan_result is None:
            return
        desc = self.ai_entry.get().strip()
        if not desc:
            messagebox.showinfo(
                "AI 生成", "请先输入一句话描述,例如:把论文和报告放一起"
            )
            return

        file_names = [i.name for i in self.scan_result.items if not i.is_dir]
        self.ai_button.configure(state="disabled", text="生成中…")
        try:
            rules = generate_rules(desc, file_names, self.config.get("ai", {}))
        except AIError as e:
            messagebox.showerror("AI 生成失败", str(e))
            return
        finally:
            self.ai_button.configure(state="normal", text="生成")

        # 并入同一个自定义规则池(同文件夹的规则以 AI 新生成的为准)
        merged = {r["folder"]: r for r in manual_rules.load_rules()}
        for rule in rules:
            normalized = manual_rules.normalize_rule(rule)
            if normalized:
                merged[normalized["folder"]] = normalized
        final = list(merged.values())
        self.custom_rules = final
        manual_rules.save_rules(final)
        self.plan_var.set("自定义")
        self.refresh_preview()
        messagebox.showinfo(
            "AI 生成完成",
            f"已生成 {len(rules)} 条关键词规则并并入自定义规则池"
            f"(共 {len(final)} 条),可在预览中查看效果。",
        )

    def on_edit_custom_rules(self) -> None:
        """本地规则编辑器:手动添加/删除「关键词 → 文件夹」规则,完全离线可用。"""
        dlg = ctk.CTkToplevel(self)
        dlg.title("编辑自定义规则(本地,无需 AI)")
        dlg.geometry("560x460")
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(
            dlg,
            text="规则 = 文件名包含任一关键词 → 移动到指定文件夹",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            dlg,
            text="例:关键词「论文, 报告」→ 文件夹「学术资料」;快捷键(.lnk)永不被移动。",
            text_color="gray40",
            wraplength=520,
            justify="left",
        ).pack(anchor="w", padx=16)

        list_frame = ctk.CTkScrollableFrame(dlg, height=200)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(10, 6))

        def render() -> None:
            for child in list_frame.winfo_children():
                child.destroy()
            current = manual_rules.load_rules()
            if not current:
                ctk.CTkLabel(
                    list_frame,
                    text="暂无规则,请在下方添加。",
                    text_color="gray40",
                ).pack(anchor="w", pady=4)
                return
            for i, rule in enumerate(current):
                row = ctk.CTkFrame(list_frame, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(
                    row,
                    text=f"{' / '.join(rule['keywords'])}  →  {rule['folder']}",
                    anchor="w",
                ).pack(side="left", fill="x", expand=True)
                ctk.CTkButton(
                    row,
                    text="删除",
                    width=52,
                    height=24,
                    fg_color="transparent",
                    border_width=1,
                    text_color=("gray10", "gray90"),
                    command=lambda idx=i: (manual_rules.remove_rule(idx), render()),
                ).pack(side="right")

        render()

        add_frame = ctk.CTkFrame(dlg)
        add_frame.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(add_frame, text="关键词(逗号分隔)").pack(anchor="w", padx=10, pady=(8, 0))
        kw_entry = ctk.CTkEntry(add_frame, placeholder_text="论文, 报告, 文献")
        kw_entry.pack(fill="x", padx=10, pady=(2, 6))
        ctk.CTkLabel(add_frame, text="目标文件夹名").pack(anchor="w", padx=10)
        folder_entry = ctk.CTkEntry(add_frame, placeholder_text="学术资料")
        folder_entry.pack(fill="x", padx=10, pady=(2, 6))

        def do_add() -> None:
            folder = folder_entry.get().strip()
            added = manual_rules.add_rule(kw_entry.get(), folder)
            if added is None:
                messagebox.showwarning(
                    "规则不合格",
                    "请填写至少一个关键词和合法的文件夹名(不能含 \\ / : * ? \" < > | 等字符)。",
                    parent=dlg,
                )
                return
            kw_entry.delete(0, "end")
            folder_entry.delete(0, "end")
            render()
            self._reload_custom_rules()

        ctk.CTkButton(add_frame, text="添加规则", command=do_add).pack(
            anchor="e", padx=10, pady=(0, 10)
        )

        def on_close() -> None:
            self._reload_custom_rules()
            dlg.destroy()

        ctk.CTkButton(dlg, text="完成", command=on_close).pack(anchor="e", padx=16, pady=(0, 14))
        dlg.protocol("WM_DELETE_WINDOW", on_close)

    def _reload_custom_rules(self) -> None:
        """从磁盘重载规则池,若已有规则则切到「自定义」方案并刷新预览。"""
        rules = manual_rules.load_rules()
        self.custom_rules = rules or None
        if rules:
            self.plan_var.set("自定义")
        self.refresh_preview()

    def on_ai_settings(self) -> None:
        """AI 设置对话框:接口地址 / 模型 / API Key。"""
        dlg = ctk.CTkToplevel(self)
        dlg.title("AI 设置")
        dlg.geometry("460x260")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        ai = self.config.get("ai", {})

        def field(label, key, show=None):
            ctk.CTkLabel(dlg, text=label, anchor="w").pack(fill="x", padx=16, pady=(10, 0))
            entry = ctk.CTkEntry(dlg, show=show)
            entry.pack(fill="x", padx=16)
            entry.insert(0, str(ai.get(key, "")))
            return entry

        entry_url = field("接口地址(OpenAI 兼容)", "base_url")
        entry_model = field("模型", "model")
        entry_key = field("API Key", "api_key", show="*")

        def save() -> None:
            self.config["ai"] = {
                "base_url": entry_url.get().strip(),
                "model": entry_model.get().strip(),
                "api_key": entry_key.get().strip(),
            }
            save_config(self.config)
            messagebox.showinfo("AI 设置", "已保存。", parent=dlg)
            dlg.destroy()

        ctk.CTkButton(dlg, text="保存", width=120, command=save).pack(pady=16)

    # ---------- 首次运行引导 ----------

    def _maybe_show_guide(self) -> None:
        if self.config.get("first_run", True):
            self._show_guide()
            self.config["first_run"] = False
            save_config(self.config)

    def _show_guide(self) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title("欢迎使用桌面整理助手")
        dlg.geometry("430x310")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        ctk.CTkLabel(
            dlg, text="四步整理你的桌面", font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(22, 10))
        steps = (
            "① 扫描桌面:自动列出桌面上的文件(只读)",
            "② 选择方案:保守 / 标准 / 按时间 / 自定义",
            "③ 预览:看到整理后桌面的概略图,可逐项排除",
            "④ 确认执行:随时可以一键撤销",
        )
        for step in steps:
            ctk.CTkLabel(dlg, text=step, anchor="w").pack(fill="x", padx=40, pady=3)
        ctk.CTkButton(dlg, text="开始使用", width=140, command=dlg.destroy).pack(pady=20)

    # ---------- 操作 ----------

    def _auto_arrange_after_change(self) -> str:
        """整理/撤销后自动分区排列(零手动步骤)。

        整理/撤销刚刚改变了桌面,此时无条件排列(不再依赖"是否已整齐"检测:
        Explorer 同步图标有延迟,刚整理完读到的可能是旧布局,会误判跳过)。
        若用户开着系统"自动排列图标",自定义坐标会被系统接管,同样无害。
        返回附加到结果提示的说明文字。
        """
        try:
            time.sleep(0.8)  # 等 Explorer 同步整理后的图标状态
            zone_of: Dict[str, int] = {}
            for item in self.scan_result.items:
                if item.is_dir:
                    zone_of[item.name] = 1
                elif is_shortcut(item):
                    zone_of[item.name] = 2
                else:
                    zone_of[item.name] = 3
            placed = arranger.arrange(zone_of)
            if placed:
                return f"\n已自动按分区排列 {placed} 个图标(文件夹 → 快捷方式 → 文件)。"
        except OSError as e:
            logger.warning("自动分区排列失败: %s", e)
        return ""

    def on_run(self) -> None:
        """④ 确认执行:只移动勾选的文件,逐个写日志,可撤销。"""
        selected = [action for action, var in self._action_vars if var.get()]
        if not selected:
            return
        if not messagebox.askyesno(
            "确认整理",
            f"将移动 {len(selected)} 个文件到桌面的分类文件夹。\n"
            "目标同名自动加编号,绝不覆盖;被占用文件自动跳过。\n"
            "执行后可用「撤销」还原。\n\n确定开始吗?",
        ):
            return

        cleanup_old_batches()
        batch = BatchLogger()
        try:
            summary = execute(selected, self.desktop, batch)
        except Exception as e:
            messagebox.showerror(
                "整理失败", f"执行出错(已完成的移动不受影响):\n{e}"
            )
            self.refresh_scan()
            return

        self.refresh_scan()
        arrange_note = self._auto_arrange_after_change()  # 整理后自动分区排列

        text = f"整理完成:成功 {summary.moved}、跳过 {summary.skipped}、失败 {summary.failed}" + arrange_note
        problems = [d for d in summary.details if d[0] in ("skip", "fail")]
        if problems:
            detail = "\n".join(
                f"[{'跳过' if d[0] == 'skip' else '失败'}] "
                f"{os.path.basename(d[1])} —— {d[3]}"
                for d in problems
            )
            messagebox.showinfo("整理完成", text + "\n\n明细:\n" + detail)
        else:
            messagebox.showinfo("整理完成", text)

    def on_arrange_icons(self) -> None:
        """B 方案第一版:把桌面图标按「文件夹 → 快捷方式 → 文件」分区紧凑排列。

        只调整图标显示位置,不移动任何文件;若用户开着系统"自动排列图标",
        自定义坐标会被系统接管(等同无效),提示用户即可。
        """
        if self.scan_result is None:
            return
        if not messagebox.askyesno(
            "分区排列图标",
            "将把桌面图标按「文件夹 → 快捷方式 → 文件」分区紧凑排列。\n"
            "只调整图标显示位置,不移动任何文件。\n\n确定执行吗?",
        ):
            return

        # 分区号:0 = 系统/未知图标(最左),1 = 文件夹,2 = 快捷方式,3 = 文件
        zone_of: Dict[str, int] = {}
        for item in self.scan_result.items:
            if item.is_dir:
                zone_of[item.name] = 1
            elif is_shortcut(item):
                zone_of[item.name] = 2
            else:
                zone_of[item.name] = 3

        try:
            placed = arranger.arrange(zone_of)
        except OSError as e:
            messagebox.showerror("分区排列图标", f"排列失败:{e}")
            return
        messagebox.showinfo("分区排列图标", f"已按分区摆放 {placed} 个图标。\n如不满意可再次拖动调整。")

    def on_undo(self) -> None:
        """撤销最近一次整理(基于日志反向移动)。"""
        if not messagebox.askyesno(
            "确认撤销", "将把最近一次整理移动的文件放回原位置。\n确定吗?"
        ):
            return
        try:
            summary = undo_last(self.desktop)
        except Exception as e:
            messagebox.showerror("撤销失败", str(e))
            return
        if summary is None:
            messagebox.showinfo("撤销", "没有可撤销的整理记录。")
            return

        text = f"撤销完成:还原 {summary.moved}、跳过 {summary.skipped}、失败 {summary.failed}"
        problems = [d for d in summary.details if d[0] in ("skip", "fail")]
        if problems:
            detail = "\n".join(
                f"[{'跳过' if d[0] == 'skip' else '失败'}] "
                f"{os.path.basename(d[1])} —— {d[3]}"
                for d in problems
            )
            messagebox.showinfo("撤销完成", text + "\n\n明细:\n" + detail)
        else:
            self.refresh_scan()
            arrange_note = self._auto_arrange_after_change()  # 撤销后自动分区排列
            messagebox.showinfo("撤销完成", text + arrange_note)
