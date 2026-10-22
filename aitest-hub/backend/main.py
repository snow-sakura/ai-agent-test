"""AI Test Hub 后端启动入口。

无论从哪个目录执行,都会先切换到 backend 目录(保证 SQLite 数据库
aitest_hub.db、上传目录等相对路径始终一致),然后启动 FastAPI 应用。

用法:
    python main.py                  # 在 backend 目录下直接启动
    python backend/main.py          # 在项目根目录启动也可以
    python main.py --port 9000      # 指定端口
    python main.py --host 0.0.0.0   # 指定监听地址
    python main.py --no-reload      # 关闭热重载(生产模式)
"""

import argparse
import os
import sys
from pathlib import Path

# backend 目录(main.py 所在目录)
BACKEND_DIR = Path(__file__).resolve().parent

# 保证 `from app...` 包导入可用
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 数据库 / 上传目录等都是相对路径,统一切换到 backend 目录
os.chdir(BACKEND_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Test Hub 后端服务启动入口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址,默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口,默认 8000")
    parser.add_argument(
        "--no-reload", action="store_true", help="关闭热重载(生产/后台常驻模式)"
    )
    args = parser.parse_args()

    from app.core import config
    import uvicorn

    print(f"🚀 启动 {config.APP_NAME} v{config.APP_VERSION} 后端服务...")
    print(f"   地址: http://{args.host}:{args.port}")
    print(f"   API 文档: http://{args.host}:{args.port}/docs")
    print("   默认管理员: admin / admin123")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
    )


if __name__ == "__main__":
    main()
