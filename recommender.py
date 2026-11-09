# -*- coding: utf-8 -*-
"""Ядро рекомендательной системы по играм Steam.

Метод взвешенного перебора: для каждого запроса пользователя система перебирает
все игры каталога, начисляет каждой баллы за совпадение жанра и за ключевые слова,
после чего возвращает топ-N игр с процентом совместимости.
"""
from __future__ import annotations

import os
import re
import math
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAMES_CSV = os.path.join(BASE_DIR, 'data', 'games.csv')

# --------------------------------------------------------------------------- #
#  Словари ключевых слов
# --------------------------------------------------------------------------- #

# Жанр — самый весомый признак: совпадение даёт 45 баллов (по ТЗ 40–50)
GENRE_SCORE = 45

GENRE_WORDS = {
    'Action': ['экшен', 'экшн', 'боевик', 'шутер', 'стрелялка', 'action'],
    'Adventure': ['приключени', 'адвенчур', 'adventure', 'квест'],
    'RPG': ['рпг', 'ролев', 'rpg'],
    'Strategy': ['стратеги', 'strategy', 'тактик'],
    'Simulation': ['симулятор', 'симуляц', 'simulation'],
    'Indie': ['инди', 'indie', 'независим'],
    'Casual': ['казуальн', 'простая', 'casual', 'лёгкая', 'легкая'],
    'Racing': ['гонк', 'racing', 'автосим'],
    'Sports': ['спорт', 'sports', 'футбол', 'хоккей'],
    'Massively Multiplayer': ['ммо', 'mmo', 'массов'],
    'Free To Play': ['free', 'фритуплей'],
    'Early Access': ['ранний доступ', 'early access'],
    'Violent': ['жесток', 'кровав'],
    'Gore': ['гор', 'расчленен'],
}

# Характеристики: ключевое слово -> (поле, направление, максимум баллов)
FEATURE_WORDS = {
    'популярн': ('popularity', +1, 35),
    'известн': ('popularity', +1, 35),
    'топов': ('popularity', +1, 35),
    'онлайн': ('online', +1, 30),
    'живая': ('online', +1, 30),
    'нов': ('fresh', +1, 25),
    'свеж': ('fresh', +1, 25),
    'стар': ('fresh', -1, 20),
    'классик': ('fresh', -1, 20),
    'дешёв': ('cheap', +1, 25),
    'дешев': ('cheap', +1, 25),
    'недорог': ('cheap', +1, 25),
    'бесплатн': ('free', +1, 30),
    'дорог': ('cheap', -1, 15),
    'оценён': ('rating', +1, 30),
    'оценен': ('rating', +1, 30),
    'рейтинг': ('rating', +1, 30),
    'хорош': ('rating', +1, 30),
    'качествен': ('rating', +1, 30),
    'кооператив': ('multi', +1, 25),
    'мультиплеер': ('multi', +1, 25),
    'совместн': ('multi', +1, 25),
    'сетев': ('multi', +1, 25),
    'одиночн': ('single', +1, 25),
    'сюжетн': ('single', +1, 20),
    'достижени': ('achievements', +1, 15),
    'ачивк': ('achievements', +1, 15),
}

SORT_HINTS = {'слаб': 'weak', 'худш': 'weak', 'плох': 'weak', 'непопулярн': 'weak'}


# --------------------------------------------------------------------------- #
#  Загрузка и нормализация каталога
# --------------------------------------------------------------------------- #

def load_games(path: str = GAMES_CSV) -> pd.DataFrame:
    """Читает каталог игр и добавляет нормированные признаки 0..1 для начисления баллов."""
    df = pd.read_csv(path)
    df['genres_list'] = df['genres_str'].fillna('').apply(
        lambda s: [g.strip() for g in s.split(',') if g.strip()])

    # Нормированные характеристики: чем ближе к 1, тем сильнее выражен признак
    df['n_popularity'] = _norm_log(df['total_reviews'])
    df['n_online'] = _norm_log(df['avg_online'])
    df['n_fresh'] = _minmax(df['release_year'])
    df['n_cheap'] = 1 - _minmax(df['price'].clip(upper=60))
    df['n_free'] = (df['price'] == 0).astype(float)
    df['n_rating'] = (df['rating'] / 100).clip(0, 1)
    df['n_multi'] = df['is_multiplayer'].astype(float)
    df['n_single'] = df['is_singleplayer'].astype(float)
    df['n_achievements'] = df['has_achievements'].astype(float)
    return df


def _norm_log(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s, errors='coerce').fillna(0).clip(lower=0)
    v = (v + 1).apply(math.log)
    return (v - v.min()) / (v.max() - v.min() + 1e-9)


def _minmax(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s, errors='coerce').fillna(0)
    return (v - v.min()) / (v.max() - v.min() + 1e-9)


# --------------------------------------------------------------------------- #
#  Разбор запроса
# --------------------------------------------------------------------------- #

