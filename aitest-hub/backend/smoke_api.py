"""8 模块 TestClient 冒烟自测：GET 断言 200 + 有数据。"""

import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

# (path, min_len 或 None 表示只需 200)
CHECKS = [
    ("/api/prompts", 1),
    ("/api/knowledge/patterns", 1),
    ("/api/deai/policies", 1),
    ("/api/config/ai", None),
    ("/api/config/roles", None),
    ("/api/token-usage", 1),
    ("/api/token-usage/stats", None),
    ("/api/logs", 1),
    ("/api/logs/stats", None),
    ("/api/scheduler/tasks", 1),
    ("/api/scheduler/logs", 1),
    ("/api/scheduler/stats", None),
    ("/api/mcp/market", 1),
    ("/api/mcp/mine", 1),
]

fail = 0
for path, min_len in CHECKS:
    try:
        r = client.get(path)
        ok = r.status_code == 200
        data = None
        if ok:
            try:
                data = r.json()
            except Exception:
                ok = False
        if ok and min_len is not None:
            if isinstance(data, dict):
                # 分页结构 items / list
                lst = data.get("items") if isinstance(data.get("items"), list) else data
            else:
                lst = data
            if not isinstance(lst, list) or len(lst) < min_len:
                ok = False
        if ok and min_len is None:
            if data is None or (isinstance(data, (list, dict)) and len(data) == 0):
                ok = False
        status = "OK" if ok else "FAIL"
        if not ok:
            fail += 1
        n = ""
        if isinstance(data, list):
            n = f" n={len(data)}"
        elif isinstance(data, dict) and isinstance(data.get("items"), list):
            n = f" total={data.get('total', len(data['items']))}"
        print(f"[{status}] GET {path} → {r.status_code}{n}")
        if not ok:
            print("  body:", str(r.text)[:300])
    except Exception as e:
        fail += 1
        print(f"[FAIL] GET {path} → {type(e).__name__}: {e}")

if fail:
    print(f"FAILED: {fail}/{len(CHECKS)}")
    sys.exit(1)
print("ALL OK")
