import os
import time
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from scraper import get_schedule, ScheduleFetchError
from bot import start_bot, stop_bot

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

GROUP_FAK = os.getenv("GROUP_FAK", "Экономический")
GROUP_FORM = os.getenv("GROUP_FORM", "Dnevnaya")
GROUP_KURSE = os.getenv("GROUP_KURSE", "1 kurs")
GROUP_CLASS = os.getenv("GROUP_CLASS", "2611 MN")

# Простой кэш в памяти, чтобы не дёргать сайт универа при каждом открытии мини-приложения.
CACHE_TTL_SECONDS = 10 * 60  # 10 минут
_cache: dict = {"data": None, "fetched_at": 0}

_bot_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot_task
    _bot_task = asyncio.create_task(start_bot())
    logger.info("Фоновая задача бота запущена")
    yield
    await stop_bot()
    if _bot_task:
        _bot_task.cancel()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/schedule")
def api_schedule(force: bool = False):
    now = time.time()
    if not force and _cache["data"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        return JSONResponse(content={"days": _cache["data"], "cached": True})

    try:
        data = get_schedule(
            fak=GROUP_FAK,
            form=GROUP_FORM,
            kurse=GROUP_KURSE,
            group_class=GROUP_CLASS,
        )
        _cache["data"] = data
        _cache["fetched_at"] = now
        return JSONResponse(content={"days": data, "cached": False})
    except ScheduleFetchError as e:
        logger.error("Ошибка парсинга расписания: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("Неожиданная ошибка при получении расписания")
        raise HTTPException(status_code=502, detail=f"Не удалось получить расписание: {e}")


# Отдаём саму мини-аппку (папку webapp) на корневом пути.
# ВАЖНО: этот роут регистрируется последним, чтобы не перекрыть /api/schedule.
app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
