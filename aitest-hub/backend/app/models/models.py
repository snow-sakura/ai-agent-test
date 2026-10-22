from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    Float,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(200))
    permissions = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    full_name = Column(String(100))
    is_active = Column(Boolean, default=True)
    role_id = Column(Integer, ForeignKey("roles.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    role = relationship("Role", back_populates="users")
    projects = relationship("Project", back_populates="owner")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    owner_id = Column(Integer, ForeignKey("users.id"))
    password_hash = Column(String(200))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="projects")
    test_cases = relationship("TestCase", back_populates="project")
    api_testcases = relationship("APITestCase", back_populates="project")


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    title = Column(String(200), nullable=False)
    description = Column(Text)
    type = Column(String(50))  # functional, api, ui
    priority = Column(String(20))  # P0, P1, P2, P3
    status = Column(String(20), default="draft")  # draft, active, archived
    steps = Column(JSON)
    expected_result = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="test_cases")
    executions = relationship("TestExecution", back_populates="test_case")


class APITestCase(Base):
    __tablename__ = "api_testcases"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String(200), nullable=False)
    method = Column(String(10))  # GET, POST, PUT, DELETE
    url = Column(String(500))
    headers = Column(JSON)
    body = Column(JSON)
    expected_status = Column(Integer)
    expected_response = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="api_testcases")


class TestExecution(Base):
    __tablename__ = "test_executions"

    id = Column(Integer, primary_key=True, index=True)
    test_case_id = Column(Integer, ForeignKey("test_cases.id"))
    status = Column(String(20))  # passed, failed, error, skipped
    result = Column(JSON)
    duration = Column(Float)
    logs = Column(Text)
    executed_at = Column(DateTime, default=datetime.utcnow)

    test_case = relationship("TestCase", back_populates="executions")


class AIConfig(Base):
    __tablename__ = "ai_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    supplier = Column(String(50))  # openai, deepseek, qwen, ollama
    model_name = Column(String(100))
    api_key = Column(String(200))
    base_url = Column(String(500))
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class KnowledgePattern(Base):
    __tablename__ = "knowledge_patterns"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    type = Column(String(50))  # pattern, bug
    title = Column(String(200), nullable=False)
    content = Column(Text)
    tags = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String(200), nullable=False)
    description = Column(Text)
    canvas = Column(JSON)
    nodes = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Defect(Base):
    __tablename__ = "defects"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    title = Column(String(200), nullable=False)
    description = Column(Text)
    severity = Column(String(20))  # critical, major, minor, trivial
    status = Column(String(20), default="open")  # open, in_progress, resolved, closed
    assignee_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============ 接口智能(api-intel) 新增模型 ============


class ApiDocument(Base):
    """接口文档快照"""

    __tablename__ = "api_documents"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("at_projects.id"), nullable=False)
    name = Column(String(200), nullable=False)
    source_type = Column(String(20), default="upload")  # upload / url / yapi
    source_url = Column(Text, default="")
    summary = Column(Text, default="")
    endpoints_count = Column(Integer, default=0)
    raw_content = Column(JSON, default=dict)  # 原始导入内容
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiDocumentEndpoint(Base):
    """文档中的接口定义"""

    __tablename__ = "api_document_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("api_documents.id"), nullable=False)
    method = Column(String(10), default="GET")
    path = Column(String(500), nullable=False)
    summary = Column(Text, default="")
    description = Column(Text, default="")
    request_params = Column(JSON, default=list)  # query / header / path 参数
    request_body = Column(JSON, default=dict)  # request body schema
    response_example = Column(JSON, default=dict)
    response_schema = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiIntelSetting(Base):
    """接口智能项目设置"""

    __tablename__ = "api_intel_settings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("at_projects.id"), nullable=False, unique=True
    )
    python_path = Column(String(500), default="python")  # 本机 Python 路径
    project_path = Column(String(500), default="")  # 本机项目路径
    ai_provider = Column(String(50), default="openai")  # openai / deepseek / qwen
    ai_model = Column(String(100), default="gpt-3.5-turbo")
    ai_api_key = Column(String(500), default="")
    ai_base_url = Column(String(500), default="")
    notification_email = Column(String(200), default="")
    notification_webhook = Column(String(500), default="")
    cron_enabled = Column(Boolean, default=False)
    cron_expression = Column(String(100), default="0 8 * * *")
    extra_config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectMember(Base):
    """项目协作者"""

    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("at_projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), default="editor")  # owner / editor / viewer
    invited_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
