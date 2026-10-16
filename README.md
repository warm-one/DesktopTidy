# 桌面整理助手 DesktopTidy

一个面向 Windows 普通用户的**桌面整理工具**：把桌面顶层的零散文件安全地收进分类文件夹——**可预览、可撤销、绝不删除**。

![主界面](docs/screenshot-main.png)

## 为什么敢用它

市面上的桌面整理工具，要么自动移动文件让人心里没底，要么在文件被占用时把文件搞丢。本项目的第一优先级是**不丢文件、不崩溃、可后悔**，十条安全铁律写进了需求和代码：

| # | 铁律 |
|---|------|
| 1 | 绝不删除任何文件 |
| 2 | 绝不覆盖任何文件（目标同名时自动加 `(1)`） |
| 3 | 绝不主动重命名文件 |
| 4 | 只移动文件，不碰任何文件夹 |
| 5 | 只操作当前用户桌面内部，不跨盘、不碰系统目录 |
| 6 | 只处理桌面顶层，不递归子文件夹 |
| 7 | 每一步都可预览、可撤销 |
| 8 | 执行必写日志，撤销靠日志反向移动 |
| 9 | 文件被占用/移动失败 → 跳过并记录，不中断 |
| 10 | AI 只生成规则，绝不直接操作文件 |

![预览](docs/screenshot-preview.png)

## 功能

- **只读扫描**：列出桌面顶层所有文件（名称、扩展名、大小、修改时间），文件夹标记为"保留"
- **整理方案**：内置 保守 / 标准（按类型）/ 按时间 三套方案，外加自定义"关键词 → 文件夹"规则（本地手动编辑，无需 AI；也可一句话让 AI 生成）
- **预览**：执行前显示"从 → 到 + 原因"，每个文件可勾选排除；GUI 里有"整理后桌面"卡片概览
- **执行**：逐个移动，先检测是否被占用；目标同名自动加 `(1)`
- **撤销**：针对最近一次整理，按日志反向还原
- **图标排列（实验性）**：把桌面图标按「文件夹 → 快捷方式 → 文件」分区紧凑排列，只调坐标不动文件
- **日志**：每条记录一行 JSON（batch_id / action / src / dst / reason），存于 `%LOCALAPPDATA%\DesktopOrganizer\logs\`，保留最近 30 次

## 快速开始

需要 Python 3.10+（无第三方依赖时 GUI 需 `pip install customtkinter`，打包用 PyInstaller）：

```bash
# 命令行版
python main.py               # 双击模式：交互菜单
python main.py scan          # 只读扫描
python main.py plan          # 预览方案
python main.py run           # 选方案 -> 预览 -> 确认 -> 执行
python main.py undo          # 撤销最近一次整理

# 图形界面版
python gui_main.py
```

| CLI 命令 | 作用 |
|----------|------|
| `scan` | 只读扫描桌面顶层 |
| `plan` | 预览整理方案（不动文件） |
| `run` | 选方案 -> 预览 -> 确认 -> 执行（`--plan 名称` 跳过交互） |
| `undo` | 撤销最近一次整理 |
| `arrange` | 实验性：图标按分区排列 |
| `rules add/remove` | 本地自定义规则管理（无需 AI） |
| `ai --desc "..."` | 一句话让 AI 生成关键词规则 |

## 构建 exe 与安装包

```bash
pip install pyinstaller customtkinter pillow
pyinstaller DesktopTidy.spec --noconfirm     # GUI 版 -> dist/DesktopTidy.exe
pyinstaller DesktopTidyCLI.spec --noconfirm  # CLI 版 -> dist/DesktopTidyCLI.exe
```

安装包：安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php) 后编译 `DesktopTidy.iss`，产物在 `dist/installer/`。

## 测试

```bash
pip install pytest
python -m pytest tests -q
```

覆盖扫描、规则、执行、日志、撤销、配置、AI 规则、手动规则、图标排列共 62 个用例；执行与撤销模块含安全边界测试（文件占用、目标同名、撤销冲突）。

## Roadmap

- [x] A 方案：移动文件（扫描 / 预览 / 执行 / 撤销）
- [x] B 方案第一版：图标分区排列（实验性，需关闭系统"自动排列图标"）
- [ ] B 方案增强：网格布局 / 按类型分区货架自选布局 / 排列撤销
- [ ] 保守运行时自动检测占用窗口
