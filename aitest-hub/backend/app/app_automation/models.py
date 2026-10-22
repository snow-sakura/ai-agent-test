# -*- coding: utf-8 -*-
"""APP自动化模块数据模型(复刻 testhub_platform 全部模型 + 控件画像流水线新增模型)"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    UniqueConstraint,
    Index,
)

from app.core.database import Base


def _now():
    return datetime.utcnow()


# ============ 常量 ============

class DeviceStatus:
    AVAILABLE = "available"
    LOCKED = "locked"
    OFFLINE = "offline"
    ONLINE = "online"


class ExecutionStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    STOPPED = "stopped"


class ExecutionResult:
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ElementType:
    IMAGE = "image"
    POS = "pos"
    REGION = "region"


# ============ 复刻:项目 / 配置 ============

class AppProject(Base):
    """APP自动化测试项目"""
    __tablename__ = "app_projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, default="")
    description = Column(Text, default="")
    status = Column(String(20), default="IN_PROGRESS")
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppTestConfig(Base):
    """APP自动化测试配置(ADB路径 / 模拟设备模式)"""
    __tablename__ = "app_test_config"

    id = Column(Integer, primary_key=True, index=True)
    adb_path = Column(String(500), default="adb")
    mock_mode = Column(Boolean, default=True)  # 暂无真机时启用模拟设备
    mock_device_count = Column(Integer, default=2)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppDevice(Base):
    """Android 设备(支持真机 / 模拟器 / 模拟设备)"""
    __tablename__ = "app_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), default="")
    status = Column(String(20), default=DeviceStatus.OFFLINE)
    android_version = Column(String(50), default="")
    connection_type = Column(String(20), default="emulator")
    ip_address = Column(String(50), default="")
    port = Column(Integer, default=5555)
    locked_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    max_allocation_time = Column(Integer, default=28800)
    device_specs = Column(JSON, default=dict)
    description = Column(Text, default="")
    location = Column(String(200), default="")
    is_mock = Column(Boolean, default=False)  # 模拟设备标记
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppElement(Base):
    """APP UI 元素(image/pos/region 三类)"""
    __tablename__ = "app_elements"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("app_projects.id"), nullable=True)
    name = Column(String(200), unique=True, nullable=False)
    element_type = Column(String(10), default=ElementType.IMAGE)
    tags = Column(JSON, default=list)
    config = Column(JSON, default=dict)
    resolution_configs = Column(JSON, default=dict)
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    is_active = Column(Boolean, default=True)


class AppComponent(Base):
    """APP 基础组件定义"""
    __tablename__ = "app_components"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, default="")
    type = Column(String(50), default="click")
    description = Column(Text, default="")
    config = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppCustomComponent(Base):
    """APP 自定义组件"""
    __tablename__ = "app_custom_components"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, default="")
    type = Column(String(50), default="composite")
    description = Column(Text, default="")
    schema = Column("schema", JSON, default=dict)
    default_config = Column(JSON, default=dict)
    steps = Column(JSON, default=list)
    enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppComponentPackage(Base):
    """APP UI 组件包(导入/安装组件定义)"""
    __tablename__ = "app_component_packages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, default="")
    version = Column(String(50), default="")
    description = Column(Text, default="")
    author = Column(String(100), default="")
    source = Column(String(20), default="upload")
    manifest = Column(JSON, default=dict)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppPackage(Base):
    """应用包名管理"""
    __tablename__ = "app_packages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, default="")
    package_name = Column(String(255), unique=True, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppTestCase(Base):
    """APP 测试用例(ui_flow JSON 编排)"""
    __tablename__ = "app_test_cases"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("app_projects.id"), nullable=True)
    name = Column(String(200), nullable=False, default="")
    description = Column(Text, default="")
    app_package_id = Column(Integer, ForeignKey("app_packages.id"), nullable=True)
    ui_flow = Column(JSON, default=dict)
    variables = Column(JSON, default=list)
    timeout = Column(Integer, default=300)
    retry_count = Column(Integer, default=0)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppTestSuite(Base):
    """APP 测试套件"""
    __tablename__ = "app_test_suites"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("app_projects.id"), nullable=True)
    name = Column(String(200), nullable=False, default="")
    description = Column(Text, default="")
    execution_status = Column(String(20), default="not_run")
    execution_result = Column(String(20), nullable=True)
    passed_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    last_run_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppTestSuiteCase(Base):
    """套件-用例关联"""
    __tablename__ = "app_test_suite_cases"
    __table_args__ = (UniqueConstraint("test_suite_id", "test_case_id", name="uq_suite_case"),)

    id = Column(Integer, primary_key=True, index=True)
    test_suite_id = Column(Integer, ForeignKey("app_test_suites.id"), nullable=False)
    test_case_id = Column(Integer, ForeignKey("app_test_cases.id"), nullable=False)
    order = Column(Integer, default=0)


class AppTestExecution(Base):
    """APP 测试执行记录"""
    __tablename__ = "app_test_executions"
    __table_args__ = (Index("idx_app_exec_status", "status"),)

    id = Column(Integer, primary_key=True, index=True)
    execution_type = Column(String(10), default="case")  # case / suite
    test_case_id = Column(Integer, ForeignKey("app_test_cases.id"), nullable=True)
    test_suite_id = Column(Integer, ForeignKey("app_test_suites.id"), nullable=True)
    device_db_id = Column(Integer, ForeignKey("app_devices.id"), nullable=True)
    device_id = Column(String(255), default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default=ExecutionStatus.PENDING)
    result = Column(String(20), nullable=True)
    task_id = Column(String(255), default="")
    progress = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration = Column(Float, default=0)
    report_path = Column(String(500), default="")
    error_message = Column(Text, default="")
    total_steps = Column(Integer, default=0)
    passed_steps = Column(Integer, default=0)
    failed_steps = Column(Integer, default=0)
    current_step = Column(String(200), default="")
    logs = Column(JSON, default=list)
    case_name = Column(String(200), default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppScheduledTask(Base):
    """APP 定时任务"""
    __tablename__ = "app_scheduled_tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("app_projects.id"), nullable=True)
    name = Column(String(200), nullable=False, default="")
    description = Column(Text, default="")
    task_type = Column(String(20), default="TEST_CASE")  # TEST_SUITE / TEST_CASE
    trigger_type = Column(String(20), default="CRON")  # CRON / INTERVAL / ONCE
    cron_expression = Column(String(100), default="")
    interval_seconds = Column(Integer, nullable=True)
    execute_at = Column(DateTime, nullable=True)
    device_db_id = Column(Integer, ForeignKey("app_devices.id"), nullable=True)
    app_package_id = Column(Integer, ForeignKey("app_packages.id"), nullable=True)
    test_suite_id = Column(Integer, ForeignKey("app_test_suites.id"), nullable=True)
    test_case_id = Column(Integer, ForeignKey("app_test_cases.id"), nullable=True)
    notify_on_success = Column(Boolean, default=False)
    notify_on_failure = Column(Boolean, default=False)
    notification_type = Column(String(20), default="")  # email / webhook / both
    notify_emails = Column(JSON, default=list)
    status = Column(String(20), default="ACTIVE")
    last_run_time = Column(DateTime, nullable=True)
    next_run_time = Column(DateTime, nullable=True)
    total_runs = Column(Integer, default=0)
    successful_runs = Column(Integer, default=0)
    failed_runs = Column(Integer, default=0)
    last_result = Column(JSON, default=dict)
    error_message = Column(Text, default="")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppNotificationLog(Base):
    """APP 自动化通知日志"""
    __tablename__ = "app_notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("app_scheduled_tasks.id"), nullable=True)
    task_name = Column(String(200), default="")
    task_type = Column(String(20), default="")
    notification_type = Column(String(50), default="task_execution")
    sender_name = Column(String(100), default="AI Test Hub")
    sender_email = Column(String(200), default="noreply@testhub.local")
    recipient_info = Column(JSON, default=list)
    webhook_bot_info = Column(JSON, default=dict)
    notification_content = Column(Text, default="")
    status = Column(String(20), default="pending")
    error_message = Column(Text, default="")
    response_info = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now)
    sent_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
    is_retried = Column(Boolean, default=False)


# ============ 新增:控件画像流水线 ============

class AppDumpSession(Base):
    """UI Dump 采集会话(页面遍历)"""
    __tablename__ = "app_dump_sessions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), default="")
    device_db_id = Column(Integer, ForeignKey("app_devices.id"), nullable=True)
    package_name = Column(String(255), default="")
    status = Column(String(20), default="pending")  # pending/running/completed/error
    pages = Column(JSON, default=list)  # 计划采集页面名列表
    collected_pages = Column(JSON, default=list)
    error_message = Column(Text, default="")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppPageDump(Base):
    """单页面采集结果:XML + 截图 + 页面状态/指纹"""
    __tablename__ = "app_page_dumps"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("app_dump_sessions.id"), nullable=False)
    page_name = Column(String(200), default="")
    xml = Column(Text, default="")
    screenshot_path = Column(String(500), default="")
    fingerprint = Column(JSON, default=dict)  # package/activity/control_hash
    action_context = Column(JSON, default=dict)  # 进入该页面的动作上下文
    profile_generated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class AppControlProfile(Base):
    """控件画像(结构化中间表示)"""
    __tablename__ = "app_control_profiles"

    id = Column(Integer, primary_key=True, index=True)
    dump_id = Column(Integer, ForeignKey("app_page_dumps.id"), nullable=True)
    session_id = Column(Integer, ForeignKey("app_dump_sessions.id"), nullable=True)
    page = Column(String(200), default="")
    control_id = Column(String(200), default="")
    role = Column(String(200), default="")  # 业务语义
    xml = Column(JSON, default=dict)  # resource-id/text/class/bounds/clickable...
    context = Column(JSON, default=dict)  # parent/siblings
    actions = Column(JSON, default=list)
    locator_candidates = Column(JSON, default=list)
    risk = Column(String(20), default="low")
    verification = Column(String(20), default="pending")
    source = Column(JSON, default=list)  # xml / vision
    visual = Column(JSON, default=dict)  # 视觉模型补充
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppGapFinding(Base):
    """视觉缺口记录"""
    __tablename__ = "app_gap_findings"

    id = Column(Integer, primary_key=True, index=True)
    dump_id = Column(Integer, ForeignKey("app_page_dumps.id"), nullable=True)
    control_id = Column(String(200), default="")
    gap_type = Column(String(50), default="")  # no_text/no_id/duplicate/icon_only/...
    detail = Column(Text, default="")
    vision_result = Column(JSON, default=dict)  # 视觉模型补充结果
    status = Column(String(20), default="open")  # open/filled
    created_at = Column(DateTime, default=_now)


class AppCaseMatrix(Base):
    """测试意图与用例矩阵"""
    __tablename__ = "app_case_matrix"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), default="")
    requirement_text = Column(Text, default="")
    cases = Column(JSON, default=list)  # [{case_id,title,steps:[{action,target,value}]}]
    status = Column(String(20), default="draft")
    session_id = Column(Integer, ForeignKey("app_dump_sessions.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)


class AppLocator(Base):
    """画像驱动的定位器资产"""
    __tablename__ = "app_locators"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("app_control_profiles.id"), nullable=True)
    case_id = Column(String(100), default="")
    strategy = Column(String(50), default="")  # id/content-desc/text/combo/coordinate
    expression = Column(Text, default="")
    status = Column(String(20), default="pending")  # pending/verified/failed
    page_fingerprint = Column(JSON, default=dict)
    verification_detail = Column(JSON, default=dict)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AppCodeArtifact(Base):
    """固化的正式自动化代码"""
    __tablename__ = "app_code_artifacts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), default="")
    template_type = Column(String(20), default="appium")  # appium / u2
    code = Column(Text, default="")
    file_path = Column(String(500), default="")
    case_ids = Column(JSON, default=list)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
