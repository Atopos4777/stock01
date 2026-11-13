"""应用入口：启动即建库、灌种子、建索引；静态前端由同一进程提供。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import ROOT_DIR, settings
from app.db.seed import seed_all
from app.rag import policy_store
from app.retrieval import index as product_index
from app.services.product_service import list_all_products

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("commerce-copilot")

FRONTEND = ROOT_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("初始化数据库与种子数据 ...")
    counts = seed_all(reset=False)
    logger.info("数据规模：%s", counts)
    logger.info("构建商品索引 ...")
    product_index.build_index(list_all_products())
    policy_store.build_policy_index()
    logger.info("启动完成：http://%s:%d", settings.host, settings.port)
    yield
    logger.info("服务已停止")


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.include_router(router)

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
def homepage():
    index = FRONTEND / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "前端未找到，请访问 /docs"}
