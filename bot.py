import os
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("bot")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

bot: Optional[Bot] = None
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    if not WEBAPP_URL:
        await message.answer(
            "WEBAPP_URL не настроен на сервере. Добавь его в переменные окружения и перезапусти бота."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Открыть расписание", web_app=WebAppInfo(url=WEBAPP_URL))]
        ]
    )
    await message.answer(
        "Привет! Нажми кнопку ниже, чтобы открыть расписание.",
        reply_markup=keyboard,
    )


async def start_bot():
    """Запускает бота в режиме long polling. Вызывается как фоновая задача из server.py."""
    global bot
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — бот не запущен, работает только веб-часть")
        return
    bot = Bot(token=BOT_TOKEN)
    try:
        await dp.start_polling(bot)
    except Exception:
        logger.exception("Бот аварийно остановился")


async def stop_bot():
    global bot
    if bot:
        await bot.session.close()
