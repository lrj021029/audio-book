"""FastAPI entrypoint."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import APP_PORT
from .errors import AppError
from .response import fail
from .routers.content import router as content_router
from .routers.creator import router as creator_router
from .routers.interactions import router as interactions_router
from .routers.library import router as library_router
from .routers.playback import router as playback_router
from .routers.search import router as search_router
from .routers.tickets import router as tickets_router
from .routers.trade import router as trade_router
from .routers.users import router as users_router
from .routers.wallet import router as wallet_router

OPENAPI_TAGS = [
    {"name": "content", "description": "1. 公共内容浏览"},
    {"name": "search", "description": "2. 搜索"},
    {"name": "playback", "description": "3. 播放"},
    {"name": "library", "description": "4. 书架与关注"},
    {"name": "interactions", "description": "5. 互动与反馈"},
    {"name": "trade", "description": "6. 会员、交易与权益"},
    {"name": "wallet", "description": "7. 钱包"},
    {"name": "users", "description": "8. 用户中心与消息"},
    {"name": "tickets", "description": "9. 客服工单"},
    {"name": "creator", "description": "10. 创作者与内容供给"},
]

app = FastAPI(title="Audio Data API", version="0.1.0", openapi_tags=OPENAPI_TAGS)

app.include_router(content_router)
app.include_router(search_router)
app.include_router(playback_router)
app.include_router(library_router)
app.include_router(interactions_router)
app.include_router(trade_router)
app.include_router(wallet_router)
app.include_router(users_router)
app.include_router(tickets_router)
app.include_router(creator_router)


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=fail(exc.code, exc.message),
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=fail("VALIDATION_ERROR", str(exc)),
    )


@app.exception_handler(ValueError)
async def handle_value_error(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content=fail("BAD_REQUEST", str(exc)))


@app.get("/health", summary="健康检查")
def health() -> dict[str, object]:
    return {"code": 0, "message": "ok", "data": {"status": "ok"}}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=APP_PORT, reload=False)
