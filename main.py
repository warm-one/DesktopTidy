"""DesktopTidy 命令行入口(A 方案 MVP)。

用法:
  python main.py scan              只读扫描,列出桌面顶层文件
  python main.py plan              预览内置整理方案,不执行任何移动
  python main.py run [--plan X]    选方案 → 预览 → 确认 → 执行(--yes 跳过交互)
  python main.py undo [--yes]      撤销最近一次整理
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import List, Optional

from desktop_tidy import arranger
from desktop_tidy import manual_rules
from desktop_tidy.ai_rules import AIError, generate_rules
from desktop_tidy.actions import MoveFileAction
from desktop_tidy.config import load_config, save_config
from desktop_tidy.executor import ExecuteResult, execute
from desktop_tidy.logger import BatchLogger, cleanup_old_batches, latest_organize_batch
from desktop_tidy.paths import get_desktop_path
from desktop_tidy.rules import Plan, build_plan_from_rules, generate_plans, is_shortcut
from desktop_tidy.scanner import scan_desktop
from desktop_tidy.undo import undo_last

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

STATUS_LABELS = {"move": "成功", "skip": "跳过", "fail": "失败", "undo": "还原"}


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


def print_preview(actions: List[MoveFileAction], desktop: str) -> None:
    """预览:从 → 到 + 原因。只读展示,不碰真文件。"""
    if not actions:
        print("  (没有需要整理的文件)")
        return
    for i, action in enumerate(actions, 1):
        src = os.path.relpath(action.src, desktop)
        dst = os.path.relpath(action.dst, desktop)
        print(f"  [{i:>3}] {src}  →  {dst}({action.reason})")


def print_details(summary: ExecuteResult) -> None:
    """跳过/失败明细,可展开查看原因。"""
    problems = [d for d in summary.details if d[0] in ("skip", "fail")]
    if not problems:
        return
    print("\n跳过/失败明细:")
    for status, src, dst, reason in problems:
        print(f"  [{STATUS_LABELS.get(status, status)}] {os.path.basename(src)} —— {reason}")


def cmd_scan(_args) -> int:
    desktop = get_desktop_path()
    result = scan_desktop(desktop)
    files = [i for i in result.items if not i.is_dir]
    dirs = [i for i in result.items if i.is_dir]

    print(f"桌面路径:{desktop}")
    print(f"文件 {len(files)} 个,文件夹 {len(dirs)} 个(已排除 {result.skipped} 个系统/隐藏条目)\n")
    print(f"{'名称':<36} {'扩展名':<7} {'大小':>9}  {'修改时间':<17} 类型")
    for item in sorted(result.items, key=lambda i: (i.is_dir, i.name.lower())):
        kind = "文件夹(保留,不处理)" if item.is_dir else "文件"
        print(
            f"{item.name:<36} {item.ext or '-':<7} {human_size(item.size):>9}"
            f"  {format_time(item.mtime):<17} {kind}"
        )
    return 0


def build_all_plans(items, desktop: str, cfg: dict) -> List[Plan]:
    """内置方案(保守/标准/按时间)+ 自定义方案(本地手动编辑或 AI 生成的规则)。"""
    plans = generate_plans(items, desktop)
    rules = cfg.get("manual_rules") or cfg.get("ai_rules")
    if isinstance(rules, list) and rules:
        plans.append(
            build_plan_from_rules(
                items,
                desktop,
                rules,
                description=f"自定义关键词规则 x {len(rules)}",
            )
        )
    return plans


def cmd_plan(_args) -> int:
    desktop = get_desktop_path()
    result = scan_desktop(desktop)
    plans = build_all_plans(result.items, desktop, load_config())
    for idx, plan in enumerate(plans, 1):
        print(f"\n方案 {idx}:{plan.name} —— {plan.description}(共 {plan.total} 个动作)")
        print_preview(plan.actions, desktop)
    return 0


def choose_plan(plans: List[Plan], args) -> Optional[Plan]:
    """按命令行参数或交互输入选择方案,默认 1(保守,最安全)。"""
    if args.plan:
        key = args.plan.strip()
        for i, plan in enumerate(plans, 1):
            if key in (plan.name, str(i)):
                return plan
        print(f"未知方案「{args.plan}」,可选:{'、'.join(p.name for p in plans)}")
        return None

    print("可用整理方案:")
    for i, plan in enumerate(plans, 1):
        print(f"  {i}. {plan.name} —— {plan.description}(共 {plan.total} 个动作)")
    raw = input(f"请选择方案 [1-{len(plans)},回车默认 1]:").strip()
    if not raw:
        return plans[0]
    for i, plan in enumerate(plans, 1):
        if raw in (plan.name, str(i)):
            return plan
    print("无效的选择。")
    return None


def cmd_run(args) -> int:
    desktop = get_desktop_path()
    result = scan_desktop(desktop)
    plans = build_all_plans(result.items, desktop, load_config())

    plan = choose_plan(plans, args)
    if plan is None:
        return 1
    if not plan.actions:
        print("所选方案没有需要整理的文件,未做任何改动。")
        return 0

    print(f"\n预览方案「{plan.name}」(在你确认前不会动任何文件):")
    print_preview(plan.actions, desktop)

    # 用户可勾选排除部分文件(编号对应预览列表)
    excluded = set()
    if not args.yes:
        raw = input("\n输入要排除的编号(逗号或空格分隔,直接回车 = 全部整理):").strip()
        for part in raw.replace(",", " ").replace("，", " ").split():
            if part.isdigit():
                excluded.add(int(part))
    actions = [a for i, a in enumerate(plan.actions, 1) if i not in excluded]
    if not actions:
        print("所有动作均被排除,未做任何改动。")
        return 0
    if excluded:
        print(f"已排除 {len(excluded)} 项,本次将整理 {len(actions)} 个文件。")

    if not args.yes:
        answer = input(f"\n确认移动 {len(actions)} 个文件?(随时可用 undo 撤销)[y/N]:").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消,未做任何改动。")
            return 0

    # 执行前清理超出保留数量的旧日志(提示,不静默删除)
    removed = cleanup_old_batches()
    if removed:
        print(f"提示:已清理 {len(removed)} 个超出保留数量(最近 30 次)的旧日志文件。")

    batch = BatchLogger()
    summary = execute(actions, desktop, batch)
    print(f"\n整理完成:成功 {summary.moved}、跳过 {summary.skipped}、失败 {summary.failed}")
    print(f"日志批次:{batch.batch_id}")
    print_details(summary)
    print(auto_arrange_note(desktop))
    return 0


def cmd_undo(args) -> int:
    desktop = get_desktop_path()
    batch_path = latest_organize_batch()
    if batch_path is None:
        print("没有可撤销的整理记录。")
        return 0
    print(f"将撤销整理批次:{os.path.basename(batch_path)}")

    if not args.yes:
        answer = input("文件将被移回整理前的原位置。确认?[y/N]:").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消,未做任何改动。")
            return 0

    summary = undo_last(desktop)
    if summary is None:
        print("没有可撤销的整理记录。")
        return 0
    print(f"\n撤销完成:还原 {summary.moved}、跳过 {summary.skipped}、失败 {summary.failed}")
    print_details(summary)
    print(auto_arrange_note(desktop))
    return 0


def cmd_ai(args) -> int:
    """AI 转规则:自然语言 → 关键词规则(存入配置),生成自定义方案预览。"""
    desc = (args.desc or "").strip()
    if not desc:
        print("请用 --desc 描述整理需求,例:python main.py ai --desc \"把论文和报告放一起\"")
        return 1

    desktop = get_desktop_path()
    result = scan_desktop(desktop)
    cfg = load_config()
    try:
        rules = generate_rules(
            desc, [i.name for i in result.items if not i.is_dir], cfg.get("ai", {})
        )
    except AIError as e:
        print(f"AI 生成失败:{e}")
        return 1

    # 并入统一的自定义规则池(同文件夹以新生成的为准)
    merged = {r["folder"]: r for r in manual_rules.load_rules()}
    for rule in rules:
        normalized = manual_rules.normalize_rule(rule)
        if normalized:
            merged[normalized["folder"]] = normalized
    final_rules = list(merged.values())
    manual_rules.save_rules(final_rules)
    print(
        f"已生成 {len(rules)} 条关键词规则并并入自定义规则池"
        f"(共 {len(final_rules)} 条,可用 run --plan 自定义 执行):"
    )
    for rule in rules:
        print(f"  {' / '.join(rule['keywords'])}  →  {rule['folder']}")

    plan = build_plan_from_rules(result.items, desktop, rules)
    print(f"\n预览方案「{plan.name}」(共 {plan.total} 个动作):")
    print_preview(plan.actions, desktop)

    if args.yes:
        answer = "y"
    else:
        answer = input("\n确认按此方案执行?[y/N]:").strip().lower()
    if answer not in ("y", "yes"):
        print("已取消,未做任何改动。")
        return 0

    batch = BatchLogger()
    summary = execute(plan.actions, desktop, batch)
    print(f"\n整理完成:成功 {summary.moved}、跳过 {summary.skipped}、失败 {summary.failed}")
    print(f"日志批次:{batch.batch_id}")
    print_details(summary)
    print(auto_arrange_note(desktop))
    return 0


def build_zone_of(result) -> dict:
    """图标分区:0=系统/未知,1=文件夹,2=快捷方式,3=文件。"""
    zone_of = {}
    for item in result.items:
        if item.is_dir:
            zone_of[item.name] = 1
        elif is_shortcut(item):
            zone_of[item.name] = 2
        else:
            zone_of[item.name] = 3
    return zone_of


def auto_arrange_note(desktop: str) -> str:
    """整理/撤销后自动分区排列(仅当系统自动排列关闭时),返回提示文字。"""
    try:
        icons_now = arranger.read_icons()
        if arranger.is_auto_arrange_on(icons_now):
            return ""
        fresh = scan_desktop(desktop)
        placed = arranger.arrange(build_zone_of(fresh))
        return f"\n已自动按分区排列 {placed} 个图标(文件夹 → 快捷方式 → 文件)。"
    except OSError as e:
        logging.warning("自动分区排列失败: %s", e)
        return ""


def cmd_arrange(_args) -> int:
    """B 方案第一版:图标按「文件夹 → 快捷方式 → 文件」分区紧凑排列。"""
    desktop = get_desktop_path()
    result = scan_desktop(desktop)
    placed = arranger.arrange(build_zone_of(result))
    print(f"已按分区(文件夹 → 快捷方式 → 文件)摆放 {placed} 个图标。")
    return 0


def cmd_rules(args) -> int:
    """本地自定义规则管理:列出默认;`add 关键词,关键词 文件夹` 添加;`remove 序号` 删除。"""
    if getattr(args, "rules_cmd", None) == "add":
        added = manual_rules.add_rule(args.keywords, args.folder)
        if added is None:
            print("规则不合格:需要至少一个关键词,文件夹名不能含 \\ / : * ? \" < > | 等字符。")
            return 1
        print(f"已添加:{' / '.join(added['keywords'])}  →  {added['folder']}")
    elif getattr(args, "rules_cmd", None) == "remove":
        if not manual_rules.remove_rule(args.index - 1):
            print(f"序号 {args.index} 不存在。")
            return 1
        print(f"已删除第 {args.index} 条规则。")

    rules = manual_rules.load_rules()
    if not rules:
        print("当前没有自定义规则。添加示例:python main.py rules add \"论文,报告\" 学术资料")
        return 0
    print(f"当前自定义规则({len(rules)} 条):")
    for i, rule in enumerate(rules, 1):
        print(f"  {i}. {' / '.join(rule['keywords'])}  →  {rule['folder']}")
    print("提示:run --plan 自定义 可按这些规则整理。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="桌面整理助手(A 方案 MVP):安全、可预览、可撤销"
    )
    # command 不再强制:不带参数运行(双击 exe)时进入交互菜单模式
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scan", help="只读扫描桌面顶层,列出文件").set_defaults(func=cmd_scan)
    sub.add_parser("plan", help="预览整理方案,不执行").set_defaults(func=cmd_plan)

    p_run = sub.add_parser("run", help="选择方案并执行整理")
    p_run.add_argument("--plan", help="方案名称或编号(保守/标准/按时间/自定义),不填则交互选择")
    p_run.add_argument("--yes", action="store_true", help="跳过交互确认(测试用)")
    p_run.set_defaults(func=cmd_run)

    p_undo = sub.add_parser("undo", help="撤销最近一次整理")
    p_undo.add_argument("--yes", action="store_true", help="跳过交互确认(测试用)")
    p_undo.set_defaults(func=cmd_undo)

    p_ai = sub.add_parser("ai", help="AI 转规则:一句话生成自定义整理方案")
    p_ai.add_argument("--desc", help="整理需求描述,例:\"把论文和报告放一起\"")
    p_ai.add_argument("--yes", action="store_true", help="跳过交互确认(测试用)")
    p_ai.set_defaults(func=cmd_ai)

    sub.add_parser("arrange", help="分区排列桌面图标(文件夹→快捷方式→文件)").set_defaults(
        func=cmd_arrange
    )

    p_rules = sub.add_parser("rules", help="本地自定义规则管理(无需 AI)")
    rules_sub = p_rules.add_subparsers(dest="rules_cmd")
    p_rules_add = rules_sub.add_parser("add", help="添加规则:add \"关键词,关键词\" 文件夹")
    p_rules_add.add_argument("keywords", help="关键词,逗号或空格分隔")
    p_rules_add.add_argument("folder", help="目标文件夹名")
    p_rules_rm = rules_sub.add_parser("remove", help="按序号删除规则")
    p_rules_rm.add_argument("index", type=int, help="规则序号(见 rules 列表)")
    p_rules.set_defaults(func=cmd_rules)

    return parser


MENU_ACTIONS = {
    "1": ("只读扫描桌面(看看桌面上有什么)", cmd_scan),
    "2": ("预览整理方案(不执行)", cmd_plan),
    "3": ("开始整理(选方案 → 预览 → 确认 → 执行)", cmd_run),
    "4": ("撤销最近一次整理", cmd_undo),
    "5": ("分区排列桌面图标(文件夹→快捷方式→文件)", cmd_arrange),
}


def pause() -> None:
    input("\n按回车键返回菜单...")


def interactive_menu() -> int:
    """双击 exe / 无参数运行时的交互菜单模式。

    每个操作结束后暂停等待回车,避免控制台窗口一闪而过;
    出错时显示原因而不是直接崩溃退出。
    """
    while True:
        print("\n" + "=" * 40)
        print("桌面整理助手(安全、可预览、可撤销)")
        print("=" * 40)
        for key, (label, _) in MENU_ACTIONS.items():
            print(f"  {key}. {label}")
        print("  0. 退出")
        try:
            choice = input("\n请选择:").strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if choice == "0":
            print("再见!")
            return 0
        if choice not in MENU_ACTIONS:
            print("无效的选择,请重新输入。")
            continue

        label, func = MENU_ACTIONS[choice]
        try:
            # 交互模式下不用命令行参数
            func(argparse.Namespace(plan=None, yes=False))
        except Exception as e:
            print(f"\n出错了:{e}")
        pause()


def main() -> int:
    args = build_parser().parse_args()
    if args.command is None:
        return interactive_menu()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
