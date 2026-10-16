"""AI 转规则模块(AGENT.md 第 7 步:自然语言 → 规则 JSON)。

安全边界(铁律 10、第 11 节 AI 输出边界):
- AI 只负责把自然语言描述转成 JSON 规则,绝不直接操作文件
- 输出必须是规定结构的 JSON,解析、清洗、校验全部由确定性代码完成
- 规则只影响"把哪些文件移动到哪个文件夹",执行仍走 executor 的安全通道
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class AIError(Exception):
    """AI 功能相关的可读错误(界面/命令行直接展示给用户)。"""


# 规则数量与长度上限,防止 AI 返回异常数据
MAX_RULES = 10
MAX_KEYWORDS_PER_RULE = 20
MAX_FOLDER_NAME_LEN = 40
MAX_FILE_NAMES = 300  # 提示词里最多带多少个文件名

REQUEST_TIMEOUT = 30

SYSTEM_PROMPT = (
    "你是桌面整理助手。用户会用一句话描述整理需求,并附上桌面文件名列表。"
    '请输出 JSON 规则,格式:{"rules": [{"keywords": ["关键词1", "关键词2"], "folder": "分类文件夹名"}]}。'
    f"要求:最多 {MAX_RULES} 条规则;每条最多 {MAX_KEYWORDS_PER_RULE} 个关键词;"
    "folder 名为 2~8 个字的中文或英文短词,禁止包含路径分隔符或特殊字符;"
    "关键词按文件名包含匹配(不区分大小写);快捷方式(如 .lnk/.url 文件)会由系统保留在桌面,不要为它们设置规则;"
    "没有匹配到的文件保持不动。"
    "只输出 JSON,不要输出任何解释或 markdown。"
)


def build_user_prompt(desc: str, file_names: List[str]) -> str:
    names = "\n".join(file_names[:MAX_FILE_NAMES])
    return f"整理需求:{desc}\n\n桌面文件名列表:\n{names}"


def generate_rules(
    desc: str, file_names: List[str], ai_cfg: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """调用 OpenAI 兼容接口,把自然语言描述转成校验后的关键词规则列表。

    ai_cfg 来自 config.json 的 "ai" 字段:base_url / model / api_key。
    """
    api_key = str(ai_cfg.get("api_key") or "").strip()
    if not api_key:
        raise AIError("尚未配置 AI:请先在「AI 设置」里填写 API Key")

    base_url = str(ai_cfg.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise AIError("尚未配置 AI 接口地址(base_url)")
    model = str(ai_cfg.get("model") or "deepseek-chat").strip() or "deepseek-chat"

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(desc, file_names)},
        ],
    }
    response = _post_json(base_url + "/chat/completions", payload, api_key)
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"AI 接口返回结构异常: {e}") from e
    return parse_rules(content)


def parse_rules(text: str) -> List[Dict[str, Any]]:
    """解析并校验 AI 输出的规则 JSON,只保留结构正确的条目。"""
    data = _extract_json(text)
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list) or not rules:
        raise AIError("AI 返回的规则为空或格式不正确")

    valid: List[Dict[str, Any]] = []
    for rule in rules[:MAX_RULES]:
        if not isinstance(rule, dict):
            continue
        raw_keywords = rule.get("keywords", [])
        if not isinstance(raw_keywords, list):
            continue
        keywords = [
            str(k).strip()
            for k in raw_keywords
            if str(k).strip()
        ][:MAX_KEYWORDS_PER_RULE]
        folder = sanitize_folder(rule.get("folder", ""))
        if keywords and folder:
            valid.append({"keywords": keywords, "folder": folder})

    if not valid:
        raise AIError("AI 返回的规则中没有有效项")
    return valid


def sanitize_folder(name: Any) -> str:
    """清洗 AI 给出的分类文件夹名,非法名称返回空字符串。"""
    name = str(name).strip()
    if not name or len(name) > MAX_FOLDER_NAME_LEN or name in (".", ".."):
        return ""
    if re.search(r'[\\/:*?"<>|]', name):  # Windows 文件名非法字符
        return ""
    return name


def _extract_json(text: str) -> dict:
    """从 AI 输出中提取 JSON 对象,容忍 markdown 代码围栏和多余文字。"""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise AIError("AI 未返回 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise AIError(f"AI 返回的 JSON 无法解析: {e}") from e
    if not isinstance(data, dict):
        raise AIError("AI 返回的不是 JSON 对象")
    return data


def _post_json(url: str, payload: dict, api_key: str, timeout: int = REQUEST_TIMEOUT) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise AIError(f"AI 接口返回错误 {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise AIError(f"无法连接 AI 接口: {e.reason}") from e
    except OSError as e:
        raise AIError(f"连接 AI 接口失败: {e}") from e
