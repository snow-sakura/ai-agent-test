# -*- coding: utf-8 -*-
"""离线解析 uiautomator XML → 生成控件画像(不消耗模型 Token,可重复可审计)。"""
import hashlib
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

INTERESTING_CLASSES = (
    "Button", "EditText", "CheckBox", "Switch", "RadioButton", "ImageButton",
    "ImageView", "TextView", "LinearLayout", "FrameLayout", "View", "RecyclerView",
)


def _parse_bounds(bounds: str) -> Optional[Tuple[int, int, int, int]]:
    m = BOUNDS_RE.match(bounds or "")
    if not m:
        return None
    return tuple(int(v) for v in m.groups())


def _area(bounds: str) -> int:
    b = _parse_bounds(bounds)
    if not b:
        return 0
    x1, y1, x2, y2 = b
    return max(0, x2 - x1) * max(0, y2 - y1)


def _slug(text: str) -> str:
    t = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fa5]", "", text or "")
    return t[:20] or "ctrl"


def parse_xml_controls(xml: str) -> List[Dict[str, Any]]:
    """解析 XML 树,展平控件节点(带父子引用)"""
    root = ET.fromstring(xml)
    nodes: List[Dict[str, Any]] = []

    def walk(el: ET.Element, parent_idx: Optional[int], depth: int):
        attrs = el.attrib
        idx = len(nodes)
        node = {
            "index": idx,
            "parent": parent_idx,
            "depth": depth,
            "resource_id": attrs.get("resource-id", "") or attrs.get("resource_id", ""),
            "text": attrs.get("text", ""),
            "class": attrs.get("class", ""),
            "content_desc": attrs.get("content-desc", "") or attrs.get("content_desc", ""),
            "clickable": attrs.get("clickable", "false") == "true",
            "enabled": attrs.get("enabled", "true") == "true",
            "scrollable": attrs.get("scrollable", "false") == "true",
            "editable": "EditText" in (attrs.get("class") or ""),
            "bounds": attrs.get("bounds", ""),
            "package": attrs.get("package", ""),
        }
        nodes.append(node)
        for child in el:
            walk(child, idx, depth + 1)

    # hierarchy 根节点可能是 <hierarchy><node .../></hierarchy>
    for top in root.iter("node"):
        walk_once_done = False
        break
    # 从顶层 node 开始遍历(仅第一棵子树)
    tops = [el for el in root.iter("node")]
    if tops:
        start = tops[0]
        # 重建父子:逐个遍历
        nodes = []

        def walk2(el, parent_idx, depth):
            attrs = el.attrib
            idx = len(nodes)
            nodes.append({
                "index": idx, "parent": parent_idx, "depth": depth,
                "resource_id": attrs.get("resource-id", ""),
                "text": attrs.get("text", ""),
                "class": attrs.get("class", ""),
                "content_desc": attrs.get("content-desc", ""),
                "clickable": attrs.get("clickable", "false") == "true",
                "enabled": attrs.get("enabled", "true") == "true",
                "scrollable": attrs.get("scrollable", "false") == "true",
                "editable": "EditText" in (attrs.get("class") or ""),
                "bounds": attrs.get("bounds", ""),
                "package": attrs.get("package", ""),
            })
            for child in el.findall("node"):
                walk2(child, idx, depth + 1)

        walk2(start, None, 0)
    return nodes


def build_profiles(xml: str, page: str) -> List[Dict[str, Any]]:
    """生成控件画像列表(文章第四节的画像结构)"""
    nodes = parse_xml_controls(xml)
    profiles: List[Dict[str, Any]] = []
    seen_key_counts: Dict[str, int] = {}

    def ctx_of(node):
        parent = nodes[node["parent"]] if node["parent"] is not None and node["parent"] < len(nodes) else None
        siblings = [n for n in nodes if n.get("parent") == node.get("parent") and n["index"] != node["index"]]
        children = [n for n in nodes if n.get("parent") == node["index"]]
        return parent, siblings, children

    for node in nodes:
        short_class = (node["class"].rsplit(".", 1)[-1] if node["class"] else "View")
        is_container = short_class in ("LinearLayout", "FrameLayout", "RecyclerView") and not node["clickable"]
        has_signal = (node["clickable"] or node["editable"] or node["text"] or node["content_desc"]
                      or node["resource_id"] or node["scrollable"])
        if is_container and not node["resource_id"]:
            continue
        if not has_signal:
            continue

        # control_id 命名: 页面.语义名(优先 resource-id 尾段 → 文本 → desc → 类型序号)
        if node["resource_id"]:
            base = node["resource_id"].split("/")[-1]
        elif node["text"]:
            base = _slug(node["text"].split("\\n")[0])
        elif node["content_desc"]:
            base = _slug(node["content_desc"])
        else:
            base = f"{short_class.lower()}_{node['index']}"
        key = f"{page}.{base}"
        seen_key_counts[key] = seen_key_counts.get(key, 0) + 1
        if seen_key_counts[key] > 1:
            control_id = f"{key}_{seen_key_counts[key]}"
        else:
            control_id = key

        parent, siblings, children = ctx_of(node)
        actions = []
        if node["clickable"]:
            actions.append("tap")
        if node["editable"]:
            actions.extend(["input_text", "clear_text"])
        if node["scrollable"]:
            actions.extend(["swipe", "scroll"])
        if not actions and (node["text"] or node["content_desc"]):
            actions.append("read")

        locator_candidates = []
        if node["resource_id"]:
            locator_candidates.append("resource-id")
        if node["content_desc"]:
            locator_candidates.append("content-desc")
        if node["text"]:
            locator_candidates.append("text+class")
        if parent and (parent.get("resource_id") or parent.get("class")):
            locator_candidates.append("parent-child relationship")
        locator_candidates.append("coordinate")

        # 风险: 无 id 且无 text 高风险;仅坐标中风险;其余低
        if not node["resource_id"] and not node["text"] and not node["content_desc"]:
            risk = "high"
        elif not node["resource_id"]:
            risk = "medium"
        else:
            risk = "low"

        role = node["content_desc"] or node["text"].split("\\n")[0] or node["resource_id"].split("/")[-1] or short_class
        profiles.append({
            "control_id": control_id,
            "role": role,
            "page": page,
            "xml": {
                "class": node["class"], "text": node["text"],
                "resource-id": node["resource_id"], "content-desc": node["content_desc"],
                "bounds": node["bounds"], "clickable": node["clickable"],
                "enabled": node["enabled"], "scrollable": node["scrollable"],
                "editable": node["editable"],
                "center": _center(node["bounds"]),
            },
            "context": {
                "parent": (parent.get("resource_id") or parent.get("class")) if parent else None,
                "siblings": [s.get("resource_id", "").split("/")[-1] or s.get("class", "").rsplit(".", 1)[-1] for s in siblings[:6]],
                "children": [c.get("resource_id", "").split("/")[-1] or c.get("class", "").rsplit(".", 1)[-1] for c in children[:6]],
                "depth": node["depth"],
            },
            "actions": actions,
            "locator_candidates": locator_candidates,
            "risk": risk,
            "verification": "pending",
            "source": ["xml"],
            "visual": {},
        })
    return profiles


def _center(bounds: str):
    b = _parse_bounds(bounds)
    if not b:
        return None
    x1, y1, x2, y2 = b
    return [(x1 + x2) // 2, (y1 + y2) // 2]
