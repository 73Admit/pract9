# -*- coding: utf-8 -*-
"""Telegram-бот рекомендательной системы (python-telegram-bot).

Токен бота берётся из переменной окружения BOT_TOKEN (файл .env).
Получить токен: написать @BotFather команду /newbot и следовать инструкции.

Команды бота:
    /start              — приветствие и справка
    /help               — список команд
    /find <запрос>      — подбор топ-5 игр по текстовому запросу
    /name <подстрока>   — поиск игры по названию
    /range <поле> <от> <до> — поиск по диапазону характеристик
    /weak               — топ самых слабых игр
    /review <appid> <1-5> <текст> — оставить отзыв
    /my                 — персональные рекомендации
    /stats              — статистика запросов и отзывов
Любое сообщение без команды обрабатывается как запрос на подбор.
"""
from __future__ import annotations

import os
import logging

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          ContextTypes, filters)

import personal
import recommender
import storage

load_dotenv()
TOKEN = os.environ.get('BOT_TOKEN', '')

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
# Библиотека httpx пишет в лог полный URL запроса вместе с токеном бота,
# поэтому её сообщения приглушаем: в журнал не должны попадать секреты.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram.ext.Updater').setLevel(logging.WARNING)
log = logging.getLogger('recsys-bot')

GAMES = recommender.load_games()
storage.init_db()

HELP = (
    '<b>Рекомендательная система по играм Steam</b>\n'
    f'В каталоге {len(GAMES)} игр.\n\n'
    'Просто напишите, что хотите найти, например:\n'
    '<i>дешёвая новая инди рпг с кооперативом</i>\n\n'
    'Команды:\n'
    '/find запрос — подбор топ-5 игр\n'
    '/name текст — поиск по названию\n'
    '/range поле от до — поиск по диапазону (price, rating, avg_online, release_year)\n'
    '/weak — топ самых слабых игр\n'
    '/review appid оценка текст — оставить отзыв\n'
    '/my — персональные рекомендации\n'
    '/stats — статистика запросов'
)


def uid(update: Update) -> str:
    return f'tg_{update.effective_user.id}'


def format_results(results: list[dict]) -> str:
    if not results:
        return 'По этому запросу ничего не найдено.'
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"<b>{i}. {r['name']}</b>\n"
            f"   {r['genres']} · {r['year']} г.\n"
            f"   цена {r['price']:.2f} $ · рейтинг {r['rating']} % · "
            f"онлайн {r['online']:.0f}\n"
            f"   совместимость: <b>{r['match']} %</b> ({r['score']} баллов)")
    return '\n\n'.join(lines)


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def cmd_find(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = ' '.join(context.args) if context.args else ''
    if not query:
        await update.message.reply_text('Напишите запрос: /find популярный бесплатный шутер')
        return
    await answer_query(update, query)


async def answer_query(update: Update, query: str) -> None:
    results, parsed = recommender.recommend(GAMES, query, 5)
    storage.log_query(uid(update), query, parsed['genres'],
                      results[0] if results else None, source='telegram')
    header = (f"Распознано: жанры {', '.join(parsed['genres']) or '—'}; "
              f"характеристики {', '.join(f[3] for f in parsed['features']) or '—'}\n\n")
    # «Пищание» в мессенджере — уведомление со звуком (disable_notification=False)
    await update.message.reply_text(header + format_results(results),
                                    parse_mode=ParseMode.HTML,
                                    disable_notification=False)


async def cmd_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = ' '.join(context.args)
    if not text:
        await update.message.reply_text('Формат: /name Counter')
        return
    found = recommender.search_by_name(GAMES, text, limit=8)
    if not found:
        await update.message.reply_text('Ничего не найдено.')
        return
    lines = [f"<code>{g['steam_appid']}</code> <b>{g['name']}</b> — {g['genres_str']}, "
             f"{g['price']:.2f} $, рейтинг {g['rating']} %" for g in found]
    await update.message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML)


async def cmd_range(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 3:
        await update.message.reply_text(
            'Формат: /range price 0 5\nПоля: ' + ', '.join(recommender.RANGE_FIELDS))
        return
    field, low, high = context.args[0], float(context.args[1]), float(context.args[2])
    try:
        found = recommender.search_by_range(GAMES, field, low, high, limit=8)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    lines = [f"<b>{g['name']}</b> — {g['price']:.2f} $, рейтинг {g['rating']} %, "
             f"онлайн {g['avg_online']:.0f}, {g['release_year']} г." for g in found]
    await update.message.reply_text('\n'.join(lines) or 'Ничего не найдено.',
                                    parse_mode=ParseMode.HTML)


async def cmd_weak(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    found = recommender.weak_games(GAMES, 8)
    lines = [f"{i}. <b>{g['name']}</b> — рейтинг {g['rating']} %, "
             f"негативных отзывов {g['total_negative']}"
             for i, g in enumerate(found, 1)]
    await update.message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML)


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text('Формат: /review 730 5 отличная игра')
        return
    app_id, rating = int(context.args[0]), int(context.args[1])
    text = ' '.join(context.args[2:])
    row = GAMES[GAMES['steam_appid'] == app_id]
    name = row.iloc[0]['name'] if len(row) else f'app {app_id}'
    storage.add_review(uid(update), app_id, name, rating, text)
    await update.message.reply_text(f'Отзыв на «{name}» с оценкой {rating} сохранён.')


async def cmd_my(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    recs, note = personal.personal_recommend(uid(update), GAMES)
    text = note if not recs else note + '\n\n' + format_results(recs)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_stats(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    qs = storage.query_stats()
    lines = [f"Всего запросов: <b>{qs['total']}</b>, пользователей: <b>{qs['users']}</b>", '',
             'Частые запросы:']
    lines += [f"  {q['query']} — {q['cnt']}" for q in qs['top_queries'][:5]]
    lines += ['', 'Популярные жанры:']
    lines += [f'  {g} — {c}' for g, c in qs['top_genres'][:5]]
    await update.message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML)


async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_query(update, update.message.text)


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            'Не задан BOT_TOKEN. Создайте файл .env рядом с bot.py и впишите строку\n'
            'BOT_TOKEN=токен_от_BotFather')
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler(['start', 'help'], cmd_start))
    app.add_handler(CommandHandler('find', cmd_find))
    app.add_handler(CommandHandler('name', cmd_name))
    app.add_handler(CommandHandler('range', cmd_range))
    app.add_handler(CommandHandler('weak', cmd_weak))
    app.add_handler(CommandHandler('review', cmd_review))
    app.add_handler(CommandHandler('my', cmd_my))
    app.add_handler(CommandHandler('stats', cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info('Бот запущен, ожидает сообщения')
    app.run_polling()


if __name__ == '__main__':
    main()
