# -*- coding: utf-8 -*-
"""画像驱动 locator 生成:资源定位策略优先级(不直接采用视觉坐标)。"""
from typing import Any, Dict, List, Optional


def generate_locators(profiles: List[Dict[str, Any]],
                      target_controls: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """为每个(或指定)画像生成 locator 候选,策略优先级:
    resource-id > content-desc > text+class > parent-child combo > coordinate(仅候选)
    """
    out = []
    for p in profiles:
        if target_controls and p["control_id"] not in target_controls:
            continue
        xml = p["xml"]
        rid = xml.get("resource-id") or ""
        desc = xml.get("content-desc") or ""
        text = xml.get("text") or ""
        cls = xml.get("class") or ""
        parent = (p.get("context") or {}).get("parent")
        center = xml.get("center")

        candidates = []
        if rid:
            candidates.append({"strategy": "id", "expression": rid, "priority": 1,
                               "stable": True, "note": "resource-id 最稳定"})
        if desc:
            candidates.append({"strategy": "content-desc", "expression": desc, "priority": 2,
                               "stable": True, "note": "content-desc 无障碍描述较稳定"})
        if text:
            candidates.append({"strategy": "text+class", "expression": f'text="{text}" AND class="{cls}"',
                               "priority": 3, "stable": len(text) >= 2,
                               "note": "文本匹配,注意与列表项内部子控件区分"})
        if parent and (rid or text or desc):
            candidates.append({"strategy": "combo",
                               "expression": f'parent={parent} > {rid or desc or text}',
                               "priority": 4, "stable": True,
                               "note": "父容器+子属性组合,适合组合条目/重复控件"})
        if center:
            candidates.append({"strategy": "coordinate",
                               "expression": f"{center[0]}, {center[1]}",
                               "priority": 9, "stable": False,
                               "note": "坐标仅作候选证据,不直接写入正式代码"})
        if not candidates:
            continue
        best = min(candidates, key=lambda c: c["priority"])
        out.append({
            "profile_id": p.get("_db_id"),
            "control_id": p["control_id"],
            "page": p["page"],
            "selected": best,
            "candidates": candidates,
        })
    return out
