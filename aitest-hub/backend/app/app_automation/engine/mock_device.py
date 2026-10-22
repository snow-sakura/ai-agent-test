# -*- coding: utf-8 -*-
"""模拟 Android 设备 —— 无真机时提供完整可演示的设备能力。

实现:
- 页面状态机(多个业务页面,点击/输入/返回可驱动跳转)
- uiautomator 格式 XML dump(与真机 dump_hierarchy 一致)
- PIL 生成模拟截图
- 页面指纹(package/activity/控件哈希)
- 定位器解析与点击验证(resource-id / text / content-desc / 组合)
"""
import hashlib
import os
import random
import re
import threading
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

UPLOAD_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads", "app-automation"))
SCREENSHOT_DIR = os.path.join(UPLOAD_BASE, "screenshots")
TEMPLATE_DIR = os.path.join(UPLOAD_BASE, "elements")
DUMP_DIR = os.path.join(UPLOAD_BASE, "dumps")

MOCK_APP_PACKAGE = "com.testhub.demoapp"

# ============ 模拟 APP 的页面与控件定义 ============
# bounds 格式与 uiautomator 一致: [x1,y1][x2,y2]
MOCK_PAGES: Dict[str, Dict[str, Any]] = {
    "home": {
        "activity": "com.testhub.demoapp.MainActivity",
        "title": "AI Demo 应用",
        "background": "#3F51B5",
        "controls": [
            {"resource_id": "com.testhub.demoapp:id/toolbar_title", "text": "AI Demo 应用", "class": "android.widget.TextView", "bounds": "[96,64][984,140]", "clickable": False, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/btn_add_friend", "text": "添加好友", "class": "android.widget.Button", "bounds": "[96,240][984,338]", "clickable": True, "enabled": True, "content_desc": "打开添加好友页面"},
            {"resource_id": "com.testhub.demoapp:id/btn_contacts", "text": "通讯录", "class": "android.widget.Button", "bounds": "[96,378][984,476]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/btn_settings", "text": "设置", "class": "android.widget.Button", "bounds": "[96,516][984,614]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "", "text": "", "class": "android.widget.ImageView", "bounds": "[880,64][984,140]", "clickable": True, "enabled": True, "content_desc": "扫一扫"},
        ],
        "transitions": {
            "com.testhub.demoapp:id/btn_add_friend": "add_friend",
            "com.testhub.demoapp:id/btn_contacts": "contacts",
            "com.testhub.demoapp:id/btn_settings": "settings",
            "desc:扫一扫": "scan",
        },
    },
    "add_friend": {
        "activity": "com.testhub.demoapp.AddFriendActivity",
        "title": "添加好友",
        "background": "#009688",
        "controls": [
            {"resource_id": "com.testhub.demoapp:id/back", "text": "", "class": "android.widget.ImageView", "bounds": "[24,40][104,120]", "clickable": True, "enabled": True, "content_desc": "返回"},
            {"resource_id": "com.testhub.demoapp:id/search_container", "text": "", "class": "android.widget.LinearLayout", "bounds": "[96,240][984,338]", "clickable": False, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/search_input", "text": "搜索", "class": "android.widget.EditText", "bounds": "[96,240][780,338]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/search_button", "text": "搜索好友", "class": "android.widget.Button", "bounds": "[796,240][984,338]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "", "text": "", "class": "android.widget.ImageView", "bounds": "[120,420][240,540]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/scan_button", "text": "扫一扫添加", "class": "android.widget.TextView", "bounds": "[260,440][500,520]", "clickable": True, "enabled": True, "content_desc": ""},
        ],
        "transitions": {
            "com.testhub.demoapp:id/back": "__back__",
            "com.testhub.demoapp:id/search_button": "add_friend_search_result",
            "com.testhub.demoapp:id/scan_button": "scan",
        },
    },
    "contacts": {
        "activity": "com.testhub.demoapp.ContactsActivity",
        "title": "通讯录",
        "background": "#673AB7",
        "controls": [
            {"resource_id": "com.testhub.demoapp:id/back", "text": "", "class": "android.widget.ImageView", "bounds": "[24,40][104,120]", "clickable": True, "enabled": True, "content_desc": "返回"},
            {"resource_id": "com.testhub.demoapp:id/contact_item_1", "text": "张三\\n在线 | 今天天气不错", "class": "android.widget.LinearLayout", "bounds": "[96,220][984,340]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/contact_item_2", "text": "李四\\n忙碌中", "class": "android.widget.LinearLayout", "bounds": "[96,360][984,480]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "", "text": "", "class": "android.widget.ImageView", "bounds": "[900,560][984,644]", "clickable": True, "enabled": True, "content_desc": ""},
        ],
        "transitions": {
            "com.testhub.demoapp:id/back": "__back__",
            "com.testhub.demoapp:id/contact_item_1": "chat",
            "com.testhub.demoapp:id/contact_item_2": "chat",
        },
    },
    "chat": {
        "activity": "com.testhub.demoapp.ChatActivity",
        "title": "聊天",
        "background": "#607D8B",
        "controls": [
            {"resource_id": "com.testhub.demoapp:id/back", "text": "", "class": "android.widget.ImageView", "bounds": "[24,40][104,120]", "clickable": True, "enabled": True, "content_desc": "返回"},
            {"resource_id": "com.testhub.demoapp:id/chat_input", "text": "输入消息", "class": "android.widget.EditText", "bounds": "[96,560][780,644]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/send_button", "text": "发送", "class": "android.widget.Button", "bounds": "[796,560][984,644]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/chat_bubble", "text": "你好!", "class": "android.widget.TextView", "bounds": "[96,220][500,300]", "clickable": False, "enabled": True, "content_desc": ""},
        ],
        "transitions": {"com.testhub.demoapp:id/back": "__back__"},
    },
}

MOCK_PAGES.update({
    "settings": {
        "activity": "com.testhub.demoapp.SettingsActivity",
        "title": "设置",
        "background": "#795548",
        "controls": [
            {"resource_id": "com.testhub.demoapp:id/back", "text": "", "class": "android.widget.ImageView", "bounds": "[24,40][104,120]", "clickable": True, "enabled": True, "content_desc": "返回"},
            {"resource_id": "com.testhub.demoapp:id/switch_dark_mode", "text": "", "class": "android.widget.Switch", "bounds": "[780,220][984,300]", "clickable": True, "enabled": True, "content_desc": "深色模式"},
            {"resource_id": "com.testhub.demoapp:id/tv_version", "text": "版本 1.0.0", "class": "android.widget.TextView", "bounds": "[96,700][400,780]", "clickable": False, "enabled": True, "content_desc": ""},
        ],
        "transitions": {"com.testhub.demoapp:id/back": "__back__"},
    },
    "add_friend_search_result": {
        "activity": "com.testhub.demoapp.SearchResultActivity",
        "title": "搜索结果",
        "background": "#009688",
        "controls": [
            {"resource_id": "com.testhub.demoapp:id/back", "text": "", "class": "android.widget.ImageView", "bounds": "[24,40][104,120]", "clickable": True, "enabled": True, "content_desc": "返回"},
            {"resource_id": "com.testhub.demoapp:id/result_item", "text": "王五 (ID: 10086)\\n添加好友", "class": "android.widget.LinearLayout", "bounds": "[96,220][984,380]", "clickable": True, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/add_button", "text": "添加", "class": "android.widget.Button", "bounds": "[796,240][984,340]", "clickable": True, "enabled": True, "content_desc": ""},
        ],
        "transitions": {
            "com.testhub.demoapp:id/back": "__back__",
            "com.testhub.demoapp:id/add_button": "add_friend_done",
        },
    },
    "add_friend_done": {
        "activity": "com.testhub.demoapp.AddFriendDoneActivity",
        "title": "好友请求已发送",
        "background": "#4CAF50",
        "controls": [
            {"resource_id": "com.testhub.demoapp:id/done_title", "text": "好友请求已发送", "class": "android.widget.TextView", "bounds": "[96,220][984,300]", "clickable": False, "enabled": True, "content_desc": ""},
            {"resource_id": "com.testhub.demoapp:id/btn_back_home", "text": "回到首页", "class": "android.widget.Button", "bounds": "[96,400][984,500]", "clickable": True, "enabled": True, "content_desc": ""},
        ],
        "transitions": {"com.testhub.demoapp:id/btn_back_home": "home"},
    },
    "scan": {
        "activity": "com.testhub.demoapp.ScanActivity",
        "title": "扫一扫",
        "background": "#212121",
        "controls": [
            {"resource_id": "com.testhub.demoapp:id/back", "text": "", "class": "android.widget.ImageView", "bounds": "[24,40][104,120]", "clickable": True, "enabled": True, "content_desc": "返回"},
            {"resource_id": "", "text": "", "class": "android.view.View", "bounds": "[240,300][840,900]", "clickable": False, "enabled": True, "content_desc": ""},
        ],
        "transitions": {"com.testhub.demoapp:id/back": "__back__"},
    },
})

_HOME_PAGE = "home"


class MockDeviceSession:
    """一个模拟设备的运行时状态(每个 device_id 一个实例)"""

    def __init__(self, device_id: str, screen: Tuple[int, int] = (1080, 2400)):
        self.device_id = device_id
        self.screen = screen
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.page: str = _HOME_PAGE
        self.page_stack: List[str] = []
        self.input_texts: Dict[str, str] = {}
        self.clipboard: str = ""
        self.variables: Dict[str, Any] = {}
        self.last_tap: Optional[Dict[str, Any]] = None
        self.switch_state: Dict[str, bool] = {}

    # ---------- XML dump ----------
    def _control_xml(self, c: Dict[str, Any], depth: int) -> str:
        pad = "  " * depth
        rid = c.get("resource_id", "")
        node_id = rid.replace("com.testhub.demoapp:id/", "id/") if rid else f"mock_{hashlib.md5(c['bounds'].encode()).hexdigest()[:8]}"
        attrs = (
            f'text="{escape(c.get("text", ""))}" resource-id="{rid}"'
            f' class="{c.get("class", "")}" package="{MOCK_APP_PACKAGE}"'
            f' content-desc="{escape(c.get("content_desc", ""))}"'
            f' checkable="false" checked="false" clickable="{str(c.get("clickable", False)).lower()}"'
            f' enabled="{str(c.get("enabled", True)).lower()}" focusable="false" scrollable="false"'
            f' long-clickable="false" password="false" selected="false" bounds="{c["bounds"]}"'
        )
        inner = ""
        t = c.get("text", "")
        if t and "\\n" in t:
            first, second = t.split("\\n", 1)
            inner = (
                f'\n{pad}  <node index="0" text="{escape(first)}" resource-id="" class="android.widget.TextView"'
                f' package="{MOCK_APP_PACKAGE}" content-desc="" checkable="false" checked="false"'
                f' clickable="false" enabled="true" focusable="false" scrollable="false"'
                f' long-clickable="false" password="false" selected="false" bounds="{c['bounds']}"/>\n'
                f'{pad}  <node index="1" text="{escape(second)}" resource-id="" class="android.widget.TextView"'
                f' package="{MOCK_APP_PACKAGE}" content-desc="" checkable="false" checked="false"'
                f' clickable="false" enabled="true" focusable="false" scrollable="false"'
                f' long-clickable="false" password="false" selected="false" bounds="{c['bounds']}"/>\n{pad}'
            )
        return f'{pad}<node node-id="{node_id}" {attrs}>{inner}</node>'

    def dump_xml(self) -> str:
        page = MOCK_PAGES[self.page]
        nodes = "\n".join(self._control_xml(c, 2) for c in page["controls"])
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
            '<hierarchy rotation="0">\n'
            f'  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"'
            f' package="{MOCK_APP_PACKAGE}" content-desc="" checkable="false" checked="false" clickable="false"'
            f' enabled="true" focusable="false" scrollable="false" long-clickable="false" password="false"'
            f' selected="false" bounds="[0,0][{self.screen[0]},{self.screen[1]}]">\n{nodes}\n  </node>\n</hierarchy>'
        )

    # ---------- 指纹 ----------
    def fingerprint(self) -> Dict[str, Any]:
        page = MOCK_PAGES[self.page]
        ctrl_hash = hashlib.md5(
            repr([(c["resource_id"], c["text"], c["bounds"]) for c in page["controls"]]).encode()
        ).hexdigest()[:16]
        return {
            "package": MOCK_APP_PACKAGE,
            "activity": page["activity"],
            "page": self.page,
            "title": page["title"],
            "control_hash": ctrl_hash,
        }

    # ---------- 控件解析 ----------
    def _bounds_center(self, bounds: str) -> Tuple[int, int]:
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m:
            return (self.screen[0] // 2, self.screen[1] // 2)
        x1, y1, x2, y2 = map(int, m.groups())
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def find_control(self, resource_id: str = "", text: str = "", content_desc: str = "",
                     partial: bool = True) -> Optional[Dict[str, Any]]:
        page = MOCK_PAGES[self.page]
        for c in page["controls"]:
            if resource_id and c.get("resource_id") == resource_id:
                return c
            if text and partial and text in (c.get("text", "") or ""):
                return c
            if text and not partial and c.get("text") == text:
                return c
            if content_desc and c.get("content_desc", "") == content_desc:
                return c
        return None

    # ---------- 交互动作 ----------
    def tap(self, x: int, y: int) -> Dict[str, Any]:
        """点击坐标:命中控件则触发跳转/记录,返回命中详情"""
        page = MOCK_PAGES[self.page]
        m = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
        hit = None
        first_hit = None
        clickable_hits = []
        for c in page["controls"]:
            b = m.match(c["bounds"])
            if not b:
                continue
            x1, y1, x2, y2 = map(int, b.groups())
            if x1 <= x <= x2 and y1 <= y <= y2:
                if first_hit is None:
                    first_hit = c
                if c.get("clickable"):
                    clickable_hits.append(((x2 - x1) * (y2 - y1), c))
        if clickable_hits:
            # 重叠时优先命中可点击控件中面积最小者(最上层交互元素)
            hit = min(clickable_hits, key=lambda t: t[0])[1]
        if hit is None:
            hit = first_hit
        before = self.fingerprint()
        transition_target = None
        if hit and hit.get("clickable"):
            rid = hit.get("resource_id", "")
            desc = hit.get("content_desc", "")
            key = None
            if rid and rid in page.get("transitions", {}):
                key = rid
            elif desc and f"desc:{desc}" in page.get("transitions", {}):
                key = f"desc:{desc}"
            if key:
                target = page["transitions"][key]
                if target == "__back__":
                    self.page = self.page_stack.pop() if self.page_stack else _HOME_PAGE
                else:
                    self.page_stack.append(self.page)
                    self.page = target
            transition_target = key or hit.get("resource_id") or hit.get("content_desc")
        self.last_tap = {"x": x, "y": y, "hit_resource_id": (hit or {}).get("resource_id", ""),
                         "hit_content_desc": (hit or {}).get("content_desc", ""),
                         "transition": transition_target,
                         "before": before, "after": self.fingerprint()}
        return self.last_tap

    def tap_control(self, resource_id: str = "", text: str = "", content_desc: str = "") -> Dict[str, Any]:
        c = self.find_control(resource_id, text, content_desc)
        if not c:
            return {"success": False, "error": "NoSuchControl", "page": self.page,
                    "detail": f"page={self.page} resource_id={resource_id!r} text={text!r} content_desc={content_desc!r}"}
        x, y = self._bounds_center(c["bounds"])
        result = self.tap(x, y)
        result["success"] = True
        result["control"] = c
        return result

    def input_text(self, text: str, resource_id: str = "") -> Dict[str, Any]:
        page = MOCK_PAGES[self.page]
        target = None
        for c in page["controls"]:
            if "EditText" in (c.get("class") or ""):
                target = c
                if resource_id and c.get("resource_id") == resource_id:
                    break
        if not target:
            return {"success": False, "error": "NoEditableControl", "page": self.page}
        merged = self.input_texts.get(target["resource_id"], "") + text
        self.input_texts[target["resource_id"]] = merged
        target["text"] = merged
        return {"success": True, "control": target["resource_id"], "value": merged}

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> Dict[str, Any]:
        return {"success": True, "swipe": [x1, y1, x2, y2], "duration": duration, "after": self.fingerprint()}

    def back(self) -> Dict[str, Any]:
        self.page = self.page_stack.pop() if self.page_stack else _HOME_PAGE
        return {"success": True, "after": self.fingerprint()}

    # ---------- 截图 ----------
    def screenshot(self, save_path: Optional[str] = None) -> str:
        os.makedirs(os.path.dirname(save_path or SCREENSHOT_DIR), exist_ok=True)
        path = save_path or os.path.join(SCREENSHOT_DIR, f"{self.device_id}_{random.randint(0, 999999)}.png")
        page = MOCK_PAGES[self.page]
        w, h = 540, 1140  # 缩略渲染尺寸
        scale = w / self.screen[0]
        img = Image.new("RGB", (w, h), page.get("background", "#333"))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, w, int(150 * scale * 0.9)], fill="#1a1a1a")
        draw.text((16, 10), page.get("title", ""), fill="white")
        draw.text((16, 30), f"[mock] {self.device_id} @ {self.page}", fill="#9ad")
        bounds_re = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
        for c in page["controls"]:
            b = bounds_re.match(c["bounds"])
            if not b:
                continue
            x1, y1, x2, y2 = [int(int(v) * scale) for v in b.groups()]
            clickable = c.get("clickable")
            if "EditText" in (c.get("class") or ""):
                fill = "#ffffff"
            elif c.get("class") == "android.widget.Button":
                fill = "#ffb74d" if clickable else "#999"
            else:
                fill = "#81c784" if clickable else "#cfd8dc"
            draw.rectangle([x1, y1, x2, y2], fill=fill, outline="#111" if clickable else "#666")
            label = (c.get("text") or c.get("content_desc") or c.get("resource_id", "").split("/")[-1] or c["class"].split(".")[-1])[:14]
            if label:
                draw.text((x1 + 4, y1 + 4), label, fill="black")
        if any("EditText" in (c.get("class") or "") and c.get("text") for c in page["controls"]):
            draw.text((16, h - 30), "[键盘弹起]", fill="yellow")
        img.save(path)
        return path


# ============ 会话管理 ============

_sessions: Dict[str, MockDeviceSession] = {}
_sessions_lock = threading.Lock()


def get_mock_session(device_id: str) -> MockDeviceSession:
    with _sessions_lock:
        if device_id not in _sessions:
            _sessions[device_id] = MockDeviceSession(device_id)
        return _sessions[device_id]


def reset_mock_session(device_id: str):
    with _sessions_lock:
        session = _sessions.get(device_id)
        if session:
            session.reset()
