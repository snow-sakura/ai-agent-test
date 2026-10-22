"""接口智能（api-intel）请求体模型。

所有模型全部给默认值并忽略未知字段：案例前端偶尔发送 {} 或多余字段，
服务端必须宽松兼容（校验规则在 common.validate_* 与路由内补充）。
"""

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


class _Loose(BaseModel):
    """宽松基类：忽略未知键，所有字段可缺省。"""

    model_config = ConfigDict(extra="ignore")


# ---------- 工作空间 ----------


class WorkspaceCreateBody(_Loose):
    name: str = ""
    settings: dict = {}


class WorkspacePatchBody(_Loose):
    name: Optional[str] = None
    settings: Optional[dict] = None


# ---------- 文档 spec / sources ----------


class SpecCreateBody(_Loose):
    label: str = "current"
    content: str = ""
    source_type: str = "paste"


class SpecFromUrlBody(_Loose):
    label: str = "current"
    url: str = ""


class SyncUrlL5Body(_Loose):
    url: str = ""
    label: str = "current"
    run_change: bool = False


class YapiImportBody(_Loose):
    base_url: str = ""
    project_id: Any = ""  # 前端可能传字符串或数字
    token: str = ""
    label: str = "current"


# ---------- 命中 / 覆盖率 ----------


class HitsCreateBody(_Loose):
    content: str = ""
    source_type: str = "paste"


class CoverageAnalyzeBody(_Loose):
    spec_id: int = 0
    hit_id: int = 0


class ChangesAnalyzeBody(_Loose):
    baseline_id: int = 0
    current_id: int = 0


class AckBody(_Loose):
    endpoint_key: str = ""


class CoreMarkBody(_Loose):
    keys: List[str] = []
    core: bool = True


# ---------- 成员 / 邀请 ----------


class InviteBody(_Loose):
    identifier: str = ""


# ---------- Edge ----------


class RunProfileBody(_Loose):
    profile: dict = {}


class RunJobCreateBody(_Loose):
    job_type: str = "run"


class TimerSlot(_Loose):
    hour: int = 9
    minute: int = 0


class TimerBody(_Loose):
    enabled: bool = False
    slots: List[TimerSlot] = []


class AgentPackBody(_Loose):
    device_name: str = "desktop"


class AgentHeartbeatBody(_Loose):
    device_id: str = ""
    hostname: str = ""
    os_name: str = ""
    agent_version: str = ""
    device_name: str = "desktop"
    tests_root_hint: str = ""
    capabilities: dict = {}


# ---------- 通知 ----------


class NotifyConfigBody(_Loose):
    channels: dict = {}


# ---------- L5 契约映射 ----------


class ManualMapBody(_Loose):
    method: str = "GET"
    path_norm: str = ""
    test_file: str = ""
    test_node_id: str = ""
    coverage_state: str = "covered"


# ---------- L5 发版门禁 / 证据 ----------


class GateCheckBody(_Loose):
    threshold: float = 80.0
    run_job_id: Optional[str] = None


class ReleaseEvidenceBody(_Loose):
    gate_check_id: Optional[int] = None
    threshold: float = 80.0
    title: str = ""
