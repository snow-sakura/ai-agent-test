# -*- coding: utf-8 -*-
"""固化正式自动化代码:Appium pytest / uiautomator2 pytest 双模板。"""
import time
from typing import Any, Dict, List, Optional


def _header(template: str, module_name: str) -> str:
    if template == "appium":
        return (
            f'\"\"\"{module_name} - Appium pytest 自动化用例(由 AI Test Hub 控件画像流水线固化生成)\n'
            f'生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\"\"\"\n'
            "import pytest\n"
            "from appium import webdriver\n"
            "from appium.options.android import UiAutomator2Options\n"
            "from appium.webdriver.common.appiumby import AppiumBy\n\n\n"
            "@pytest.fixture(scope='module')\n"
            "def driver():\n"
            "    options = UiAutomator2Options()\n"
            "    options.platform_name = 'Android'\n"
            "    options.device_name = 'emulator-5554'\n"
            "    options.automation_name = 'UiAutomator2'\n"
            "    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)\n"
            "    yield driver\n"
            "    driver.quit()\n\n\n"
        )
    return (
        f'\"\"\"{module_name} - uiautomator2 pytest 自动化用例(由 AI Test Hub 控件画像流水线固化生成)\n'
        f'生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\"\"\"\n'
        "import uiautomator2 as u2\n"
        "import pytest\n\n\n"
        "@pytest.fixture(scope='module')\n"
        "def driver():\n"
        "    d = u2.connect('emulator-5554')\n"
        "    yield d\n\n\n"
    )


def _case_code(template: str, case: Dict[str, Any], locators_by_target: Dict[str, Dict[str, Any]]) -> str:
    cid = case.get("case_id", "CASE")
    title = case.get("title", "")
    lines = [f"def test_{cid.lower().replace('-', '_')}(driver):", f'    \"\"\"{title}\"\"\"']
    for step in case.get("steps", []):
        action = step.get("action")
        target = step.get("target", "")
        value = step.get("value", "")
        loc = locators_by_target.get(target) or locators_by_target.get(target.split(".")[-1]) or {}
        strategy = loc.get("strategy", "text+class")
        expr = loc.get("expression", target)
        note = f"  # locator: {strategy} = {expr}" if loc else "  # 画像中未找到该控件,待补充"
        if action == "tap":
            if template == "appium":
                if strategy == "id":
                    lines.append(f"    driver.find_element(AppiumBy.ID, '{expr}').click(){note}")
                elif strategy == "content-desc":
                    lines.append(f"    driver.find_element(AppiumBy.ACCESSIBILITY_ID, '{expr}').click(){note}")
                else:
                    text = expr.split('text="')[-1].split('"')[0] if 'text="' in expr else expr
                    lines.append(f"    driver.find_element(AppiumBy.XPATH, f'//*[@text=\"{text}\"]').click(){note}")
            else:
                if strategy == "id":
                    lines.append(f"    driver(resourceId='{expr}').click(){note}")
                elif strategy == "content-desc":
                    lines.append(f"    driver(description='{expr}').click(){note}")
                else:
                    text = expr.split('text="')[-1].split('"')[0] if 'text="' in expr else expr
                    lines.append(f"    driver(text='{text}').click(){note}")
        elif action in ("input", "input_text"):
            if template == "appium":
                lines.append(f"    el = driver.find_element(AppiumBy.XPATH, '//*[@class=\"android.widget.EditText\"]')  # 输入框(按画像)")
                lines.append(f"    el.clear(); el.send_keys('{value}'){note}")
            else:
                lines.append(f"    driver(className='android.widget.EditText').clear_text(){note}")
                lines.append(f"    driver(className='android.widget.EditText').send_keys('{value}')")
        elif action == "swipe":
            if template == "appium":
                lines.append(f"    driver.swipe(540, 1800, 540, 600, 300)  # 上滑")
            else:
                lines.append(f"    driver.swipe(0.5, 0.75, 0.5, 0.25)  # 上滑")
        elif action == "assert":
            if template == "appium":
                lines.append("    assert driver.current_package, '应用应在前台'  # 页面指纹断言")
            else:
                lines.append("    assert driver.info.get('currentPackage'), '应用应在前台'  # 页面指纹断言")
    lines.append("")
    return "\n".join(lines)


def generate_code(template: str, module_name: str, cases: List[Dict[str, Any]],
                  locators: List[Dict[str, Any]]) -> str:
    """template: appium | u2"""
    locators_by_target = {}
    for loc in locators:
        if loc.get("selected"):
            locators_by_target[loc["control_id"]] = loc["selected"]
            locators_by_target[loc["control_id"].split(".")[-1]] = loc["selected"]
    code = _header(template, module_name)
    for case in cases:
        code += _case_code(template, case, locators_by_target) + "\n\n"
    return code