def parse_query(query: str) -> dict:
    """Разбирает текстовый запрос: находит жанры, характеристики и режим сортировки."""
    q = query.lower().replace('ё', 'е')
    genres, features = [], []

    for genre, words in GENRE_WORDS.items():
        if any(w.replace('ё', 'е') in q for w in words):
            genres.append(genre)

    for word, (field, direction, weight) in FEATURE_WORDS.items():
        if word.replace('ё', 'е') in q:
            features.append((field, direction, weight, word))

    mode = 'top'
    for word, m in SORT_HINTS.items():
        if word in q:
            mode = m
    return {'query': query, 'genres': genres, 'features': features, 'mode': mode}


def max_possible_score(parsed: dict) -> float:
    """Максимум баллов, который теоретически может набрать игра по этому запросу."""
    total = GENRE_SCORE * len(parsed['genres'])
    total += sum(w for _, _, w, _ in parsed['features'])
    return max(total, 1.0)


# --------------------------------------------------------------------------- #
#  Начисление баллов и рекомендации
# --------------------------------------------------------------------------- #

def score_games(df: pd.DataFrame, parsed: dict) -> pd.Series:
    """Взвешенный перебор: начисляет баллы всем играм каталога сразу (векторно)."""
    score = pd.Series(0.0, index=df.index)

    for genre in parsed['genres']:
        score += df['genres_list'].apply(lambda g, gn=genre: GENRE_SCORE if gn in g else 0)

    for field, direction, weight, _ in parsed['features']:
        col = f'n_{field}'
        if col not in df.columns:
            continue
        value = df[col] if direction > 0 else (1 - df[col])
        score += value * weight

    # Небольшая добавка за общее качество, чтобы при равенстве баллов выше шли
    # игры с лучшим рейтингом — не более 5 баллов
    score += df['n_rating'] * 5
    return score


def explain(row: pd.Series, parsed: dict) -> list[str]:
    """Расшифровывает, за что игра получила баллы."""
    parts = []
    for genre in parsed['genres']:
        if genre in row['genres_list']:
            parts.append(f'жанр {genre}: +{GENRE_SCORE}')
    for field, direction, weight, word in parsed['features']:
        col = f'n_{field}'
        if col in row:
            v = row[col] if direction > 0 else (1 - row[col])
            parts.append(f'«{word}»: +{v * weight:.1f}')
    return parts


def recommend(df: pd.DataFrame, query: str, top_n: int = 5) -> tuple[list[dict], dict]:
    """Главная функция: возвращает топ-N игр с процентом совместимости."""
    parsed = parse_query(query)
    scores = score_games(df, parsed)
    best = max_possible_score(parsed) + 5

    work = df.assign(score=scores)
    ascending = parsed['mode'] == 'weak'
    work = work.sort_values('score', ascending=ascending).head(top_n)

    result = []
    for _, row in work.iterrows():
        result.append({
            'app_id': int(row['steam_appid']),
            'name': row['name'],
            'genres': row['genres_str'],
            'year': int(row['release_year']),
            'price': float(row['price']),
            'rating': float(row['rating']),
            'reviews': int(row['total_reviews']),
            'online': float(row['avg_online']),
            'score': round(float(row['score']), 1),
            'match': round(min(float(row['score']) / best * 100, 100), 1),
            'why': explain(row, parsed),
        })
    return result, parsed


# --------------------------------------------------------------------------- #
#  Дополнительные режимы поиска
# --------------------------------------------------------------------------- #

def search_by_name(df: pd.DataFrame, text: str, limit: int = 10) -> list[dict]:
    """Поиск игры по названию (подстрока, без учёта регистра)."""
    mask = df['name'].str.contains(re.escape(text), case=False, na=False)
    found = df[mask].sort_values('total_reviews', ascending=False).head(limit)
    return found.to_dict('records')


def search_by_range(df: pd.DataFrame, field: str, low: float, high: float,
                    limit: int = 10) -> list[dict]:
    """Поиск по диапазону характеристики: цена, рейтинг, онлайн, год, отзывы."""
    if field not in df.columns:
        raise ValueError(f'Неизвестная характеристика: {field}')
    mask = df[field].between(low, high)
    found = df[mask].sort_values('total_reviews', ascending=False).head(limit)
    return found.to_dict('records')


def weak_games(df: pd.DataFrame, limit: int = 5) -> list[dict]:
    """Топ самых слабых игр: низкий рейтинг при заметном числе отзывов."""
    work = df[df['total_reviews'] >= 100].copy()
    work['weakness'] = (100 - work['rating']) + (work['total_negative'] /
                                                 work['total_reviews'] * 100)
    found = work.sort_values('weakness', ascending=False).head(limit)
    return found.to_dict('records')


RANGE_FIELDS = {
    'price': 'цена, $',
    'rating': 'рейтинг, %',
    'avg_online': 'средний онлайн, чел.',
    'release_year': 'год выпуска',
    'total_reviews': 'количество отзывов',
}
