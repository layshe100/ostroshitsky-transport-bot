from __future__ import annotations

import os
import re
import logging
from datetime import datetime, time as dt_time, timedelta

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from schedule import format_departures, next_departures, timezone


load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)


def parse_query(text: str) -> tuple[str | None, int, str | None, str | None, dt_time | None]:
    normalized = text.lower().replace("ё", "е")
    explicit_to_ostroshitsky = bool(re.search(r"до\s+(?:острош|городок)", normalized))
    explicit_to_vostok = bool(re.search(r"до\s+восток", normalized))
    at_vostok = bool(re.search(r"(?:я\s+)?(?:сейчас\s+)?(?:на|у)\s+восток", normalized))
    at_ostroshitsky = bool(re.search(r"(?:я\s+)?(?:сейчас\s+)?(?:в|из|на)\s+острош", normalized))

    if explicit_to_ostroshitsky:
        direction = "to_ostroshitsky"
    elif explicit_to_vostok:
        direction = "to_vostok"
    elif at_vostok:
        direction = "to_ostroshitsky"
    elif at_ostroshitsky:
        direction = "to_vostok"
    elif "острош" in normalized or "городок" in normalized:
        direction = "to_ostroshitsky"
    elif any(token in normalized for token in ("восток", "минск")):
        direction = "to_vostok"
    else:
        direction = None

    route = None
    if re.search(r"\b451\b", normalized):
        route = "451"
    elif re.search(r"\b2198\b", normalized):
        route = "2198"

    offset_match = re.search(r"через\s+(\d+)\s*(?:мин|минут|минуты|минуту)?", normalized)
    offset_minutes = int(offset_match.group(1)) if offset_match else 0

    time_match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", normalized)
    requested_time = None
    if time_match:
        requested_time = dt_time(int(time_match.group(1)), int(time_match.group(2)))

    season = None
    if "лет" in normalized:
        season = "summer"
    elif "зим" in normalized:
        season = "winter"
    return direction, offset_minutes, season, route, requested_time


def keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["До Острошицкого городка", "До ст. метро Восток"], ["Выбрать время"], ["Помощь"]],
        resize_keyboard=True,
    )


def time_keyboard() -> ReplyKeyboardMarkup:
    buttons = []
    for total_minutes in range(5 * 60, 23 * 60 + 1, 30):
        hour, minute = divmod(total_minutes, 60)
        buttons.append(f"{hour:02d}:{minute:02d}")
    rows = [buttons[index:index + 4] for index in range(0, len(buttons), 4)]
    rows.append(["Назад"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Выбери направление и время — я покажу ближайшие 3 рейса №451 и №2198.",
        reply_markup=keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def season_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    command = update.message.text.lower().split()[0]
    if command == "/summer":
        context.user_data["season"] = "summer"
        text = "летний"
    elif command == "/winter":
        context.user_data["season"] = "winter"
        text = "зимний"
    else:
        context.user_data.pop("season", None)
        text = "автоматический"
    await update.message.reply_text(f"Режим сезона: {text}. Выбери направление.", reply_markup=keyboard())


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text
    button_text = text.strip().lower()
    if button_text == "выбрать время":
        await update.message.reply_text("Выбери время с шагом 30 минут:", reply_markup=time_keyboard())
        return
    if button_text == "назад":
        await update.message.reply_text("Главное меню.", reply_markup=keyboard())
        return
    direction, offset_minutes, season, route, requested_time = parse_query(text)
    if text.lower() in {"помощь", "/help"}:
        await help_command(update, context)
        return
    if text.lower() == "до острошицкого городка":
        direction = "to_ostroshitsky"
    elif text.lower() == "до ст. метро восток":
        direction = "to_vostok"
    if direction is not None:
        context.user_data["last_direction"] = direction
    elif requested_time is not None:
        direction = context.user_data.get("last_direction")
    if direction is None:
        await update.message.reply_text("Не понял направление. Напиши «до ст. метро Восток» или «до Острошицкого городка».", reply_markup=keyboard())
        return

    season = season or context.user_data.get("season")
    now = datetime.now(timezone())
    if requested_time is not None:
        now = now.replace(
            hour=requested_time.hour,
            minute=requested_time.minute,
            second=0,
            microsecond=0,
        )
        if now < datetime.now(timezone()):
            now += timedelta(days=1)
    else:
        now += timedelta(minutes=offset_minutes)
    items = next_departures(direction, now, limit=3, season_override=season, route_filter=route)
    answer = format_departures(items, direction, now)
    if offset_minutes:
        answer = f"Проверяю от времени через {offset_minutes} мин.\n\n" + answer
    elif requested_time is not None:
        answer = f"Проверяю от {requested_time:%H:%M}.\n\n" + answer
    await update.message.reply_text(answer, reply_markup=keyboard())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Ошибка при обработке сообщения", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Произошла ошибка при расчёте. Посмотри подробность в окне командной строки.")


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задан BOT_TOKEN. Создай .env по примеру .env.example.")
    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler(["summer", "winter", "auto"], season_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(error_handler)
    app.run_polling()


if __name__ == "__main__":
    main()
