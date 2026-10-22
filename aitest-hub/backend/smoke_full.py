"""全量冒烟：GET 清单 + 关键 POST。失败清单为空时输出 SMOKE ALL OK。"""

import sys
import traceback

sys.path.insert(0, ".")

GETS = """
/api/health /api/prompts /api/knowledge/patterns /api/knowledge/bugs /api/knowledge/entries
/api/deai/policies /api/config/ai /api/config/roles /api/config/env /api/config/dify /api/config/notify /api/config/roles/reviews
/api/token-usage /api/token-usage/stats /api/logs /api/logs/stats
/api/scheduler/tasks /api/scheduler/logs /api/mcp/market /api/mcp/mine /api/mcp/services
/api/perf/scenes /api/perf/reports
/api/api-testing/endpoints /api/api-testing/envs /api/api-testing/history /api/api-testing/health
/api/security/findings /api/security/baselines
/api/pentest/plans /api/pentest/assets /api/pentest/cases
/api/scenario/plans /api/data-factory/presets
/api/ui-automation/scenes /api/ui-automation/runs
/api/app-automation/devices /api/app-automation/packages /api/app-automation/scripts
/api/app-automation/pipelines /api/app-automation/jobs /api/app-automation/timers
/api/assistant/sessions /api/skills /api/skills/usage/stats /api/skills-center/atomic
/api/agents /api/agents/tasks /api/agents/stats /api/workflows /api/reports /api/reports/stats
/api/root-cause/cases
/api/requirements /api/cases /api/case-modules /api/case-batches /api/bugs
/api/ai-configs /api/projects
""".split()

try:
    from fastapi.testclient import TestClient
    from app.main import app
except Exception:
    traceback.print_exc()
    print("STARTUP FAIL")
    sys.exit(2)

client = TestClient(app, raise_server_exceptions=False)

fails = []

# 先登录（requirements/cases/bugs/ai-configs/projects 等需 Bearer）
token = None
try:
    r = client.post(
        "/api/auth/login", data={"username": "admin", "password": "admin123"}
    )
    ok = r.status_code == 200 and "user" in r.json()
    print(f"[{'OK' if ok else 'FAIL'}] POST /api/auth/login -> {r.status_code}")
    if not ok:
        fails.append(("/api/auth/login", r.status_code, r.text[:300]))
        print("   ", r.text[:300])
    else:
        token = r.json().get("access_token")
except Exception as e:
    fails.append(("/api/auth/login", "EXC", str(e)))
    print(f"[FAIL] POST /api/auth/login -> EXC {e}")

HDR = {"Authorization": f"Bearer {token}"} if token else {}

print("===== GET =====")
for path in GETS:
    try:
        r = client.get(path, headers=HDR)
        status = "OK" if r.status_code == 200 else "FAIL"
        if status == "FAIL":
            fails.append((path, r.status_code, r.text[:300]))
        print(f"[{status}] GET {path} -> {r.status_code}")
        if status == "FAIL":
            print("   ", r.text[:300].replace("\n", " "))
    except Exception as e:
        fails.append((path, "EXC", str(e)))
        print(f"[FAIL] GET {path} -> EXC {e}")

print("===== POST =====")


def post_check(path, accept=(200,), **kw):
    headers = dict(kw.pop("headers", {}) or {})
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")
    try:
        r = client.post(path, headers=headers, **kw)
        ok = r.status_code in accept
        print(
            f"[{'OK' if ok else 'FAIL'}] POST {path} -> {r.status_code} {r.text[:200]}"
        )
        if not ok:
            fails.append((path, r.status_code, r.text[:300]))
        return r
    except Exception as e:
        fails.append((path, "EXC", str(e)))
        print(f"[FAIL] POST {path} -> EXC {e}")
        return None


post_check("/api/assistant/chat", json={"content": "你好"})
post_check("/api/requirements/ai-test", accept=(200, 400), json={"model": ""})

# perf scenes 第一条 id
scene_id = None
try:
    r = client.get("/api/perf/scenes", headers=HDR)
    data = r.json()
    rows = data if isinstance(data, list) else data.get("items", [])
    if rows:
        scene_id = rows[0].get("id")
except Exception:
    pass
if scene_id is not None:
    post_check(f"/api/perf/scenes/{scene_id}/run", json={})
else:
    print("[FAIL] perf scene id not found")
    fails.append(("/api/perf/scenes", "NO_ID", ""))

post_check(
    "/api/deai/apply",
    json={"text": "这是一个非常好的结果，我们非常的满意。", "scope": "全部"},
)
post_check("/api/data-factory/crontab-parse", json={"expr": "0 9 * * *"})
post_check(
    "/api/scenario/import-curl",
    json={
        "curl": "curl -X POST https://example.com/api -H 'Content-Type: application/json' -d '{\"a\":1}'"
    },
)

print("===== SUMMARY =====")
if fails:
    print(f"FAILED: {len(fails)}")
    for p, c, t in fails:
        print(f"  - {p} :: {c} :: {str(t)[:200]}")
    sys.exit(1)
print("SMOKE ALL OK")
