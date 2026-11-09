# -*- coding: utf-8 -*-
"""Персональные рекомендации и обучение модели на истории пользователя.

Два механизма:
1. Профиль интересов — накопленные веса жанров из запросов и оценок пользователя.
2. Обученная модель — логистическая регрессия, предсказывающая, понравится ли игра
   (оценка 4–5) по её признакам. Обучается на всех отзывах из базы.
"""
from __future__ import annotations

import os
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import storage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'data', 'like_model.pkl')

NUM_FEATURES = ['n_popularity', 'n_online', 'n_fresh', 'n_cheap', 'n_free',
                'n_rating', 'n_multi', 'n_single', 'n_achievements']
MIN_REVIEWS = 10          # меньше этого обучать модель бессмысленно
MIN_HISTORY = 2           # с какого числа действий строим личный профиль


# --------------------------------------------------------------------------- #
#  Профиль интересов пользователя
# --------------------------------------------------------------------------- #

def build_profile(user_id: str, games: pd.DataFrame) -> dict[str, float]:
    """Веса жанров: +1 за каждый запрос с жанром, +оценка/5 за каждый отзыв."""
    hist = storage.user_history(user_id)
    weights: dict[str, float] = {}

    for q in hist['queries']:
        for g in (q['genres'] or '').split(','):
            if g:
                weights[g] = weights.get(g, 0) + 1.0

    by_id = games.set_index('steam_appid')
    for r in hist['reviews']:
        if r['app_id'] in by_id.index:
            row = by_id.loc[r['app_id']]
            genres = row['genres_list'] if isinstance(row['genres_list'], list) else []
            for g in genres:
                weights[g] = weights.get(g, 0) + (r['rating'] - 3) / 2
    return weights


def personal_recommend(user_id: str, games: pd.DataFrame, top_n: int = 5) -> tuple[list[dict], str]:
    """Рекомендации под конкретного пользователя на основе его истории."""
    profile = build_profile(user_id, games)
    hist = storage.user_history(user_id)
    actions = len(hist['queries']) + len(hist['reviews'])
    if actions < MIN_HISTORY or not profile:
        return [], ('Недостаточно истории: сделайте хотя бы два запроса '
                    'или оставьте отзыв, чтобы система узнала ваши вкусы.')

    seen = {r['app_id'] for r in hist['reviews']}
    score = pd.Series(0.0, index=games.index)
    for genre, w in profile.items():
        if w <= 0:
            continue
        score += games['genres_list'].apply(lambda g, gn=genre: 1.0 if gn in g else 0.0) * w
    score += games['n_rating'] * 2 + games['n_popularity']

    model = load_model()
    note = 'Рекомендации построены по профилю интересов.'
    if model is not None:
        proba = model.predict_proba(games[NUM_FEATURES])[:, 1]
        score += pd.Series(proba, index=games.index) * 3
        note = ('Рекомендации построены по профилю интересов и обученной модели '
                'предпочтений.')

    work = games.assign(score=score)
    work = work[~work['steam_appid'].isin(seen)]
    top = work.sort_values('score', ascending=False).head(top_n)

    out = []
    best = float(top['score'].max()) or 1.0
    for _, row in top.iterrows():
        matched = [g for g in row['genres_list'] if profile.get(g, 0) > 0]
        out.append({
            'app_id': int(row['steam_appid']), 'name': row['name'],
            'genres': row['genres_str'], 'year': int(row['release_year']),
            'price': float(row['price']), 'rating': float(row['rating']),
            'online': float(row['avg_online']),
            'score': round(float(row['score']), 2),
            'match': round(float(row['score']) / best * 100, 1),
            'why': [f'ваши жанры: {", ".join(matched)}'] if matched else ['высокий рейтинг'],
        })
    top_genres = sorted(profile.items(), key=lambda kv: -kv[1])[:5]
    note += ' Ваши интересы: ' + ', '.join(f'{g} ({w:+.1f})' for g, w in top_genres)
    return out, note


# --------------------------------------------------------------------------- #
#  Обучение модели предпочтений
# --------------------------------------------------------------------------- #

def train_model(games: pd.DataFrame) -> dict:
    """Обучает логистическую регрессию «понравится / не понравится» на отзывах."""
    reviews = storage.get_reviews(limit=100_000)
    if len(reviews) < MIN_REVIEWS:
        return {'trained': False,
                'reason': f'в базе {len(reviews)} отзывов, нужно минимум {MIN_REVIEWS}'}

    rev = pd.DataFrame(reviews)
    data = rev.merge(games, left_on='app_id', right_on='steam_appid', how='inner')
    if len(data) < MIN_REVIEWS:
        return {'trained': False, 'reason': 'отзывы не сопоставились с каталогом'}

    y = (data['rating_x'] >= 4).astype(int)
    if y.nunique() < 2:
        return {'trained': False, 'reason': 'в отзывах только один класс оценок'}

    X = data[NUM_FEATURES]
    model = Pipeline([('scaler', StandardScaler()),
                      ('clf', LogisticRegression(max_iter=1000, class_weight='balanced'))])
    model.fit(X, y)
    acc = float(model.score(X, y))
    joblib.dump(model, MODEL_PATH)

    coefs = dict(zip(NUM_FEATURES,
                     np.round(model.named_steps['clf'].coef_[0], 3).tolist()))
    return {'trained': True, 'samples': len(data), 'accuracy': round(acc, 3),
            'positive_share': round(float(y.mean()), 3), 'coefficients': coefs}


def load_model():
    if os.path.exists(MODEL_PATH):
        try:
            return joblib.load(MODEL_PATH)
        except Exception:
            return None
    return None


if __name__ == '__main__':
    import recommender
    storage.init_db()
    print(train_model(recommender.load_games()))
