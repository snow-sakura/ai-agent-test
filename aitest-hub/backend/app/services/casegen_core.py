"""用例生成核心（共享）：提示词、消息构建、演示兜底。

main.py 的 SSE 单条生成与 gen_queue 序列调度共用，保证两个入口的
提示词/参数/兜底行为完全一致（单一事实源）。
"""

from typing import Any, Dict, List, Optional

TC_CASE_GEN_PROMPT = """你是资深测试工程师。根据用户给出的需求,运用等价类划分、边界值分析、场景法、错误推测等测试设计方法,生成结构化测试用例。

严格只输出一个 JSON 对象,不要任何解释文字或 Markdown 代码块,格式如下:
{"summary": "一句话概述本次设计思路与覆盖策略", "cases": [{"module": "所属模块", "name": "用例名称", "priority": "P0|P1|P2|P3", "type": "功能|边界|异常|性能", "precondition": "前置条件", "steps": "步骤1\\n步骤2\\n步骤3", "expected": "预期结果"}]}

要求:
1. 覆盖正常流程、边界值、异常/非法输入、权限与并发等维度;数量 8~20 条,按优先级排序
2. steps 为可执行的分步描述,每步一行;expected 给出可判定、可观测的结果
3. 用例名称包含操作与验证点,避免「测试XX」这类空泛命名"""

_TEST_HINTS = {
    "functional": "以功能测试为主",
    "boundary": "侧重边界值分析",
    "exception": "侧重异常场景与容错",
    "comprehensive": "综合运用各类设计方法",
}

_PLATFORM_HINTS = {
    "web": "Web 端",
    "api": "API 接口",
    "app": "移动 App 端",
}


def build_messages(
    requirement: str,
    *,
    project_type: str = "web",
    test_type: str = "functional",
    system_prompt: Optional[str] = None,
) -> List[Dict[str, str]]:
    """统一构建用例生成的 messages（单条与序列共用）。"""
    test_hint = _TEST_HINTS.get(test_type, "")
    platform_hint = _PLATFORM_HINTS.get(project_type, "")
    user_content = (
        f"被测对象:{platform_hint or '通用'};测试设计:{test_hint or '常规'}\n\n"
        f"需求描述:\n{(requirement or '').strip()[:6000]}"
    )
    return [
        {"role": "system", "content": system_prompt or TC_CASE_GEN_PROMPT},
        {"role": "user", "content": user_content},
    ]


def demo_generated_cases(requirement: str) -> Dict[str, Any]:
    """无 Key / 解析失败时的演示用例集（保证演示环境闭环可用）。"""
    subject = (
        (requirement or "").strip().splitlines()[0][:20]
        if (requirement or "").strip()
        else "被测功能"
    )
    rows = [
        (
            "P0",
            "功能",
            "主流程冒烟",
            "需求已评审、测试环境就绪",
            "1. 打开入口\n2. 按主流程操作\n3. 提交并观察结果",
            "主流程成功，关键数据正确落库",
        ),
        (
            "P0",
            "边界",
            "输入边界校验",
            "表单可用",
            "1. 输入长度为 0/1/最大值的文本\n2. 提交表单",
            "超界被拒绝并提示，合法值可提交",
        ),
        (
            "P1",
            "异常",
            "非法输入容错",
            "表单可用",
            "1. 输入特殊字符/脚本片段\n2. 提交表单",
            "输入被过滤或拒绝，无 500 错误",
        ),
        (
            "P1",
            "功能",
            "重复提交防抖",
            "同一账号已发起请求",
            "1. 连续快速点击提交\n2. 观察结果",
            "仅生成一条记录，重复请求被拦截",
        ),
        (
            "P1",
            "功能",
            "权限校验",
            "普通用户已登录",
            "1. 以普通用户访问受限入口\n2. 执行操作",
            "返回 403 并提示无权限",
        ),
        (
            "P2",
            "异常",
            "后端异常降级",
            "模拟接口超时/500",
            "1. 触发异常场景\n2. 观察前端表现",
            "前端展示友好错误提示，不白屏",
        ),
        (
            "P2",
            "性能",
            "关键接口响应",
            "并发 50 用户",
            "1. 并发发起关键请求\n2. 统计响应时间",
            "P95 响应时间 ≤ 2s",
        ),
        (
            "P2",
            "功能",
            "数据一致性",
            "操作成功后",
            "1. 执行增删改操作\n2. 刷新页面核对列表",
            "列表与详情数据一致，无脏数据",
        ),
    ]
    cases = [
        {
            "module": subject,
            "name": "%s·%s" % (subject, name),
            "priority": pri,
            "type": typ,
            "precondition": pre,
            "steps": steps,
            "expected": exp,
        }
        for pri, typ, name, pre, steps, exp in rows
    ]
    return {
        "summary": "已按等价类/边界值/异常场景/权限/并发维度生成 %d 条演示用例（当前为统一 AI 服务 mock 输出）"
        % len(cases),
        "cases": cases,
    }
