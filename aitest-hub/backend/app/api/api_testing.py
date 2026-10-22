"""API 自动化测试（api-testing）路由壳。

历史说明：
- 旧版「接口智能」路由 router_intel（/api/api-intel 的 projects/documents 等）
  已由独立包 app.api.api_intel 全量复刻替代，并从本文件移除；
  备份见 .reference/legacy-api-intel/api_testing.with-router_intel.bak.py。
- 本文件仅保留其它页面（ApiTesting.vue）仍在探活的 /api/api-testing/health。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/api-testing", tags=["api-testing"])


@router.get("/health")
async def testing_health():
    return {"status": "ok", "service": "api-testing"}
