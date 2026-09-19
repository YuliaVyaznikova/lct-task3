"""Прогон сценария защиты из ТЗ §4 через интерфейс со снимками экрана.

    python tools/demo_flow.py [каталог-для-снимков]

Проверяет ровно то, что будет показано комиссии: загрузка набора, расчёт,
карта и таймлайн, объяснение назначения, причина отказа, событие
и перестроение плана, сравнение с базовым вариантом.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from browser import Browser  # noqa: E402

URL = os.environ.get("PLANNER_URL", "http://127.0.0.1:8000")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")

problems: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  [ok] " if condition else "  [!!] ") + message)
    if not condition:
        problems.append(message)


def run() -> int:
    with Browser(width=1680, height=1000) as browser:
        browser.install_error_trap()

        print("\n1. Открываем сервис")
        browser.goto(URL, wait_ms=3500)
        check(browser.eval("document.getElementById('root').children.length > 0"), "страница отрисована")
        check("ПЛАНИРОВАНИЕ МАРШРУТОВ" in (browser.eval("document.body.innerText") or ""), "панель управления на месте")
        browser.screenshot(OUT / "01-старт.png")

        print("\n2. Считаем план")
        browser.eval(
            "[...document.querySelectorAll('button')]"
            ".find(b => b.textContent.includes('Спланировать день')).click()"
        )
        ready = browser.wait_for(
            "document.body.innerText.includes('Задействовано')", timeout_s=120
        )
        check(ready, "план посчитан")
        # Тайлы OpenStreetMap приходят медленно (секунды на плитку), а без них
        # снимок выглядит пустым, хотя маршруты уже нарисованы.
        browser.wait_for(
            "[...document.querySelectorAll('img.leaflet-tile')]"
            ".filter(i => i.complete && i.naturalWidth > 0).length >= 12",
            timeout_s=45,
        )
        browser.wait(1200)

        summary = browser.eval(
            "document.querySelector('.summary')?.textContent || ''"
        )
        print("     ", summary[:160])
        check(bool(summary), "сводка плана показана")
        check(
            browser.eval("document.querySelectorAll('.leaflet-container').length === 1"),
            "карта на экране",
        )
        # Карта включена в режиме canvas (preferCanvas), поэтому точки и линии
        # не являются элементами DOM — проверяем сам холст и подложку.
        check(
            browser.eval("document.querySelectorAll('.leaflet-container canvas').length >= 1"),
            "слой маршрутов на карте создан",
        )
        check(
            browser.eval(
                "[...document.querySelectorAll('img.leaflet-tile')]"
                ".filter(i => i.complete && i.naturalWidth > 0).length >= 8"
            ),
            "подложка карты загрузилась",
        )
        check(browser.eval("document.querySelectorAll('.tl-row').length >= 10"), "таймлайн заполнен")
        browser.screenshot(OUT / "02-план.png")

        print("\n3. Объяснение назначения")
        browser.eval("document.querySelectorAll('tr.clickable')[0]?.click()")
        browser.wait(1200)
        card = browser.eval("document.querySelector('.card')?.innerText || ''")
        print("     ", card.replace("\n", " | ")[:200])
        check("Навык" in card and "Окно" in card, "карточка показывает проверки ограничений")
        check("Альтернативы" in card or "Единственный" in card, "карточка отвечает, почему этот инженер")
        browser.screenshot(OUT / "03-карточка-заявки.png")

        print("\n4. Неназначенные заявки и причины")
        browser.eval(
            "[...document.querySelectorAll('.tabs button')]"
            ".find(b => b.textContent.includes('Не назначены')).click()"
        )
        browser.wait(900)
        text = browser.eval("document.body.innerText") or ""
        check(
            "Все заявки распределены" in text
            or any(word in text for word in ("не хватило мощности", "нет навыка", "слишком далеко")),
            "причина отказа показана словами",
        )
        browser.screenshot(OUT / "04-не-назначены.png")

        print("\n5. Сравнение с базовым вариантом")
        browser.eval(
            "[...document.querySelectorAll('.tabs button')]"
            ".find(b => b.textContent.includes('Метрики')).click()"
        )
        browser.wait(900)
        metrics = browser.eval("document.body.innerText") or ""
        check("Сравнение с базовым вариантом" in metrics, "таблица сравнения на месте")
        check("Задействовано инженеров" in metrics, "первая обязательная метрика ТЗ")
        check("Суммарный пробег" in metrics, "вторая обязательная метрика ТЗ")
        # Таблица должна быть именно видна, а не уехать под открытую карточку.
        check(
            browser.eval(
                "(() => { const t = [...document.querySelectorAll('h2')]"
                ".find(h => h.textContent.includes('Сравнение с базовым'));"
                " if (!t) return false;"
                " const r = t.getBoundingClientRect();"
                " return r.top >= 0 && r.top < window.innerHeight; })()"
            ),
            "таблица сравнения видна без прокрутки",
        )
        browser.screenshot(OUT / "05-метрики.png")

        print("\n6. Событие: срочная авария")
        browser.eval(
            "[...document.querySelectorAll('button')]"
            ".find(b => b.textContent.trim() === 'Срочная заявка').click()"
        )
        browser.wait(400)
        browser.eval(
            "[...document.querySelectorAll('button')]"
            ".find(b => b.textContent.includes('Перестроить план')).click()"
        )
        rebuilt = browser.wait_for(
            "document.body.innerText.includes('Событие:')", timeout_s=180
        )
        check(rebuilt, "план перестроен")
        browser.wait(2000)
        diff = browser.eval("document.querySelector('.summary')?.textContent || ''")
        print("     ", diff[:220])
        check("Зафиксировано" in diff, "визиты, начатые до события, зафиксированы")
        check("Пробег" in diff, "изменение метрик показано")
        browser.screenshot(OUT / "06-после-события.png")

        print("\n7. Что именно изменилось")
        browser.eval(
            "[...document.querySelectorAll('.tabs button')]"
            ".find(b => b.textContent.includes('Изменения')).click()"
        )
        browser.wait(900)
        changes = browser.eval("document.body.innerText") or ""
        check("Событие:" in changes, "вкладка изменений заполнена")
        browser.screenshot(OUT / "07-изменения.png")

        print("\n8. Другой участок")
        browser.eval(
            "(() => { const s = document.querySelector('select');"
            " s.value = 'yugo-vostok';"
            " s.dispatchEvent(new Event('change', { bubbles: true })); })()"
        )
        browser.wait(1500)
        browser.eval(
            "[...document.querySelectorAll('button')]"
            ".find(b => b.textContent.includes('Спланировать день')).click()"
        )
        check(
            browser.wait_for("document.body.innerText.includes('Задействовано')", timeout_s=180),
            "Юго-Восток посчитан",
        )
        browser.wait(2500)
        browser.screenshot(OUT / "08-юго-восток.png")

        errors = browser.eval("window.__errors__ || []") or []
        check(not errors, f"ошибок в консоли нет (найдено {len(errors)})")
        for item in errors[:10]:
            print("      ошибка:", item)

    print("\n" + ("ВСЁ ХОРОШО" if not problems else f"ПРОБЛЕМЫ ({len(problems)}):"))
    for item in problems:
        print("  -", item)
    print(f"снимки: {OUT.resolve()}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(run())
