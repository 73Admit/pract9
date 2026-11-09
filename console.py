# -*- coding: utf-8 -*-
"""Консольный режим рекомендательной системы с циклом ввода запросов.

Поддерживаемые команды:
    <текст запроса>      — подбор топ-5 игр
    имя <подстрока>      — поиск игры по названию
    диапазон <поле> <от> <до>  — поиск по диапазону характеристик
    слабые               — топ самых слабых игр
    отзыв <appid> <1-5> <текст>  — оставить отзыв
    статистика           — статистика по запросам и отзывам
    мои                  — персональные рекомендации
    обучить              — обучить модель предпочтений
    выход                — завершить работу
"""
from __future__ import annotations

import sys

import personal
import recommender
import storage

USER = 'console_user'


def beep() -> None:
    """Звуковое сопровождение: на Windows — winsound, иначе системный сигнал."""
    try:
        import winsound
        winsound.Beep(880, 150)
    except Exception:
        sys.stdout.write('\a')
        sys.stdout.flush()


def show(results: list[dict]) -> None:
    if not results:
        print('Ничего не найдено.')
        return
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['name']}  [{r['genres']}]")
        print(f"   год {r['year']} | цена {r['price']:.2f} $ | рейтинг {r['rating']} % | "
              f"онлайн {r['online']:.0f} | баллов {r['score']}")
        print(f"   совместимость с запросом: {r['match']} %")
        if r['why']:
            print('   за что баллы: ' + '; '.join(r['why']))
    beep()


def main() -> None:
    storage.init_db()
    games = recommender.load_games()
    print('=' * 72)
    print('Рекомендательная система по играм Steam — практическая работа №9')
    print(f'В каталоге {len(games)} игр. Команда «выход» завершает работу.')
    print('=' * 72)

    while True:
        try:
            line = input('\nЗапрос> ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nЗавершение работы.')
            break
        if not line:
            continue
        low = line.lower()

        if low in ('выход', 'exit', 'quit'):
            print('Завершение работы.')
            break

        if low.startswith('имя '):
            found = recommender.search_by_name(games, line[4:].strip())
            for g in found:
                print(f"  {g['steam_appid']:>8}  {g['name']}  [{g['genres_str']}] "
                      f"{g['price']:.2f} $  {g['rating']} %")
            if not found:
                print('Ничего не найдено.')
            continue

        if low.startswith('диапазон '):
            parts = line.split()
            if len(parts) != 4:
                print('Формат: диапазон <поле> <от> <до>. Поля:',
                      ', '.join(recommender.RANGE_FIELDS))
                continue
            try:
                found = recommender.search_by_range(games, parts[1], float(parts[2]),
                                                    float(parts[3]))
            except ValueError as e:
                print(e)
                continue
            for g in found:
                print(f"  {g['name']}  {g['price']:.2f} $  рейтинг {g['rating']} %  "
                      f"онлайн {g['avg_online']:.0f}  год {g['release_year']}")
            continue

        if low.startswith('слабые'):
            for i, g in enumerate(recommender.weak_games(games, 10), 1):
                print(f"  {i}. {g['name']}  рейтинг {g['rating']} %  "
                      f"негативных отзывов {g['total_negative']}")
            continue

        if low.startswith('отзыв '):
            parts = line.split(maxsplit=3)
            if len(parts) < 3:
                print('Формат: отзыв <appid> <оценка 1-5> <текст>')
                continue
            row = games[games['steam_appid'] == int(parts[1])]
            name = row.iloc[0]['name'] if len(row) else f'app {parts[1]}'
            storage.add_review(USER, int(parts[1]), name, int(parts[2]),
                               parts[3] if len(parts) > 3 else '')
            print(f'Отзыв на «{name}» сохранён.')
            continue

        if low.startswith('статистик'):
            qs = storage.query_stats()
            print(f"Запросов всего: {qs['total']}, пользователей: {qs['users']}")
            print('Частые запросы:', ', '.join(f"{q['query']} ({q['cnt']})"
                                               for q in qs['top_queries'][:5]))
            print('Популярные жанры:', ', '.join(f'{g} ({c})' for g, c in qs['top_genres'][:5]))
            for s in storage.review_stats(10):
                print(f"  {s['name']}: отзывов {s['cnt']}, средняя оценка {s['avg_rating']}")
            continue

        if low.startswith('мои'):
            recs, note = personal.personal_recommend(USER, games)
            print(note)
            show(recs)
            continue

        if low.startswith('обучить'):
            print(personal.train_model(games))
            continue

        results, parsed = recommender.recommend(games, line, 5)
        print(f"Распознано: жанры {parsed['genres'] or '—'}, "
              f"характеристики {[f[3] for f in parsed['features']] or '—'}")
        storage.log_query(USER, line, parsed['genres'],
                          results[0] if results else None, source='console')
        show(results)


if __name__ == '__main__':
    main()
