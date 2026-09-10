"""
Скрапер расписания apps.mitso.by
 
Логика такая же, как у браузера:
1. GET  /schedule/index         -> получаем сессионные куки и csrf-токен
2. POST /schedule/group-schedule -> отправляем факультет/форму/курс/группу и получаем HTML с таблицей
3. Разбираем HTML и превращаем в удобный JSON: список дней, в каждом список пар.
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
 
 
def fetch_schedule_html(fak: str, form: str, kurse: str, group_class: str, week: str = "0") -> str:
    """Делает POST-запрос от имени сессии и возвращает сырой HTML с расписанием."""
    session = requests.Session()
    csrf_token = _get_csrf_token(session)
 
    payload = {
        "_csrf-frontend": csrf_token,
        "ScheduleSearch[fak]": fak,
        "ScheduleSearch[form]": form,
        "ScheduleSearch[kurse]": kurse,
        "ScheduleSearch[group_class]": group_class,
        "ScheduleSearch[week]": week,
    }
 
    resp = session.post(GROUP_SCHEDULE_URL, data=payload, headers=HEADERS, timeout=15, verify=False)
    resp.raise_for_status()
    return resp.text
 
 
def parse_schedule(html: str) -> list[dict]:
    """Превращает HTML-страницу расписания в список дней с парами.
 
    ВАЖНО: на сайте apps.mitso.by класс `.weekly-schedule` — это ОДИН общий
    контейнер на всю неделю, внутри которого подряд идут заголовки <h2> с
    названиями дней и таблицы <table> с парами для каждого дня. Раньше код
    делал `block.find("h2")` / `block.find("table")` на этом единственном
    контейнере, а .find() в BeautifulSoup возвращает только ПЕРВЫЙ найденный
    элемент — поэтому всегда получался только понедельник.
 
    Исправление: находим ВСЕ заголовки <h2> внутри .weekly-schedule и для
    каждого берём таблицу, которая идёт сразу за ним (find_next_sibling или
    find_next).
    """
    soup = BeautifulSoup(html, "html.parser")
    days = []
 
    headers = soup.select(".weekly-schedule h2")
    for header in headers:
        day_title = header.get_text(strip=True)
 
        # Ищем ближайшую таблицу, которая идёт после этого заголовка,
        # но раньше следующего h2 (чтобы не залезть в чужой день).
        table = header.find_next("table")
 
        lessons = []
        if table:
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
 
    if not days:
        raise ScheduleFetchError(
            "Не нашёл ни одного дня в ответе сайта — вероятно, неверно указаны "
            "fak/form/kurse/group_class, либо сайт изменил структуру страницы"
        )
 
    return days
 
 
def get_schedule(fak: str, form: str, kurse: str, group_class: str, week: str = "0") -> list[dict]:
    """Главная функция: сходить на сайт и вернуть готовое расписание."""
    html = fetch_schedule_html(fak, form, kurse, group_class, week)
    return parse_schedule(html)
 
 
if __name__ == "__main__":
    # Быстрая проверка вручную: python scraper.py
    # Подставь сюда точные значения, которые ты видел(а) в Payload запроса group-schedule.
    import json
 
    schedule = get_schedule(
        fak="Экономический",
        form="Dnevnaya",
        kurse="1 kurs",
        group_class="2611 MN",
    )
    print(json.dumps(schedule, ensure_ascii=False, indent=2))
 
