"""AI 输出的结构化解析（用例 JSON 多策略提取）。

从 main.py 抽出，供 SSE 流式端点与序列调度器（gen_queue）复用，
避免 api 层反向依赖 main 造成循环导入。
"""

import json as _json
import re
from typing import Optional


def parse_generated_cases(text: str) -> Optional[dict]:
    """多策略解析 AI 输出的用例 JSON(直接解析 → 代码块 → 数组边界 → 截断修复)。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    candidates = []
    # 1) 直接解析
    candidates.append(cleaned)
    # 2) 提取 ```json 代码块
    m = re.search(r"```(?:json)?\s*\n([\s\S]*?)```", cleaned)
    if m:
        candidates.append(m.group(1).strip())
    # 3) 首个 { 到末个 } 之间
    i, j = cleaned.find("{"), cleaned.rfind("}")
    if i >= 0 and j > i:
        candidates.append(cleaned[i : j + 1])
    parsed = None
    for c in candidates:
        try:
            obj = _json.loads(c)
            if isinstance(obj, dict):
                parsed = obj
                break
        except Exception:
            continue
    # 4) 截断修复:去掉尾部不完整的对象后补 ]
    if parsed is None:
        m = re.search(r"\{[\s\S]*", cleaned)
        if m:
            frag = m.group(0)
            for cut in range(len(frag), 1, -1):
                probe = frag[:cut].rstrip().rstrip(",") + "]}"
                try:
                    obj = _json.loads(probe)
                    if isinstance(obj, dict):
                        parsed = obj
                        break
                except Exception:
                    continue
            if parsed is None and "cases" in frag:
                # 逐对象抢救
                objs = []
                for om in re.finditer(r"\{[^{}]*\}", frag):
                    try:
                        o = _json.loads(om.group(0))
                        if isinstance(o, dict) and ("name" in o or "steps" in o):
                            objs.append(o)
                    except Exception:
                        continue
                if objs:
                    parsed = {"cases": objs}
    if not parsed:
        return None
    raw_cases = parsed.get("cases")
    if isinstance(parsed, list):
        raw_cases = parsed
        parsed = {"summary": "", "cases": raw_cases}
    if not isinstance(raw_cases, list):
        return None
    cases = []
    for c in raw_cases:
        if not isinstance(c, dict):
            continue
        cases.append(
            {
                "module": str(c.get("module") or "通用"),
                "name": str(c.get("name") or c.get("title") or "未命名用例"),
                "priority": str(c.get("priority") or "P2").upper()[:2],
                "type": str(c.get("type") or "功能"),
                "precondition": str(
                    c.get("precondition") or c.get("pre_condition") or ""
                ),
                "steps": str(c.get("steps") or ""),
                "expected": str(c.get("expected") or c.get("expected_result") or ""),
            }
        )
    if not cases:
        return None
    return {"summary": str(parsed.get("summary") or ""), "cases": cases}
