# -*- coding: utf-8 -*-
"""视觉缺口检测(文章第三节第二层规则,不消耗模型 Token)。"""
from typing import Any, Dict, List


def detect_gaps(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按文章规则判定 XML 视觉缺口:"""
    gaps: List[Dict[str, Any]] = []
    seen: Dict[str, List[str]] = {}

    # 相同属性控件分组(重复控件/组合容器)
    for p in profiles:
        key = repr((p["xml"].get("class"), p["xml"].get("bounds")))
        seen.setdefault(key, []).append(p["control_id"])

    for p in profiles:
        xml = p["xml"]
        # 1. 无文本控件(依赖图标/自绘)
        if not xml.get("text") and not xml.get("content-desc") and xml.get("clickable"):
            gaps.append({
                "control_id": p["control_id"], "gap_type": "no_text",
                "detail": f"控件 {p['control_id']} 可点击但无 text/content-desc,语义只能依赖视觉判断",
                "page": p["page"],
            })
        # 2. 无 resource-id
        if not xml.get("resource-id") and (xml.get("clickable") or xml.get("editable")):
            gaps.append({
                "control_id": p["control_id"], "gap_type": "no_id",
                "detail": f"控件 {p['control_id']} 无 resource-id,定位稳定性依赖文本/层级/坐标",
                "page": p["page"],
            })
        # 3. 自绘图标(ImageView 可点击且无 desc)
        if "ImageView" in (xml.get("class") or "") and xml.get("clickable") and not xml.get("content-desc"):
            gaps.append({
                "control_id": p["control_id"], "gap_type": "icon_only",
                "detail": f"控件 {p['control_id']} 为自绘图标按钮,XML 无法表达业务含义,需要视觉模型补充",
                "page": p["page"],
            })
        # 4. 组合条目容器(列表项,内含多个子控件,容易误点)
        children = (p.get("context") or {}).get("children") or []
        if xml.get("clickable") and len(children) >= 2:
            gaps.append({
                "control_id": p["control_id"], "gap_type": "composite_item",
                "detail": f"控件 {p['control_id']} 是包含 {len(children)} 个子控件的组合条目,按文本搜索可能误点内部子控件而非真正目标",
                "page": p["page"],
            })
        # 5. 高风险且只能坐标定位
        if p.get("risk") == "high" and xml.get("clickable"):
            gaps.append({
                "control_id": p["control_id"], "gap_type": "coord_only",
                "detail": f"控件 {p['control_id']} 无任何稳定属性,只能坐标定位,分辨率/状态变化后可能失效",
                "page": p["page"],
            })

    # 6. 属性完全相同的重复控件
    for key, ids in seen.items():
        if len(ids) > 1:
            gaps.append({
                "control_id": ids[0], "gap_type": "duplicate",
                "detail": f"控件 {', '.join(ids)} 属性完全相同,存在歧义,需视觉/上下文区分",
                "page": "",
            })

    # 去重(同控件同类型)
    dedup = {}
    for g in gaps:
        k = (g["control_id"], g["gap_type"])
        dedup[k] = g
    return list(dedup.values())
