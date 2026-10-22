# -*- coding: utf-8 -*-
"""设备验证:点击 locator → 比对页面指纹 → 通过才允许固化。"""
from typing import Any, Dict, List

from app.app_automation.engine import mock_device


def verify_locator(device_id: str, locator: Dict[str, Any]) -> Dict[str, Any]:
    """在(模拟)设备上执行点击,验证页面指纹是否按预期变化。"""
    session = mock_device.get_mock_session(device_id)
    before = session.fingerprint()
    strategy = locator.get("strategy")
    expression = locator.get("expression", "")
    try:
        if strategy == "id":
            r = session.tap_control(resource_id=expression)
        elif strategy == "content-desc":
            r = session.tap_control(content_desc=expression)
        elif strategy in ("text+class", "text"):
            text = expression.split('text="')[-1].split('"')[0] if 'text="' in expression else expression
            r = session.tap_control(text=text)
        elif strategy == "coordinate":
            x, y = [int(v) for v in expression.split(",")]
            r = session.tap(x, y)
            r["success"] = True
        elif strategy == "combo":
            child = expression.split(">")[-1].strip()
            r = session.tap_control(resource_id=child if child.startswith("com.") else "",
                                    text=child if not child.startswith("com.") else "")
        else:
            return {"success": False, "error": f"未知策略: {strategy}", "before": before}
    except Exception as e:
        return {"success": False, "error": str(e), "before": before}

    after = session.fingerprint()
    changed = before["control_hash"] != after["control_hash"] or before["page"] != after["page"]
    return {
        "success": bool(r.get("success")),
        "hit": r.get("hit_resource_id") or r.get("hit_content_desc"),
        "transition": r.get("transition"),
        "fingerprint_changed": changed,
        "before": before,
        "after": after,
        "error": r.get("error") or r.get("detail"),
    }
