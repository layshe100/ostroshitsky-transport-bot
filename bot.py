from __future__ import annotations

import os
import re
import logging
from datetime import datetime, time as dt_time, timedelta

from dotenv import load_dotenv
from telegram import BotCommand, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from schedule import format_departures, next_departures, timezone


load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)


DIRECTION_LABELS = {
    "to_ostroshitsky": "Восток → Острошицкий городок",
    "to_vostok": "Острошицкий городок → Восток",
}

TIME_PRESETS = {
    "утром": dt_time(5, 0),
    "днём": dt_time(12, 0),
    "днем": dt_time(12, 0),
    "вечером": dt_time(18, 0),
}


def direction_label(direction: str) -> str:
    return DIRECTION_LABELS.get(direction, "направление не выбрано")


def parse_query(
    text: str,
    last_direction: str | None = None,
) -> tuple[str | None, int, str | None, str | None, dt_time | None]:
    normalized = text.lower().replace("ё", "е")
    direction = None

    if re.search(r"\bдомой\b|\bдо\s+острош\w*|\bв\s+острош\w*|\bв\s+городок\b", normalized):
        direction = "to_ostroshitsky"
    elif re.search(r"\b(?:до\s+(?:ст\.?\s*м\.?\s*)?восток|до\s+метро|на\s+восток|в\s+минск|в\s+город)\b", normalized):
        direction = "to_vostok"
    elif re.search(r"\b(?:я|сейчас|нахожусь)\s+(?:на|у)\s+восток(?:е|а)\b", normalized):
        direction = "to_ostroshitsky"
    elif re.search(r"\b(?:я|сейчас|нахожусь)\s+(?:в|на)\s+острош", normalized):
        direction = "to_vostok"
    elif re.search(r"\bиз\s+острош", normalized):
        direction = "to_vostok"
    elif re.search(r"\bиз\s+(?:минска|города)\b", normalized):
        direction = "to_ostroshitsky"
    elif re.search(r"\bобратно\b", normalized) and last_direction:
        direction = "to_vostok" if last_direction == "to_ostroshitsky" else "to_ostroshitsky"
    elif re.search(r"\bтуда\b", normalized) and last_direction:
        direction = last_direction
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

    offset_match = re.search(r"через\s+(\d+)\s*(?:мин|минут|минуты|минуту|час|часа|ч)?", normalized)
    offset_minutes = int(offset_match.group(1)) if offset_match else 0
    if re.search(r"через\s+полчаса", normalized):
        offset_minutes = 30
    elif offset_match and re.search(r"через\s+\d+\s*(?:час|часа|ч)\b", normalized):
        offset_minutes *= 60

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
        [
            ["До Острошицкого городка", "До ст. метро Восток"],
            ["Выбрать время"],
            ["Помощь", "Сообщить об изменении"],
        ],
        resize_keyboard=True,
    )


def time_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["Через 30 минут", "Через 1 час"],
            ["Утром", "Днём", "Вечером"],
            ["Ввести время"],
            ["🔄 Сменить направление", "Назад"],
        ],
        resize_keyboard=True,
    )


def time_input_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Выбери направление и время — я покажу ближайшие 3 рейса №451 и №2198.",
        reply_markup=keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Помощь\n\n"
        "Бот показывает ближайшие 3 отправления автобуса №451 и маршрутки №2198 "
        "между ст. метро Восток и Острошицким городком.\n\n"
        "Время берётся из расписания, транспорт в реальном времени бот не отслеживает.\n"
        "Фактическое время прибытия может отличаться.\n\n"
        "Расписание обновлено 20.08.2026.\n"
        "Источник: фотографии расписания на остановках.\n\n"
        "Команды:\n"
        "/start — запустить бота\n"
        "/next — ближайшие рейсы\n"
        "/time — выбрать время\n"
        "/help — помощь\n"
        "/feedback — сообщить об изменении или ошибке",
        reply_markup=keyboard(),
    )


