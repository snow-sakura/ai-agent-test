"""数据库连接管理

由于 Python 3.14 环境不支持 greenlet 库，这里使用纯同步 sqlite3 + asyncio.to_thread
方式实现数据库操作，完全避免对 SQLAlchemy async ORM 的依赖。
"""

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from app.core.config import DATABASE_URL

# 数据库文件路径
DB_PATH = Path(__file__).resolve().parent.parent / "aitest_hub.db"


# 兼容层：保持 Base / async_session 导出，让其他旧模块能正常导入
class Base:
    """兼容占位 - database.py 已改为纯 sqlite3 模式"""

    metadata = None


class AsyncSession:
    """兼容占位 - 已改用 SyncDB"""

    pass


async_session = None


# =============================================================================
# 同步数据库连接（核心）
# =============================================================================


def _get_conn() -> sqlite3.Connection:
    """获取同步 SQLite 连接（自动设置 Row 工厂和 WAL 模式）"""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def get_db():
    """异步数据库依赖 - 使用 to_thread 运行同步操作"""
    conn = _get_conn()
    try:
        yield SyncDB(conn)
    finally:
        conn.close()


# =============================================================================
# 同步数据库包装器（提供简单的 ORM-like 接口）
# =============================================================================


class SyncDB:
    """同步数据库操作包装器"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cursor = conn.cursor()

    def execute(self, sql: str, params=None):
        """执行 SQL"""
        if params is None:
            self.cursor.execute(sql)
        else:
            self.cursor.execute(sql, params)
        return self.cursor

    def execute_many(self, sql: str, params_list: list):
        """批量执行"""
        self.cursor.executemany(sql, params_list)
        return self.cursor

    def fetch_one(self):
        """获取单行（返回 dict）"""
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetch_all(self):
        """获取所有行（返回 dict 列表）"""
        return [dict(row) for row in self.cursor.fetchall()]

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def last_row_id(self) -> int:
        return self.cursor.lastrowid

    def rowcount(self) -> int:
        return self.cursor.rowcount


# =============================================================================
# CRUD 辅助函数（与 API 路由配合使用）
# =============================================================================


async def db_execute(db: SyncDB, sql: str, params=None):
    """异步执行 SQL"""
    return await asyncio.to_thread(db.execute, sql, params)


async def db_fetch_one(db: SyncDB, sql: str, params=None):
    """异步执行 SQL 并获取一行"""
    await asyncio.to_thread(db.execute, sql, params or [])
    return await asyncio.to_thread(db.fetch_one)


async def db_fetch_all(db: SyncDB, sql: str, params=None):
    """异步执行 SQL 并获取所有行"""
    await asyncio.to_thread(db.execute, sql, params or [])
    return await asyncio.to_thread(db.fetch_all)


async def db_commit(db: SyncDB):
    """异步提交"""
    await asyncio.to_thread(db.commit)


async def db_insert(db: SyncDB, table: str, data: dict) -> int:
    """插入一行数据，返回自增ID"""
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    values = [_serialize(v) for v in data.values()]
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    await asyncio.to_thread(db.execute, sql, values)
    await asyncio.to_thread(db.commit)
    return await asyncio.to_thread(db.last_row_id)


async def db_update(db: SyncDB, table: str, data: dict, where: str, where_params=None):
    """更新数据"""
    set_clause = ", ".join([f"{k}=?" for k in data.keys()])
    values = [_serialize(v) for v in data.values()]
    if where_params:
        values.extend(where_params)
    sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
    await asyncio.to_thread(db.execute, sql, values)
    await asyncio.to_thread(db.commit)
    return await asyncio.to_thread(db.rowcount)


async def db_delete(db: SyncDB, table: str, where: str, where_params=None):
    """删除数据"""
    sql = f"DELETE FROM {table} WHERE {where}"
    await asyncio.to_thread(db.execute, sql, where_params or [])
    await asyncio.to_thread(db.commit)
    return await asyncio.to_thread(db.rowcount)


async def db_select_one(
    db: SyncDB, table: str, where: str, where_params=None, columns="*"
):
    """查询单行"""
    sql = f"SELECT {columns} FROM {table} WHERE {where} LIMIT 1"
    return await db_fetch_one(db, sql, where_params or [])


async def db_select_all(
    db: SyncDB,
    table: str,
    where: str = "1=1",
    where_params=None,
    columns="*",
    order_by: str = "",
    limit: int = 0,
):
    """查询多行"""
    sql = f"SELECT {columns} FROM {table} WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit > 0:
        sql += f" LIMIT {limit}"
    return await db_fetch_all(db, sql, where_params or [])


def _serialize(v):
    """将 dict/list 序列化为 JSON 字符串"""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _deserialize(v):
    """尝试将 JSON 字符串反序列化"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


