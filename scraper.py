"""
Скрапер расписания apps.mitso.by

Логика такая же, как у браузера:
1. GET  /schedule/index         -> получаем сессионные куки и csrf-токен
2. POST /schedule/group-schedule -> отправляем факультет/форму/курс/группу и получаем HTML
3. Разбираем HTML и превращаем в удобный JSON: список недель, в каждой список дней с парами.

ВАЖНОЕ НАБЛЮДЕНИЕ (после отладки через DevTools):
Сайт при КАЖДОМ запросе всегда возвращает ОБА блока расписания сразу —
два отдельных контейнера с классом `.weekly-schedule`: один для текущей
недели (id вида "schedule-Текущая-неделя"), другой для следующей
(id вида "schedule-14-сентября-20-сентября"). Параметр
`ScheduleSearch[week]`, который отправляет форма на сайте, влияет только
на то, какой из двух уже отрисованных на сервере блоков сайт показывает
пользователю через JS/CSS — сами данные всегда приходят оба сразу.

Поэтому мы не пытаемся "просить" сайт отдать только одну неделю (это не
работает), а разбираем оба блока `.weekly-schedule` по отдельности и сами
выбираем нужный по порядковому номеру (0 — текущая, 1 — следующая).
"""

import logging
import requests
import urllib3
from bs4 import BeautifulSoup

# Сайт apps.mitso.by отдаёт неполную цепочку сертификатов (браузеры это прощают,
# у них уже есть промежуточный сертификат в системном хранилище, а у чистого сервера
# его нет). Поэтому отключаем проверку и глушим предупреждение об этом в логах.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://apps.mitso.by/frontend/web"
INDEX_URL = f"{BASE_URL}/schedule/index"
GROUP_SCHEDULE_URL = f"{BASE_URL}/schedule/group-schedule"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

logger = logging.getLogger("scraper")


class ScheduleFetchError(Exception):
    pass


def _get_csrf_token(session: requests.Session) -> str:
    """Заходим на страницу расписания, чтобы получить сессионные куки и csrf-токен."""
    resp = session.get(INDEX_URL, headers=HEADERS, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    meta = soup.find("meta", attrs={"name": "csrf-token"})
    if not meta or not meta.get("content"):
        raise ScheduleFetchError("Не нашёл csrf-token на странице schedule/index — сайт мог измениться")
    return meta["content"]


def fetch_schedule_html(fak: str, form: str, kurse: str, group_class: str) -> str:
    """Делает POST-запрос от имени сессии и возвращает сырой HTML со ВСЕМИ неделями сразу.

    Поле ScheduleSearch[week] сайт, судя по всему, требует как обязательное
    для валидации формы (без него не возвращает результат вообще). При этом
    само его значение не влияет на то, что приходит в ответе — сайт всегда
    присылает оба блока недель. Поэтому шлём фиксированное "0" просто чтобы
    пройти валидацию.
    """
    session = requests.Session()
    csrf_token = _get_csrf_token(session)

    payload = {
        "_csrf-frontend": csrf_token,
        "ScheduleSearch[fak]": fak,
        "ScheduleSearch[form]": form,
        "ScheduleSearch[kurse]": kurse,
        "ScheduleSearch[group_class]": group_class,
        "ScheduleSearch[week]": "0",
    }

    resp = session.post(GROUP_SCHEDULE_URL, data=payload, headers=HEADERS, timeout=15, verify=False)
    resp.raise_for_status()
    return resp.text


def _parse_week_block(block) -> list[dict]:
    """Разбирает ОДИН контейнер .weekly-schedule (одну неделю) в список дней."""
    days = []
    headers = block.find_all("h2")
    tables = block.find_all("table")

    # На каждый день должен быть ровно один h2 (заголовок) и одна table (пары).
    # Если вдруг их количество не совпадает — берём по минимальному количеству,
    # чтобы не упасть, но логируем это как подозрительный случай.
    if len(headers) != len(tables):
        logger.warning(
            "В одном блоке недели не совпадает число заголовков (%d) и таблиц (%d)",
            len(headers), len(tables),
        )

    for header, table in zip(headers, tables):
        day_title = header.get_text(strip=True)
        lessons = []
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            time_ = cells[0].get_text(strip=True)
            subject = cells[1].get_text(" ", strip=True)
            room = cells[2].get_text(strip=True)
            if subject and "нет занятий" not in subject.lower():
                lessons.append({"time": time_, "subject": subject, "room": room})
        days.append({"day": day_title, "lessons": lessons})

    return days


def parse_all_weeks(html: str) -> list[list[dict]]:
    """Возвращает список недель. Каждая неделя — список дней (как раньше).

    weeks[0] — текущая неделя, weeks[1] — следующая (порядок как на сайте).
    """
    soup = BeautifulSoup(html, "html.parser")
    week_blocks = soup.select(".weekly-schedule")

    logger.info(
        "Найдено %d блоков недель: %s",
        len(week_blocks),
        [b.get("id", "(без id)") for b in week_blocks],
    )

    if not week_blocks:
        raise ScheduleFetchError(
            "Не нашёл ни одного блока .weekly-schedule в ответе сайта — вероятно, неверно указаны "
            "fak/form/kurse/group_class, либо сайт изменил структуру страницы"
        )

    weeks = [_parse_week_block(block) for block in week_blocks]
    for i, week_days in enumerate(weeks):
        logger.info("Неделя %d: %s", i, [d["day"] for d in week_days])

    return weeks


def get_schedule(fak: str, form: str, kurse: str, group_class: str, week: str = "0") -> list[dict]:
    """Главная функция: сходить на сайт и вернуть готовое расписание ОДНОЙ недели.

    week: "0" — текущая неделя (первый блок на сайте), "1" — следующая (второй блок).
    """
    html = fetch_schedule_html(fak, form, kurse, group_class)
    weeks = parse_all_weeks(html)

    week_index = int(week)
    if week_index >= len(weeks):
        raise ScheduleFetchError(
            f"Запрошена неделя с индексом {week_index}, но на сайте есть только {len(weeks)} недель(и)"
        )

    return weeks[week_index]


if __name__ == "__main__":
    # Быстрая проверка вручную: python scraper.py
    import json

    for w in ("0", "1"):
        schedule = get_schedule(
            fak="Экономический",
            form="Dnevnaya",
            kurse="1 kurs",
            group_class="2611 MN",
            week=w,
        )
        print(f"--- Неделя {w} ---")
        print(json.dumps(schedule, ensure_ascii=False, indent=2))