async def show_time_selector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    direction = context.user_data.get("last_direction")
    if direction is None:
        await update.message.reply_text(
            "Сначала выбери направление, затем нажми «Выбрать время».",
            reply_markup=keyboard(),
        )
        return
    await update.message.reply_text(
        f"Выбрано направление: {direction_label(direction)}.\nНа какое время искать транспорт?",
        reply_markup=time_keyboard(),
    )


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting_feedback"] = True
    await update.message.reply_text(
        "Напиши следующим сообщением, что изменилось в расписании или что работает неправильно.",
        reply_markup=time_input_keyboard(),
    )


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


async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    direction = context.user_data.get("last_direction")
    if direction is None:
        await update.message.reply_text("Сначала выбери направление.", reply_markup=keyboard())
        return
    now = datetime.now(timezone())
    items = next_departures(
        direction,
        now,
        limit=3,
        season_override=context.user_data.get("season"),
    )
    await update.message.reply_text(format_departures(items, direction, now), reply_markup=keyboard())


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text
    button_text = text.strip().lower()

    if context.user_data.get("awaiting_feedback"):
        if button_text in {"назад", "отмена"}:
            context.user_data.pop("awaiting_feedback", None)
            await update.message.reply_text("Главное меню.", reply_markup=keyboard())
            return
        context.user_data.pop("awaiting_feedback", None)
        logging.info("FEEDBACK user_id=%s text=%s", update.effective_user.id if update.effective_user else "unknown", text)
        await update.message.reply_text(
            "Спасибо! Сообщение принято и будет учтено при проверке расписания.",
            reply_markup=keyboard(),
        )
        return

    if button_text in {"помощь", "/help"}:
        await help_command(update, context)
        return
    if button_text in {"сообщить об изменении", "/feedback"}:
        await feedback_command(update, context)
        return
    if button_text in {"выбрать время", "/time"}:
        await show_time_selector(update, context)
        return
    if button_text == "🔄 сменить направление":
        context.user_data.pop("last_direction", None)
        await update.message.reply_text("Выбери новое направление.", reply_markup=keyboard())
        return
    if button_text == "назад":
        context.user_data.pop("awaiting_time", None)
        await update.message.reply_text("Главное меню.", reply_markup=keyboard())
        return
    if button_text == "ввести время":
        context.user_data["awaiting_time"] = True
        await update.message.reply_text(
            "Введи время в формате ЧЧ:ММ, например 18:00.",
            reply_markup=time_input_keyboard(),
        )
        return

    direction, offset_minutes, season, route, requested_time = parse_query(
        text,
        last_direction=context.user_data.get("last_direction"),
    )
    if button_text in TIME_PRESETS:
        requested_time = TIME_PRESETS[button_text]
    if button_text == "через 30 минут":
        offset_minutes = 30
    elif button_text == "через 1 час":
        offset_minutes = 60

    if button_text == "до острошицкого городка":
        direction = "to_ostroshitsky"
    elif button_text == "до ст. метро восток":
        direction = "to_vostok"

    if direction is not None:
        context.user_data["last_direction"] = direction
    elif requested_time is not None or offset_minutes:
        direction = context.user_data.get("last_direction")
    if direction is None:
        await update.message.reply_text(
            "Не понял направление. Выбери кнопку или напиши «домой», «в город», «на Восток», "
            "«из Острошицкого» или «из Минска».",
            reply_markup=keyboard(),
        )
        return

    context.user_data.pop("awaiting_time", None)
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
    await update.message.reply_text(format_departures(items, direction, now), reply_markup=keyboard())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Ошибка при обработке сообщения", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Не получилось рассчитать рейсы. Попробуй ещё раз или сообщи об ошибке через «Сообщить об изменении».")


async def set_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "запустить бота"),
            BotCommand("next", "ближайшие рейсы"),
            BotCommand("time", "выбрать время"),
            BotCommand("help", "помощь"),
            BotCommand("feedback", "сообщить об ошибке"),
        ]
    )


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
        .post_init(set_bot_commands)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("next", next_command))
    app.add_handler(CommandHandler("time", show_time_selector))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("feedback", feedback_command))
    app.add_handler(CommandHandler(["summer", "winter", "auto"], season_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(error_handler)
    app.run_polling()


if __name__ == "__main__":
    main()
