"""Прогон демонстрации из пункта 4 задания через интерфейс со снимками экрана."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

from browser import Browser

URL = os.environ.get("PLANNER_URL", "http://127.0.0.1:8000")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")

PLAN_READY = (
    "!document.querySelector('.plan-btn').disabled"
    " && !!document.querySelector('.kpis:not(.empty) .kpi-value')"
    " && !document.querySelector('.variant-bar.running')"
)
ROUTES_DRAWN = (
    "[...document.querySelectorAll('.leaflet-overlay-pane canvas')].some(c => {"
    " const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;"
    " let painted = 0;"
    " for (let i = 3; i < data.length; i += 4 * 97) if (data[i] > 0) painted += 1;"
    " return painted > 200; })"
)
EVENTS_IDLE = "!document.querySelector('.ev.running') && !document.querySelector('.ev.pending:not(.future)')"

problems: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  [ok] " if condition else "  [!!] ") + message)
    if not condition:
        problems.append(message)


def text(browser: Browser, selector: str = "body") -> str:
    return browser.eval(f"(document.querySelector({selector!r}) || {{}}).innerText || ''") or ""


def open_tab(browser: Browser, title: str) -> bool:
    opened = browser.click_text(title, "[role=tab]")
    browser.wait(1200)
    return opened


def set_clock(browser: Browser, hhmm: str) -> None:
    hours, minutes = hhmm.split(":")
    browser.eval(
        "(() => { const input = document.querySelector('input[aria-label=\"Время дня\"]');"
        " const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
        f" setter.call(input, '{int(hours) * 60 + int(minutes)}');"
        " input.dispatchEvent(new Event('input', { bubbles: true })); })()"
    )


def play_until(browser: Browser, hhmm: str) -> int:
    """Двигает часы симуляции и ждёт перепланирования по каждому наступившему событию."""
    fired = 0
    for _ in range(10):
        set_clock(browser, hhmm)
        browser.wait(600)
        if not browser.eval("!!document.querySelector('.ev.running')"):
            break
        fired += 1
        browser.wait_for(EVENTS_IDLE, timeout_s=120)
    return fired


def run() -> int:
    with Browser(width=1680, height=1000) as browser:
        browser.install_error_trap()

        print("\n1. Открыть данные")
        browser.goto(URL, wait_ms=3000)
        check(browser.wait_for("!!document.querySelector('.kpis.empty .kpi-value')", timeout_s=30), "сценарий загружен")
        check(browser.eval("document.querySelector('.area select')?.value") == "demo", "выбран демонстрационный набор")
        print("     ", text(browser, ".kpis").replace("\n", " "))
        browser.screenshot(OUT / "01-данные.png")

        print("\n2. Запустить планирование")
        started = time.time()
        check(browser.click(".plan-btn"), "кнопка расчёта нажата")
        browser.wait(4000)
        browser.screenshot(OUT / "02-ход-расчёта.png")
        check(browser.wait_for(PLAN_READY, timeout_s=180), "план построен")
        print(f"      расчёт занял {time.time() - started:.0f} с")
        browser.wait(1500)
        kpis = text(browser, ".kpis")
        print("     ", kpis.replace("\n", " "))
        check("заявок" in kpis and "инженеров" in kpis and "км" in kpis, "показатели плана на месте")
        check("Базовый" in kpis, "рядом показан базовый вариант")
        check(browser.eval("document.querySelectorAll('.vc').length") == 3, "три варианта плана на выбор")

        print("\n3. Показать карту")
        browser.wait_for(
            "[...document.querySelectorAll('img.leaflet-tile')]"
            ".filter(i => i.complete && i.naturalWidth > 0).length >= 8",
            timeout_s=45,
        )
        check(browser.eval("document.querySelectorAll('.leaflet-container').length === 1"), "карта на экране")
        check(browser.eval(ROUTES_DRAWN), "маршруты нарисованы на карте")
        check(browser.eval("document.querySelectorAll('.q-row').length >= 50"), "очередь заявок заполнена")
        browser.screenshot(OUT / "03-карта.png")

        print("\n4. Объяснить заявку")
        check(browser.click(".q-row:not(.unplaced)"), "назначенная заявка открыта")
        browser.wait(1500)
        browser.eval(
            "document.querySelectorAll('.panel.job .disclosure-toggle[aria-expanded=false]')"
            ".forEach(b => b.click())"
        )
        browser.wait(600)
        card = text(browser, ".panel.job")
        print("     ", card.replace("\n", " | ")[:240])
        check("Проверки" in card, "карточка показывает проверки ограничений")
        check(browser.wait_for("!!document.querySelector('.cand-list')", timeout_s=30), "показаны кандидаты на замену")
        browser.screenshot(OUT / "04-объяснение.png")
        browser.click(".panel.job .panel-head .icon")
        browser.wait(800)

        browser.click(".kpi-action")
        browser.wait(800)
        if browser.click(".q-row.unplaced"):
            browser.wait(1500)
            reason = text(browser, ".panel.job .status-times")
            print("      причина:", reason)
            check(bool(reason.strip()), "у неназначенной заявки есть причина")
            browser.screenshot(OUT / "05-неназначенная.png")
            browser.click(".panel.job .panel-head .icon")
            browser.wait(800)

        print("\n5. Ввести событие")
        check(open_tab(browser, "Симуляция"), "симуляция открыта")
        check(browser.eval("document.querySelectorAll('.ev').length") >= 3, "подготовленные события на шкале")
        fired = play_until(browser, "12:35")
        check(fired >= 2, f"отмена и авария применены ({fired})")
        events = text(browser, ".events-panel")
        print("     ", events.replace("\n", " | ")[:300])
        check("зафиксировано" in events, "указано число закреплённых визитов")
        check("не применено" not in events, "все события применены")
        browser.screenshot(OUT / "06-симуляция.png")

        browser.click_text("Новая заявка", "button")
        browser.wait(1500)
        check(browser.wait_for("!document.querySelector('.ev-form .primary').disabled", timeout_s=20), "форма новой заявки готова")
        browser.screenshot(OUT / "07-форма-события.png")
        browser.click(".ev-form .primary")
        browser.wait(1000)
        check(browser.wait_for(EVENTS_IDLE, timeout_s=120), "новая заявка обработана")
        added = text(browser, ".events-panel")
        check("NEW-" in added, "новая заявка появилась в списке событий")

        print("\n6. Показать изменения")
        open_tab(browser, "План дня")
        browser.click(".queue .seg button")
        browser.wait(600)
        kpis = text(browser, ".kpis")
        print("     ", kpis.replace("\n", " "))
        check(browser.eval("document.querySelectorAll('.q-row .tag.changed').length") > 0, "изменённые заявки подсвечены")
        browser.screenshot(OUT / "08-изменения.png")
        check(open_tab(browser, "Расписание"), "расписание открыто")
        browser.screenshot(OUT / "09-расписание.png")

        print("\n7. Сравнить с базовым")
        check(open_tab(browser, "Сравнение с базовым"), "сравнение открыто")
        compare = text(browser, ".compare-page")
        print("     ", text(browser, ".verdict-line"))
        check("Задействовано" in compare or "инженер" in compare, "первая обязательная метрика")
        check("пробег" in compare.lower(), "вторая обязательная метрика")
        check("Факт" in compare, "сверка с ручным распределением")
        browser.screenshot(OUT / "10-сравнение.png")

        errors = browser.console_errors()
        check(not errors, f"ошибок в консоли нет (найдено {len(errors)})")
        for item in errors[:10]:
            print("      ошибка:", item)

    print("\n" + ("всё хорошо" if not problems else f"проблемы ({len(problems)}):"))
    for item in problems:
        print("  -", item)
    print(f"снимки: {OUT.resolve()}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(run())
