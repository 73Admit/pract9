# -*- coding: utf-8 -*-
"""Веб-интерфейс рекомендательной системы (Flask)."""
from __future__ import annotations

import os
import uuid

from flask import Flask, render_template, request, session, redirect, url_for, flash

import recommender
import personal
import storage

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'steam-recsys-pr9-secret')

GAMES = recommender.load_games()
storage.init_db()


def current_user() -> str:
    """Каждому посетителю выдаётся постоянный идентификатор в cookie-сессии."""
    if 'user_id' not in session:
        session['user_id'] = 'user_' + uuid.uuid4().hex[:8]
    return session['user_id']


@app.route('/', methods=['GET', 'POST'])
def index():
    user = current_user()
    results, parsed, query = [], None, ''
    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        top_n = int(request.form.get('top_n', 5))
        if query:
            results, parsed = recommender.recommend(GAMES, query, top_n)
            storage.log_query(user, query, parsed['genres'],
                              results[0] if results else None, source='web')
    return render_template('index.html', results=results, parsed=parsed,
                           query=query, user=user, games_count=len(GAMES))


@app.route('/search')
def search():
    user = current_user()
    name = request.args.get('name', '').strip()
    found = recommender.search_by_name(GAMES, name) if name else []
    return render_template('search.html', found=found, name=name, user=user)


@app.route('/range')
def range_search():
    user = current_user()
    field = request.args.get('field', 'price')
    low = request.args.get('low', type=float)
    high = request.args.get('high', type=float)
    found = []
    if low is not None and high is not None:
        found = recommender.search_by_range(GAMES, field, low, high, limit=20)
    return render_template('range.html', found=found, field=field, low=low, high=high,
                           fields=recommender.RANGE_FIELDS, user=user)


@app.route('/weak')
def weak():
    return render_template('weak.html', found=recommender.weak_games(GAMES, 10),
                           user=current_user())


@app.route('/review', methods=['GET', 'POST'])
def review():
    user = current_user()
    if request.method == 'POST':
        app_id = int(request.form['app_id'])
        rating = int(request.form['rating'])
        text = request.form.get('text', '').strip()
        row = GAMES[GAMES['steam_appid'] == app_id]
        name = row.iloc[0]['name'] if len(row) else f'app {app_id}'
        storage.add_review(user, app_id, name, rating, text)
        flash(f'Отзыв на «{name}» сохранён')
        return redirect(url_for('review'))
    return render_template('review.html', reviews=storage.get_reviews(limit=30),
                           stats=storage.review_stats(), user=user)


@app.route('/stats')
def stats():
    return render_template('stats.html', qstats=storage.query_stats(),
                           rstats=storage.review_stats(), user=current_user())


@app.route('/personal')
def personal_page():
    user = current_user()
    recs, note = personal.personal_recommend(user, GAMES)
    history = storage.user_history(user, limit=15)
    return render_template('personal.html', recs=recs, note=note,
                           history=history, user=user)


@app.route('/train', methods=['POST'])
def train():
    info = personal.train_model(GAMES)
    flash('Модель обучена: ' + str(info) if info.get('trained')
          else 'Обучение невозможно: ' + info.get('reason', ''))
    return redirect(url_for('personal_page'))


if __name__ == '__main__':
    app.run(debug=False, port=5000)
