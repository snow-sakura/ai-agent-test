"""接口智能（api-intel）路由聚合

对外只暴露一个 router，统一挂载前缀 /api/api-intel。
子模块按资源划分：

- router_workspaces : 工作空间（项目）、成员与邀请、审计、核心接口标记
- router_specs      : 文档快照 spec、数据源（URL / YApi）、命中 hits、覆盖率 coverage
- router_l5         : L5 契约对照 endpoint-map-l5（对照、建议、手工映射）
- router_notify     : 通知通道配置、通知日志、发送测试
- router_edge       : 本机 Agent（设备、运行档案、Python 探测、运行任务、日志、定时、启动包）

业务异常 ApiError 由 app.main 中注册的 handler 统一转成 {"error": 中文提示}。
"""

from fastapi import APIRouter

from app.api.api_intel import (
    router_edge,
    router_l5,
    router_notify,
    router_specs,
    router_workspaces,
)

# 统一前缀；各子路由内部已写全 /workspaces/{ws}/... 相对路径
router = APIRouter(prefix="/api/api-intel", tags=["api-intel"])

# 健康检查：前端 ApiIntelApi 是否加载完成的探针
router.add_api_route(
    "/health",
    lambda: {"ok": True, "module": "api-intel"},
    methods=["GET"],
    tags=["api-intel"],
    summary="接口智能后端健康检查",
)

router.include_router(router_workspaces.router)
router.include_router(router_specs.router)
router.include_router(router_l5.router)
router.include_router(router_notify.router)
router.include_router(router_edge.router)

__all__ = ["router"]