# =============================================================================
# 数据库初始化
# =============================================================================


def init_db_sync():
    """初始化数据库 - 创建所有表（同步模式）"""
    conn = _get_conn()
    cursor = conn.cursor()

    # 创建核心表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(50) UNIQUE NOT NULL,
        description VARCHAR(200),
        permissions TEXT DEFAULT '[]',
        created_at TIMESTAMP
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(50) UNIQUE NOT NULL,
        phone VARCHAR(20) UNIQUE,
        email VARCHAR(100) UNIQUE NOT NULL,
        hashed_password VARCHAR(200) NOT NULL,
        full_name VARCHAR(100),
        is_active BOOLEAN DEFAULT 1,
        role_id INTEGER,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY (role_id) REFERENCES roles(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(100) NOT NULL,
        description TEXT,
        owner_id INTEGER,
        password_hash VARCHAR(200),
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS test_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, title VARCHAR(200) NOT NULL,
        description TEXT, type VARCHAR(50), priority VARCHAR(20),
        status VARCHAR(20) DEFAULT 'draft', steps TEXT,
        expected_result TEXT, created_at TIMESTAMP, updated_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS api_testcases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, name VARCHAR(200) NOT NULL,
        method VARCHAR(10), url VARCHAR(500), headers TEXT,
        body TEXT, expected_status INTEGER, expected_response TEXT,
        created_at TIMESTAMP, FOREIGN KEY (project_id) REFERENCES projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS test_executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_case_id INTEGER, status VARCHAR(20), result TEXT,
        duration FLOAT, logs TEXT, executed_at TIMESTAMP,
        FOREIGN KEY (test_case_id) REFERENCES test_cases(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(100) NOT NULL, supplier VARCHAR(50),
        model_name VARCHAR(100), api_key VARCHAR(200),
        base_url VARCHAR(500), is_default BOOLEAN DEFAULT 0,
        created_at TIMESTAMP
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, type VARCHAR(50), title VARCHAR(200) NOT NULL,
        content TEXT, tags TEXT, created_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS workflows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, name VARCHAR(200) NOT NULL,
        description TEXT, canvas TEXT, nodes TEXT,
        created_at TIMESTAMP, updated_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS defects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, title VARCHAR(200) NOT NULL,
        description TEXT, severity VARCHAR(20), status VARCHAR(20) DEFAULT 'open',
        assignee_id INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id),
        FOREIGN KEY (assignee_id) REFERENCES users(id)
    )""")

    # 接口智能表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(200) NOT NULL, description TEXT DEFAULT '',
        project_type VARCHAR(20) DEFAULT 'HTTP', status VARCHAR(20) DEFAULT 'NOT_STARTED',
        start_date VARCHAR(20), end_date VARCHAR(20), owner_id INTEGER,
        created_at TIMESTAMP, updated_at TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_collections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(200) NOT NULL, description TEXT DEFAULT '',
        order_num INTEGER DEFAULT 0, project_id INTEGER NOT NULL, parent_id INTEGER,
        created_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES at_projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        collection_id INTEGER, project_id INTEGER NOT NULL,
        name VARCHAR(200) NOT NULL, description TEXT DEFAULT '',
        request_type VARCHAR(20) DEFAULT 'HTTP', method VARCHAR(10) DEFAULT 'GET',
        url TEXT DEFAULT '', headers TEXT DEFAULT '{}', params TEXT DEFAULT '{}',
        body TEXT DEFAULT '{}', assertions TEXT DEFAULT '[]',
        order_num INTEGER DEFAULT 0, created_by INTEGER,
        created_at TIMESTAMP, updated_at TIMESTAMP,
        FOREIGN KEY (collection_id) REFERENCES at_collections(id),
        FOREIGN KEY (project_id) REFERENCES at_projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_environments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(200) NOT NULL, scope VARCHAR(10) DEFAULT 'GLOBAL',
        variables TEXT DEFAULT '{}', is_active BOOLEAN DEFAULT 0, project_id INTEGER,
        created_at TIMESTAMP, FOREIGN KEY (project_id) REFERENCES at_projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_request_histories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER, request_data TEXT DEFAULT '{}',
        response_data TEXT, status_code INTEGER, response_time FLOAT,
        error_message TEXT DEFAULT '', assertions_results TEXT,
        executed_by INTEGER, executed_at TIMESTAMP,
        FOREIGN KEY (request_id) REFERENCES at_requests(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_test_suites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL, name VARCHAR(200) NOT NULL,
        description TEXT DEFAULT '', environment_id INTEGER, created_by INTEGER,
        created_at TIMESTAMP, FOREIGN KEY (project_id) REFERENCES at_projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_suite_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        suite_id INTEGER NOT NULL, request_id INTEGER NOT NULL,
        order_num INTEGER DEFAULT 0, enabled BOOLEAN DEFAULT 1,
        FOREIGN KEY (suite_id) REFERENCES at_test_suites(id),
        FOREIGN KEY (request_id) REFERENCES at_requests(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_test_executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        suite_id INTEGER NOT NULL, status VARCHAR(20) DEFAULT 'PENDING',
        total_requests INTEGER DEFAULT 0, passed_requests INTEGER DEFAULT 0,
        failed_requests INTEGER DEFAULT 0, results TEXT DEFAULT '{}',
        executed_by INTEGER, created_at TIMESTAMP,
        FOREIGN KEY (suite_id) REFERENCES at_test_suites(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_scheduled_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL, suite_id INTEGER,
        name VARCHAR(200) NOT NULL, cron_expression VARCHAR(100) DEFAULT '0 8 * * *',
        description TEXT DEFAULT '', is_active BOOLEAN DEFAULT 0,
        notification_settings TEXT DEFAULT '{}', created_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES at_projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS at_task_execution_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL, success BOOLEAN DEFAULT 1,
        message TEXT DEFAULT '', detail TEXT,
        total_requests INTEGER DEFAULT 0, passed_requests INTEGER DEFAULT 0,
        failed_requests INTEGER DEFAULT 0, executed_at TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES at_scheduled_tasks(id)
    )""")

    # 新增接口智能表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS api_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL, name VARCHAR(200) NOT NULL,
        source_type VARCHAR(20) DEFAULT 'upload', source_url TEXT DEFAULT '',
        summary TEXT DEFAULT '', endpoints_count INTEGER DEFAULT 0,
        raw_content TEXT DEFAULT '{}', created_by INTEGER,
        created_at TIMESTAMP, updated_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES at_projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS api_document_endpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER NOT NULL, method VARCHAR(10) DEFAULT 'GET',
        path VARCHAR(500) NOT NULL, summary TEXT DEFAULT '',
        description TEXT DEFAULT '', request_params TEXT DEFAULT '[]',
        request_body TEXT DEFAULT '{}', response_example TEXT DEFAULT '{}',
        response_schema TEXT DEFAULT '{}', tags TEXT DEFAULT '[]',
        created_at TIMESTAMP, FOREIGN KEY (document_id) REFERENCES api_documents(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS api_intel_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL UNIQUE,
        python_path VARCHAR(500) DEFAULT 'python', project_path VARCHAR(500) DEFAULT '',
        ai_provider VARCHAR(50) DEFAULT 'openai', ai_model VARCHAR(100) DEFAULT 'gpt-3.5-turbo',
        ai_api_key VARCHAR(500) DEFAULT '', ai_base_url VARCHAR(500) DEFAULT '',
        notification_email VARCHAR(200) DEFAULT '', notification_webhook VARCHAR(500) DEFAULT '',
        cron_enabled BOOLEAN DEFAULT 0, cron_expression VARCHAR(100) DEFAULT '0 8 * * *',
        extra_config TEXT DEFAULT '{}', created_at TIMESTAMP, updated_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES at_projects(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        role VARCHAR(20) DEFAULT 'editor', invited_by INTEGER,
        created_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES at_projects(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")

    # =====================================================================
    # 接口智能（api-intel）重建版数据表 —— 对齐 testhubkit 案例站 API 契约
    # =====================================================================

    # 工作空间（项目）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_ws (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL, name VARCHAR(200) NOT NULL,
        settings_json TEXT DEFAULT '{}', created_at TEXT, updated_at TEXT,
        FOREIGN KEY (owner_id) REFERENCES users(id)
    )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_ws_owner ON ai_ws(owner_id)")

    # 工作空间成员（owner/member）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_ws_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        role VARCHAR(20) DEFAULT 'member', created_at TEXT,
        UNIQUE (ws_id, user_id)
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_ws_members_user ON ai_ws_members(user_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_ws_members_ws ON ai_ws_members(ws_id)"
    )

    # 工作空间邀请（pending/accepted/rejected）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_ws_invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, inviter_id INTEGER NOT NULL,
        invitee_user_id INTEGER NOT NULL,
        status VARCHAR(20) DEFAULT 'pending', created_at TEXT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_ws_invites_ws ON ai_ws_invites(ws_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_ws_invites_user ON ai_ws_invites(invitee_user_id, status)"
    )

    # 文档快照（OpenAPI/Swagger 解析结果）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_specs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, label VARCHAR(200) DEFAULT 'current',
        source_type VARCHAR(20) DEFAULT 'paste', content_raw TEXT DEFAULT '',
        summary_json TEXT DEFAULT '{}', created_at TEXT
    )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_specs_ws ON ai_specs(ws_id, id)")

    # 命中列表导入
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_hits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, content_raw TEXT DEFAULT '',
        summary_json TEXT DEFAULT '{}', created_at TEXT
    )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_hits_ws ON ai_hits(ws_id, id)")

    # 覆盖率缺口报告
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_coverage_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, spec_id INTEGER, hit_id INTEGER,
        summary_json TEXT DEFAULT '{}', gaps_json TEXT DEFAULT '{}', created_at TEXT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_coverage_ws ON ai_coverage_reports(ws_id, id)"
    )

    # 新旧快照变更报告
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_changes_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, baseline_id INTEGER, current_id INTEGER,
        report_json TEXT DEFAULT '{}', created_at TEXT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_changes_ws ON ai_changes_reports(ws_id, id)"
    )

    # L5 契约映射（文档端点 ↔ 测试代码 对照结果）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_endpoint_map (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, method VARCHAR(10) DEFAULT 'GET',
        path_norm VARCHAR(500) DEFAULT '', test_node_id VARCHAR(500) DEFAULT '',
        test_file VARCHAR(500) DEFAULT '',
        coverage_state VARCHAR(20) DEFAULT 'missing',
        source VARCHAR(20) DEFAULT 'auto', created_at TEXT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_endpoint_map_ws ON ai_endpoint_map(ws_id, coverage_state)"
    )

    # 本机运行配置（每个工作空间一份）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_run_profiles (
        ws_id INTEGER PRIMARY KEY,
        project_root TEXT DEFAULT '', entry_file VARCHAR(256) DEFAULT 'run.py',
        python_cmd VARCHAR(512) DEFAULT 'python', updated_at TEXT
    )""")

    # Edge 设备（本机 Agent；本平台内置模拟器注册自身）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_edge_devices (
        id VARCHAR(36) PRIMARY KEY,
        ws_id INTEGER NOT NULL, hostname VARCHAR(200) DEFAULT '',
        os_name VARCHAR(100) DEFAULT '', agent_version VARCHAR(50) DEFAULT '',
        status VARCHAR(20) DEFAULT 'offline', tests_root_hint TEXT DEFAULT '',
        capabilities_json TEXT DEFAULT '{}', last_seen_at TEXT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_edge_devices_ws ON ai_edge_devices(ws_id, last_seen_at)"
    )

    # 运行任务（uuid 主键）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_run_jobs (
        id VARCHAR(36) PRIMARY KEY,
        ws_id INTEGER NOT NULL, device_id VARCHAR(36),
        job_type VARCHAR(30) DEFAULT 'run', status VARCHAR(30) DEFAULT 'queued',
        created_by INTEGER, created_at TEXT, started_at TEXT, finished_at TEXT,
        summary_json TEXT DEFAULT '{}', exit_code INTEGER
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_run_jobs_ws ON ai_run_jobs(ws_id, id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_run_jobs_status ON ai_run_jobs(status)"
    )

    # 运行任务日志（按 seq 递增，支持 after_seq 增量拉取）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_run_job_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id VARCHAR(36) NOT NULL, seq INTEGER NOT NULL,
        text TEXT DEFAULT '', created_at TEXT
    )""")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_run_job_logs_seq ON ai_run_job_logs(job_id, seq)"
    )

    # 定时运行配置（HH:MM 时段数组）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_edge_timer (
        ws_id INTEGER PRIMARY KEY,
        enabled BOOLEAN DEFAULT 0, slots_json TEXT DEFAULT '[]', updated_at TEXT
    )""")

    # 通知配置
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_notify_config (
        ws_id INTEGER PRIMARY KEY,
        channels_json TEXT DEFAULT '{}', updated_at TEXT
    )""")

    # 通知发送日志
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_notify_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, event_type VARCHAR(50) DEFAULT 'test',
        channel VARCHAR(30) DEFAULT '', status VARCHAR(30) DEFAULT '',
        detail_json TEXT DEFAULT '{}', created_at TEXT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_notify_logs_ws ON ai_notify_logs(ws_id, id)"
    )

    # 操作审计
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, user_id INTEGER, action VARCHAR(100) DEFAULT '',
        detail_json TEXT DEFAULT '{}', created_at TEXT
    )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_audit_ws ON ai_audit(ws_id, id)")

    # L5 发版门禁检查记录
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_gate_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, threshold REAL DEFAULT 80,
        passed BOOLEAN DEFAULT 0, covered INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0, coverage_pct REAL DEFAULT 0,
        run_job_id VARCHAR(64) DEFAULT '',
        detail_json TEXT DEFAULT '{}', created_by INTEGER,
        created_at TEXT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_gate_checks_ws ON ai_gate_checks(ws_id, id)"
    )

    # L5 发版证据存档
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_release_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ws_id INTEGER NOT NULL, gate_check_id INTEGER,
        title VARCHAR(200) DEFAULT '', payload_json TEXT DEFAULT '{}',
        created_by INTEGER, created_at TEXT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_release_ev_ws ON ai_release_evidence(ws_id, id)"
    )

    # 兼容旧 app 表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(200),
        project_type VARCHAR(20), config TEXT, owner_id INTEGER,
        created_at TIMESTAMP, updated_at TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_test_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
        test_framework VARCHAR(50), test_dir VARCHAR(500), app_type VARCHAR(50),
        app_path VARCHAR(500), package_name VARCHAR(200), main_activity VARCHAR(500),
        platform_name VARCHAR(50), platform_version VARCHAR(20), device_name VARCHAR(200),
        automation_name VARCHAR(50), no_reset BOOLEAN, full_reset BOOLEAN,
        created_at TIMESTAMP, updated_at TIMESTAMP
    )""")

    # ALTER 兼容
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20)")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "ALTER TABLE ai_configs ADD COLUMN tier TEXT DEFAULT 'free'"
        )
    except sqlite3.OperationalError:
        pass

    # 创建默认角色和用户
    cursor.execute("SELECT id FROM roles WHERE name='admin'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO roles (name, description, permissions, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("admin", "管理员", '["read","write","admin"]'),
        )
    cursor.execute("SELECT id FROM roles WHERE name='tester'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO roles (name, description, permissions, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("tester", "普通测试人员", '["read","write"]'),
        )

    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成（同步模式）")


async def init_db():
    """异步数据库初始化入口"""
    init_db_sync()
