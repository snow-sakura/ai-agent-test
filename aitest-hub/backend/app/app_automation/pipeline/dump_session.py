# -*- coding: utf-8 -*-
"""UI Dump 采集编排:页面遍历 → XML + 截图 + 页面指纹采集。"""
import os
import time
from typing import Any, Dict, List, Optional

from app.app_automation.engine import mock_device

# 模拟 APP 的页面遍历路径(默认: 添加好友业务全链路)
DEFAULT_TRAVERSAL = ["home", "add_friend", "add_friend_search_result", "contacts", "chat", "settings", "scan"]

# 页面间跳转动作(用于 action_context 记录)
PAGE_ENTRY_ACTIONS = {
    "home": {"action": "launch", "note": "应用启动首页"},
    "add_friend": {"action": "tap", "target": "com.testhub.demoapp:id/btn_add_friend", "note": "首页点击添加好友"},
    "add_friend_search_result": {"action": "tap", "target": "com.testhub.demoapp:id/search_button", "note": "添加好友页点击搜索"},
    "contacts": {"action": "tap", "target": "com.testhub.demoapp:id/btn_contacts", "note": "首页点击通讯录"},
    "chat": {"action": "tap", "target": "com.testhub.demoapp:id/contact_item_1", "note": "通讯录点击好友"},
    "settings": {"action": "tap", "target": "com.testhub.demoapp:id/btn_settings", "note": "首页点击设置"},
    "scan": {"action": "tap", "target": "desc:扫一扫", "note": "点击扫一扫图标(视觉缺口控件)"},
}


class DumpSessionRunner:
    """一次采集会话的执行器(模拟设备);真机使用 uiautomator2 dump_hierarchy 的逻辑一致。"""

    def __init__(self, device_id: str, pages: List[str], package_name: str = mock_device.MOCK_APP_PACKAGE,
                 is_mock: bool = True):
        self.device_id = device_id
        self.pages = pages or DEFAULT_TRAVERSAL
        self.package_name = package_name
        self.is_mock = is_mock
        self.session = mock_device.get_mock_session(device_id)

    def run(self, progress_callback=None) -> List[Dict[str, Any]]:
        """顺序遍历页面,采集 XML/截图/指纹,返回每页采集结果"""
        results = []
        os.makedirs(mock_device.DUMP_DIR, exist_ok=True)
        ts = int(time.time())
        session = mock_device.get_mock_session(self.device_id)
        session.reset()
        for i, page in enumerate(self.pages, 1):
            action_ctx = PAGE_ENTRY_ACTIONS.get(page, {"action": "navigate", "note": "直接导航"})
            # 通过动作导航到目标页(模拟页面遍历)
            self._navigate_to(page)
            page_def = mock_device.MOCK_PAGES[session.page]
            xml = session.dump_xml()
            screenshot_path = os.path.join(mock_device.DUMP_DIR, f"{self.device_id}_{page}_{ts}.png")
            session.screenshot(screenshot_path)
            fingerprint = session.fingerprint()
            result = {
                "page_name": page,
                "actual_page": session.page,
                "xml": xml,
                "screenshot_path": screenshot_path,
                "fingerprint": fingerprint,
                "action_context": action_ctx,
                "title": page_def.get("title", ""),
            }
            results.append(result)
            if progress_callback:
                progress_callback(i, len(self.pages), page)
        return results

    def _navigate_to(self, page: str):
        """从当前页导航到目标页(走状态机真实路径,而不是直接赋值,保证 XML 与指纹来自真实遍历)"""
        session = self.session
        if session.page == page:
            return
        # 简单策略: 先回到 home,再走 transition
        while session.page_stack:
            session.back()
        if session.page != "home":
            session.reset()
        transition = None
        home_def = mock_device.MOCK_PAGES.get("home", {})
        for rid, target in home_def.get("transitions", {}).items():
            if target == page:
                transition = rid
                break
        if transition:
            if transition.startswith("desc:"):
                session.tap_control(content_desc=transition[5:])
            else:
                session.tap_control(resource_id=transition)
        elif page == "add_friend_search_result":
            session.tap_control(resource_id="com.testhub.demoapp:id/btn_add_friend")
            session.tap_control(resource_id="com.testhub.demoapp:id/search_button")
        elif page == "chat":
            session.tap_control(resource_id="com.testhub.demoapp:id/btn_contacts")
            session.tap_control(resource_id="com.testhub.demoapp:id/contact_item_1")
        else:
            # 兜底: 直接赋值(模拟系统导航)
            session.page_stack.append(session.page)
            session.page = page
