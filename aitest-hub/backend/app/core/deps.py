"""共享依赖：JWT 当前用户（FastAPI Depends），供 main 与各路由模块使用。

使用 SyncDB（同步 sqlite3 + asyncio.to_thread）替代 SQLAlchemy AsyncSession。
"""

from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.database import get_db, SyncDB, db_fetch_one
from app.core.security import decode_token

# auto_error=False：缺失 Authorization 头时依赖结果为 None，
# 由下方统一抛 401（FastAPI 默认 HTTPBearer 会抛 403，与前端拦截器约定的 401 不符）
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: SyncDB = Depends(get_db),
) -> dict:
    """从 JWT 中解析当前用户并返回 dict 行。

    路由中直接使用 user["id"]、user["username"] 等字段访问。
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db_fetch_one(db, "SELECT * FROM users WHERE id=?", [int(user_id)])
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: SyncDB = Depends(get_db),
) -> Optional[dict]:
    """可选当前用户：未登录/令牌无效时返回 None（不抛 401）。

    用于公开列表顺带返回「当前用户是否已收藏」。
    """
    if credentials is None or not credentials.credentials:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("sub") is None:
        return None
    try:
        user = await db_fetch_one(
            db, "SELECT * FROM users WHERE id=?", [int(payload["sub"])]
        )
    except Exception:
        return None
    return user
