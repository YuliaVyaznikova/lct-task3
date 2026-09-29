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
REVIEW_OR_IDLE = f"!!document.querySelector('.review-card') || ({EVENTS_IDLE})"

problems: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  [ok] " if condition else "  [!!] ") + message)
    if not condition:
        problems.append(message)


def text(browser: Browser, selector: str = "body") -> str:
    return browser.eval(f"(document.querySelector({selector!r}) || {{}}).innerText || ''") or ""


JOB_PANEL = '.panel[aria-label^="Заявка"]'
EVENTS_PANEL = '.panel[aria-label="События дня"]'
MAP_MODES = ("План дня", "Симуляция")


def open_tab(browser: Browser, title: str) -> bool:
    if title in MAP_MODES:
        browser.click(".tb-tabs [role=tab]")
        browser.wait(600)
        want_sim = title == "Симуляция"
        pressed = browser.eval("document.querySelector('.sim-toggle')?.getAttribute('aria-pressed') === 'true'")
        opened = True if pressed == want_sim else browser.click(".sim-toggle")
    else:
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


def settle_events(browser: Browser, shot: Path | None = None) -> bool:
    """Подтверждает каждый новый план, пока наступившие события не обработаны."""
    for _ in range(10):
        if not browser.wait_for(REVIEW_OR_IDLE, timeout_s=120):
            return False
        if not browser.eval("!!document.querySelector('.review-card')"):
            return True
        if shot is not None:
            browser.screenshot(shot)
            shot = None
        browser.click(".review-card .primary")
        browser.wait(400)
        browser.click(".review-card .danger")
        browser.wait(800)
    return False


def play_until(browser: Browser, hhmm: str, shot: Path | None = None) -> int:
    """Двигает часы симуляции и ждёт перепланирования по каждому наступившему событию."""
    fired = 0
    for _ in range(10):
        set_clock(browser, hhmm)
        browser.wait(600)
        if not browser.eval("!!document.querySelector('.ev.running')"):
            break
        fired += 1
        settle_events(browser, shot)
        shot = None
    return fired


def open_data(browser: Browser) -> None:
    print("\n1. Открыть данные")
    browser.goto(URL, wait_ms=3000)
    check(browser.wait_for("!!document.querySelector('.kpis.empty .kpi-value')", timeout_s=30), "сценарий загружен")
    check(browser.eval("document.querySelector('.area select')?.value") == "demo", "выбран демонстрационный набор")
    print("     ", text(browser, ".kpis").replace("\n", " "))
    browser.screenshot(OUT / "01-данные.png")


def start_planning(browser: Browser) -> None:
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
    check("база" in kpis, "в карточках показана база")
    check(browser.eval("document.querySelectorAll('.vc').length") == 3, "три варианта плана на выбор")


def show_map(browser: Browser) -> None:
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


def explain_order(browser: Browser) -> None:
    print("\n4. Объяснить заявку")
    check(browser.click(".q-row:not(.unplaced)"), "назначенная заявка открыта")
    browser.wait(1500)
    browser.eval(
        f"document.querySelectorAll('{JOB_PANEL} .disclosure-toggle[aria-expanded=false]')"
        ".forEach(b => b.click())"
    )
    browser.wait(600)
    card = text(browser, JOB_PANEL)
    print("     ", card.replace("\n", " | ")[:240])
    check("Проверки" in card, "карточка показывает проверки ограничений")
    check(browser.wait_for("!!document.querySelector('.cand-list')", timeout_s=30), "показаны кандидаты на замену")
    browser.screenshot(OUT / "04-объяснение.png")
    browser.click(f"{JOB_PANEL} .panel-head .icon")
    browser.wait(800)

    browser.click(".kpi-action")
    browser.wait(800)
    if browser.click(".q-row.unplaced"):
        browser.wait(1500)
        reason = text(browser, f"{JOB_PANEL} .status-times")
        print("      причина:", reason)
        check(bool(reason.strip()), "у неназначенной заявки есть причина")
        browser.screenshot(OUT / "05-неназначенная.png")
        browser.click(f"{JOB_PANEL} .panel-head .icon")
        browser.wait(800)


def enter_event(browser: Browser) -> None:
    print("\n5. Ввести событие")
    check(open_tab(browser, "Симуляция"), "симуляция открыта")
    check(browser.eval("document.querySelectorAll('.ev').length") >= 3, "подготовленные события на шкале")
    fired = play_until(browser, "12:35", OUT / "06-подтверждение.png")
    check(fired >= 2, f"отмена и авария применены ({fired})")
    events = text(browser, EVENTS_PANEL)
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
    check(settle_events(browser), "новая заявка обработана")
    added = text(browser, EVENTS_PANEL)
    check("NEW-" in added, "новая заявка появилась в списке событий")


def show_changes(browser: Browser) -> None:
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


def compare_with_baseline(browser: Browser) -> None:
    print("\n7. Сравнить с базовым")
    check(open_tab(browser, "Сравнение с базовым"), "сравнение открыто")
    compare = text(browser, ".compare-page")
    print("     ", text(browser, ".verdict-line"))
    check("Задействовано" in compare or "инженер" in compare, "первая обязательная метрика")
    check("пробег" in compare.lower(), "вторая обязательная метрика")
    check("Факт" in compare, "сверка с ручным распределением")
    browser.screenshot(OUT / "10-сравнение.png")


STEPS = (
    open_data,
    start_planning,
    show_map,
    explain_order,
    enter_event,
    show_changes,
    compare_with_baseline,
)


def check_console(browser: Browser) -> None:
    errors = browser.console_errors()
    check(not errors, f"ошибок в консоли нет (найдено {len(errors)})")
    for item in errors[:10]:
        print("      ошибка:", item)


def run() -> int:
    with Browser(width=1680, height=1000) as browser:
        browser.install_error_trap()
        for step in STEPS:
            step(browser)
        check_console(browser)

    print("\n" + ("всё хорошо" if not problems else f"проблемы ({len(problems)}):"))
    for item in problems:
        print("  -", item)
    print(f"снимки: {OUT.resolve()}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(run())
