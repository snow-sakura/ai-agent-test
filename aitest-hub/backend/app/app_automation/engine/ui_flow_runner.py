# -*- coding: utf-8 -*-
"""UI Flow 执行器 —— 将 UI Flow JSON 转换为设备动作并执行。

复刻 testhub_platform UiFlowRunner 全部动作(13 种)与变量体系:
touch/click, double_click, swipe, wait, sleep, exists, snapshot, text,
set_variable, unset_variable, extract_output, assert, back
支持 {{variable}} 渲染与 global/local/outputs 三级作用域。
当前以模拟设备驱动;真机 Airtest 驱动按可选依赖预留。
"""
import copy
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from app.app_automation.engine import mock_device
from app.app_automation.engine.adb_manager import AdbManager

logger = logging.getLogger(__name__)

VAR_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")


class StepFailure(Exception):
    pass


class UiFlowRunner:
    def __init__(self, device_id: str, mock_mode: bool = True,
                 screenshot_dir: Optional[str] = None, username: str = "unknown"):
        self.device_id = device_id
        self.mock_mode = mock_mode
        self.adb = AdbManager(mock_mode=mock_mode)
        self.session = mock_device.get_mock_session(device_id) if mock_mode else None
        self.screenshot_dir = screenshot_dir or mock_device.SCREENSHOT_DIR
        os.makedirs(self.screenshot_dir, exist_ok=True)
        self.context: Dict[str, Any] = {"global": {}, "local": {}, "outputs": {}}
        self.runtime = {"retry_times": 3, "retry_interval": 0.5}
        self.stop_flag = False
        self.screenshots: List[Dict[str, str]] = []

    # ---------- 变量体系 ----------
    def _init_context(self, variables: Optional[List[Dict[str, Any]]], runtime: Optional[Dict[str, Any]]):
        for v in (variables or []):
            name = v.get("name") if isinstance(v, dict) else None
            if name:
                self.context["local"][name] = v.get("value", "")
        if runtime:
            self.runtime.update(runtime)

    def _set_variable(self, name: str, value: Any, scope: str = "local"):
        if scope not in self.context:
            scope = "local"
        self.context[scope][name] = value

    def _get_variable(self, path: str) -> Any:
        parts = path.split(".")
        if len(parts) == 2 and parts[0] in self.context:
            return self.context[parts[0]].get(parts[1])
        for scope in ("local", "global", "outputs"):
            if path in self.context[scope]:
                return self.context[scope][path]
        return None

    def render(self, value: Any) -> Any:
        """渲染 {{var}} 占位"""
        if not isinstance(value, str):
            return value
        def _sub(m):
            v = self._get_variable(m.group(1))
            return "" if v is None else str(v)
        return VAR_PATTERN.sub(_sub, value)

    # ---------- 选择器解析 ----------
    def _resolve_selector(self, selector_type: str, selector: str) -> Dict[str, Any]:
        selector = self.render(selector or "")
        if selector_type in ("pos", "coordinate"):
            try:
                x, y = [int(v.strip()) for v in str(selector).split(",")]
                return {"type": "pos", "x": x, "y": y}
            except Exception:
                raise StepFailure(f"坐标格式错误: {selector},应为 'x, y'")
        if selector_type == "element_id":
            return {"type": "element_id", "id": selector}
        if selector_type == "image":
            return {"type": "image", "path": selector}
        if selector_type == "region":
            return {"type": "region", "rect": selector}
        # text / id / desc
        return {"type": selector_type or "text", "value": selector}

    def _find_and_tap(self, sel: Dict[str, Any]) -> Dict[str, Any]:
        if sel["type"] == "pos":
            r = self.session.tap(sel["x"], sel["y"])
            r["success"] = True
            return r
        if sel["type"] == "element_id":
            # element_id 需查库,由上层注入 element_map
            el = (self.element_map or {}).get(sel["id"])
            if not el:
                raise StepFailure(f"元素不存在: {sel['id']}")
            cfg = el.get("config", {})
            etype = el.get("element_type")
            if etype == "pos":
                return self._find_and_tap({"type": "pos", "x": cfg.get("x", 0), "y": cfg.get("y", 0)})
            rid = cfg.get("resource_id", "")
            return self.session.tap_control(resource_id=rid, text=cfg.get("text", ""), content_desc=cfg.get("content_desc", ""))
        if sel["type"] in ("id", "resource_id"):
            return self.session.tap_control(resource_id=sel["value"])
        if sel["type"] == "desc":
            return self.session.tap_control(content_desc=sel["value"])
        # text
        return self.session.tap_control(text=sel["value"])

    element_map: Dict[str, Any] = {}

    # ---------- 动作实现 ----------
    def _action(self, step: Dict[str, Any]) -> Dict[str, Any]:
        action = (step.get("action") or step.get("type") or "").lower()
        if action in ("touch", "click"):
            return self._find_and_tap(self._resolve_selector(step.get("selector_type", "text"), step.get("selector", "")))
        if action == "double_click":
            r = self._find_and_tap(self._resolve_selector(step.get("selector_type", "text"), step.get("selector", "")))
            r["double"] = True
            return r
        if action == "swipe":
            return self.session.swipe(int(step.get("x1", 540)), int(step.get("y1", 1800)),
                                      int(step.get("x2", 540)), int(step.get("y2", 600)),
                                      int(step.get("duration", 300)))
        if action == "wait":
            sel = self._resolve_selector(step.get("selector_type", "text"), step.get("selector", ""))
            timeout = float(step.get("timeout", 5))
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._exists(sel):
                    return {"success": True, "waited": True, "page": self.session.fingerprint()}
                time.sleep(0.3)
            raise StepFailure(f"等待元素超时({timeout}s): {sel}")
        if action == "sleep":
            time.sleep(min(float(step.get("duration", 1)), 10))
            return {"success": True, "page": self.session.fingerprint()}
        if action == "exists":
            sel = self._resolve_selector(step.get("selector_type", "text"), step.get("selector", ""))
            found = self._exists(sel)
            save_to = step.get("save_to")
            if save_to:
                self._set_variable(save_to, found, "local")
            return {"success": True, "exists": found, "save_to": save_to}
        if action == "snapshot":
            name = self.render(step.get("name", f"snapshot_{int(time.time())}"))
            path = os.path.join(self.screenshot_dir, f"{self.device_id}_{name}.png")
            self.session.screenshot(path)
            self.screenshots.append({"name": name, "path": path})
            return {"success": True, "screenshot": path}
        if action == "text":
            r = self.session.input_text(self.render(step.get("text", "")), resource_id=step.get("resource_id", ""))
            if not r.get("success"):
                raise StepFailure(f"输入失败: {r}")
            return r
        if action == "set_variable":
            self._set_variable(step.get("name", ""), self.render(step.get("value", "")), step.get("scope", "local"))
            return {"success": True}
        if action == "unset_variable":
            self.context.get(step.get("scope", "local"), {}).pop(step.get("name"), None)
            return {"success": True}
        if action == "extract_output":
            source = self._get_variable(step.get("source", ""))
            if source is None:
                raise StepFailure(f"来源变量不存在: {step.get('source')}")
            current = source
            for key in self._parse_path(step.get("path", "")):
                if isinstance(current, dict):
                    current = current.get(key)
                elif isinstance(current, (list, tuple)):
                    try:
                        current = current[int(key)]
                    except (ValueError, IndexError):
                        current = None
                else:
                    current = None
                if current is None:
                    raise StepFailure(f"提取失败: 路径 '{step.get('path')}' 在 '{key}' 处找不到值")
            self._set_variable(step.get("name", ""), current, step.get("scope", "local"))
            return {"success": True, "value": current}
        if action == "assert":
            cond = step.get("condition", True)
            if isinstance(cond, str):
                cond = self.render(cond) not in ("", "false", "False", "0", None)
            if not cond:
                raise StepFailure(step.get("message", "断言失败"))
            return {"success": True}
        if action == "back":
            return self.session.back()
        if action == "launch":
            self.session.reset()
            return {"success": True, "page": self.session.fingerprint()}
        raise StepFailure(f"不支持的动作: {action}")

    def _exists(self, sel: Dict[str, Any]) -> bool:
        if sel["type"] == "pos":
            return True
        if sel["type"] in ("id", "resource_id"):
            return self.session.find_control(resource_id=sel["value"]) is not None
        if sel["type"] == "desc":
            return self.session.find_control(content_desc=sel["value"]) is not None
        if sel["type"] == "element_id":
            el = (self.element_map or {}).get(sel["id"])
            if not el:
                return False
            cfg = el.get("config", {})
            return self.session.find_control(resource_id=cfg.get("resource_id", ""), text=cfg.get("text", "")) is not None
        return self.session.find_control(text=sel["value"]) is not None

    @staticmethod
    def _parse_path(path: str) -> List[str]:
        keys = []
        for part in path.split("."):
            if "[" in part:
                base, rest = part.split("[", 1)
                if base:
                    keys.append(base)
                for idx_part in rest.split("["):
                    idx_part = idx_part.rstrip("]")
                    if idx_part:
                        keys.append(idx_part)
            elif part:
                keys.append(part)
        return keys

    # ---------- 主入口 ----------
    def run(self, ui_flow: List[Dict[str, Any]], variables: Optional[List[Dict[str, Any]]] = None,
            runtime: Optional[Dict[str, Any]] = None, element_map: Optional[Dict[str, Any]] = None,
            progress_callback=None) -> Dict[str, Any]:
        if isinstance(ui_flow, dict):
            ui_flow = ui_flow.get("steps", [])
        if not isinstance(ui_flow, list):
            raise ValueError("ui_flow 必须是列表")
        self.element_map = element_map or {}
        self._init_context(variables, runtime)
        mock_device.reset_mock_session(self.device_id)

        total = len(ui_flow)
        passed, failed = 0, 0
        step_results = []
        started = time.time()
        for idx, step in enumerate(ui_flow, 1):
            if self.stop_flag:
                break
            step_name = step.get("name") or step.get("action") or f"step_{idx}"
            if progress_callback:
                progress_callback(idx, total, step_name, "running")
            try:
                detail = self._action(copy.deepcopy(step))
                passed += 1
                step_results.append({"index": idx, "name": step_name, "status": "passed", "detail": self._safe(detail)})
                if progress_callback:
                    progress_callback(idx, total, step_name, "passed")
            except StepFailure as e:
                failed += 1
                step_results.append({"index": idx, "name": step_name, "status": "failed", "detail": str(e)})
                if progress_callback:
                    progress_callback(idx, total, step_name, "failed")
                break
            except Exception as e:  # noqa
                failed += 1
                step_results.append({"index": idx, "name": step_name, "status": "failed", "detail": f"异常: {e}"})
                if progress_callback:
                    progress_callback(idx, total, step_name, "failed")
                break
        duration = round(time.time() - started, 2)
        return {
            "total_steps": total, "passed_steps": passed, "failed_steps": failed,
            "duration": duration, "step_results": step_results,
            "screenshots": self.screenshots,
            "outputs": self.context["outputs"],
            "final_fingerprint": self.session.fingerprint(),
            "stopped": self.stop_flag,
        }

    @staticmethod
    def _safe(detail: Any) -> Any:
        try:
            import json
            return json.loads(json.dumps(detail, ensure_ascii=False, default=str))
        except Exception:
            return str(detail)
