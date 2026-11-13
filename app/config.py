"""全局配置：环境变量优先，缺省值保证开箱可跑。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # 应用
    app_name: str = "Commerce Copilot"
    app_env: str = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = ROOT_DIR / "data"

    # 鉴权
    jwt_secret: str = "commerce-copilot-poc-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # LLM（OpenAI 兼容接口；无 Key 时自动降级规则模式）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 30.0
    llm_max_tokens: int = 800

    # 向量
    embedding_mode: str = "auto"          # auto | bge | hash
    embedding_model: str = "BAAI/bge-m3"
    embedding_batch: int = 32
    hf_endpoint: str = "https://hf-mirror.com"

    # 检索
    bm25_top_k: int = 30
    vector_top_k: int = 30
    final_top_k: int = 3
    rrf_k: int = 60
    rrf_bm25_weight: float = 1.6     # 词法通道权重；属性词直给的查询更依赖精确匹配
    rrf_vector_weight: float = 1.0

    # 业务开关
    max_clarify_rounds: int = 2
    max_graph_steps: int = 12
    high_value_threshold: float = 1000.0

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key.strip())

    @property
    def db_path(self) -> Path:
        return self.data_dir / "commerce.db"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = s.hf_endpoint
    return s


settings = get_settings()
