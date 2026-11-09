# -*- coding: utf-8 -*-
"""Хранилище истории запросов и отзывов (SQLite)."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'recsys.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   TEXT    NOT NULL,
    query     TEXT    NOT NULL,
    genres    TEXT,
    top_app   INTEGER,
    top_name  TEXT,
    source    TEXT,
    created   TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   TEXT    NOT NULL,
    app_id    INTEGER NOT NULL,
    name      TEXT,
    rating    INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    text      TEXT,
    created   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queries_user ON queries(user_id);
CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


def log_query(user_id: str, query: str, genres: list[str], top: dict | None,
              source: str = 'web') -> None:
    with connect() as con:
        con.execute(
            'INSERT INTO queries (user_id, query, genres, top_app, top_name, source, created)'
            ' VALUES (?,?,?,?,?,?,?)',
            (user_id, query, ','.join(genres),
             top['app_id'] if top else None, top['name'] if top else None,
             source, datetime.now().isoformat(timespec='seconds')))


def add_review(user_id: str, app_id: int, name: str, rating: int, text: str) -> None:
    with connect() as con:
        con.execute(
            'INSERT INTO reviews (user_id, app_id, name, rating, text, created)'
            ' VALUES (?,?,?,?,?,?)',
            (user_id, int(app_id), name, int(rating), text,
             datetime.now().isoformat(timespec='seconds')))


def get_reviews(app_id: int | None = None, user_id: str | None = None,
                limit: int = 100) -> list[dict]:
    sql = 'SELECT * FROM reviews'
    cond, args = [], []
    if app_id is not None:
        cond.append('app_id = ?'); args.append(int(app_id))
    if user_id is not None:
        cond.append('user_id = ?'); args.append(user_id)
    if cond:
        sql += ' WHERE ' + ' AND '.join(cond)
    sql += ' ORDER BY id DESC LIMIT ?'
    args.append(limit)
    with connect() as con:
        return [dict(r) for r in con.execute(sql, args)]


def review_stats(limit: int = 20) -> list[dict]:
    """Статистика по играм: количество отзывов и средняя оценка."""
    with connect() as con:
        rows = con.execute(
            'SELECT app_id, name, COUNT(*) AS cnt, ROUND(AVG(rating), 2) AS avg_rating,'
            ' MIN(rating) AS min_rating, MAX(rating) AS max_rating'
            ' FROM reviews GROUP BY app_id, name ORDER BY cnt DESC, avg_rating DESC'
            ' LIMIT ?', (limit,))
        return [dict(r) for r in rows]


def query_stats(limit: int = 15) -> dict:
    """Статистика по ранее введённым запросам."""
    with connect() as con:
        total = con.execute('SELECT COUNT(*) AS c FROM queries').fetchone()['c']
        users = con.execute('SELECT COUNT(DISTINCT user_id) AS c FROM queries').fetchone()['c']
        top_q = [dict(r) for r in con.execute(
            'SELECT query, COUNT(*) AS cnt FROM queries GROUP BY query'
            ' ORDER BY cnt DESC LIMIT ?', (limit,))]
        rows = con.execute('SELECT genres FROM queries WHERE genres != ""').fetchall()
        recent = [dict(r) for r in con.execute(
            'SELECT query, top_name, source, created FROM queries'
            ' ORDER BY id DESC LIMIT ?', (limit,))]
    counter: dict[str, int] = {}
    for r in rows:
        for g in r['genres'].split(','):
            if g:
                counter[g] = counter.get(g, 0) + 1
    top_genres = sorted(counter.items(), key=lambda kv: -kv[1])[:limit]
    return {'total': total, 'users': users, 'top_queries': top_q,
            'top_genres': top_genres, 'recent': recent}


def user_history(user_id: str, limit: int = 50) -> dict:
    with connect() as con:
        queries = [dict(r) for r in con.execute(
            'SELECT * FROM queries WHERE user_id = ? ORDER BY id DESC LIMIT ?',
            (user_id, limit))]
        reviews = [dict(r) for r in con.execute(
            'SELECT * FROM reviews WHERE user_id = ? ORDER BY id DESC LIMIT ?',
            (user_id, limit))]
    return {'queries': queries, 'reviews': reviews}


if __name__ == '__main__':
    init_db()
    print('База данных создана:', DB_PATH)
