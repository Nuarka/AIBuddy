# Main.py
# Aiogram 3.x — ИИ-компаньон на OpenRouter (минимальная версия)
# Команды:
# /start — приветствие и краткая справка
# /help — подсказка по функциям
# /setmodel <model> — смена модели на лету (напр.: meta-llama/llama-3.1-8b-instruct)
# /persona <текст> — задание «характера» (системного промпта) компаньона
# /reset — сброс персонажа к значению по умолчанию
# Любое текстовое сообщение — диалог с ИИ (с сохранением короткого контекста)

import os
import asyncio
import logging
from typing import Dict, List

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionMiddleware
from aiogram.client.default import DefaultBotProperties

from dotenv import load_dotenv

# загрузим .env из текущей папки проекта
load_dotenv()

# --- ENV / Config ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required (put it in Render env or .env)")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "meta-llama/llama-3.1-8b-instruct")

# Лёгкая «память» на процесс
PERSONA_DEFAULT = (
    "Ты — доброжелательный ИИ-компаньон. Поддерживай беседу, задавай уточняющие вопросы, "
    "помогай с идеями и планами, пиши кратко и по делу. Отвечай по-русски."
)
user_persona: Dict[int, str] = {}                    # tg_id -> system prompt
user_dialogs: Dict[int, List[Dict[str, str]]] = {}   # tg_id -> последние реплики
MAX_TURNS = 8  # глубина контекста (user/assistant пар)

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("ai-companion")

# --- OpenRouter Chat Completion ---
async def openrouter_chat(messages: List[Dict[str, str]], model: str) -> str:
    """
    messages: [{"role":"system/user/assistant","content":"..."}]
    """
    if not OPENROUTER_API_KEY:
        return "OpenRouter недоступен: не задан OPENROUTER_API_KEY."

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.6,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    txt = await resp.text()
                    return f"Не смог получить ответ от ИИ (OpenRouter {resp.status}). {txt[:300]}"
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Ошибка обращения к OpenRouter: {e}"

def get_persona_for(user_id: int) -> str:
    return user_persona.get(user_id, PERSONA_DEFAULT)

def ensure_dialog(user_id: int):
    if user_id not in user_dialogs:
        user_dialogs[user_id] = []

def push_user_message(user_id: int, content: str):
    ensure_dialog(user_id)
    user_dialogs[user_id].append({"role": "user", "content": content})
    if len(user_dialogs[user_id]) > MAX_TURNS * 2:
        user_dialogs[user_id] = user_dialogs[user_id][-MAX_TURNS * 2 :]

def push_assistant_message(user_id: int, content: str):
    ensure_dialog(user_id)
    user_dialogs[user_id].append({"role": "assistant", "content": content})
    if len(user_dialogs[user_id]) > MAX_TURNS * 2:
        user_dialogs[user_id] = user_dialogs[user_id][-MAX_TURNS * 2 :]

# --- Handlers ---
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я твой ИИ-компаньон 😊\n\n"
        "Напиши, как проходит день, задай вопрос или попроси помощи.\n\n"
        "Команды:\n"
        "• /persona &lt;характер&gt; — настроить стиль и роль компаньона\n"
        "• /reset — сбросить характер к значению по умолчанию\n"
        "• /setmodel &lt;model&gt; — сменить модель OpenRouter\n"
        "• /help — подробнее о настройках",
    )

async def cmd_help(message: Message):
    await message.answer(
        "Как пользоваться:\n"
        "— Просто пиши сообщения: я буду отвечать, сохраняя краткий контекст беседы.\n"
        "— /persona &lt;текст&gt; задаёт системный промпт (характер/роль), напр.:\n"
        "   /persona Спокойный наставник по продуктивности, говори коротко и по делу\n"
        "— /reset сбрасывает характер на дефолтный.\n"
        "— /setmodel &lt;model&gt; переключает модель (пример: meta-llama/llama-3.1-8b-instruct).\n"
        "Замечание: память хранится в оперативке и очищается при рестарте.",
    )

async def cmd_setmodel(message: Message, command: CommandObject):
    global AI_MODEL
    new_model = (command.args or "").strip()
    if not new_model:
        await message.answer(f"Текущая модель: <code>{AI_MODEL}</code>", parse_mode=ParseMode.HTML)
        return
    AI_MODEL = new_model
    await message.answer(f"Ок, модель переключена на: <code>{AI_MODEL}</code>", parse_mode=ParseMode.HTML)

async def cmd_persona(message: Message, command: CommandObject):
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(
            "Использование: /persona &lt;характер&gt;\n"
            "Пример: /persona Дружелюбный коуч по саморазвитию, по шагам даёт советы",
        )
        return
    user_persona[message.from_user.id] = raw
    await message.answer("Готово! Характер компаньона обновлён.")

async def cmd_reset(message: Message):
    user_persona.pop(message.from_user.id, None)
    user_dialogs.pop(message.from_user.id, None)
    await message.answer("Сбросил характер и историю диалога. Начнём с чистого листа!")

async def talk(message: Message):
    uid = message.from_user.id
    ensure_dialog(uid)
    push_user_message(uid, message.text or "")

    messages = [{"role": "system", "content": get_persona_for(uid)}]
    messages.extend(user_dialogs[uid])

    await message.chat.do("typing")
    reply = await openrouter_chat(messages, AI_MODEL)
    push_assistant_message(uid, reply)

    # Telegram лимит ~4096 символов — шлём без HTML-парсинга, чтобы не падать на <...>
    if len(reply) <= 3900:
        await message.answer(reply, parse_mode=None)
    else:
        i = 0
        while i < len(reply):
            await message.answer(reply[i : i + 3900], parse_mode=None)
            i += 3900

# --- App factory ---
def create_dp() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ChatActionMiddleware())

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_setmodel, Command("setmodel"))
    dp.message.register(cmd_persona, Command("persona"))
    dp.message.register(cmd_reset, Command("reset"))
    dp.message.register(talk, F.text)  # остальной текст — в диалог

    return dp

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dp()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Stopped by user")
