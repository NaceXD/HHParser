"""
Ядро асинхронного парсера HeadHunter.

Реализует конкурентный конвейер:
1. Crawler (parse_vacancies) — сборщик базовых карточек вакансий.
2. Hydrator (background_hydrator_loop) — обогатитель вакансий деталями и навыками.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random

from dotenv import load_dotenv
import httpx2 as httpx
from lxml import html

from ..crud import get_unparsed_vacancies, save_vacancy
from ..db import SessionLocal
from ..schemas import VacancyCreate
from ..state import ACTIVE_TASKS, parser_state

load_dotenv()

USER_AGENTS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
]
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")
HH_WEB_URL = "https://hh.ru/search/vacancy"

# Настройки логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("parser.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("HHParser")


# --- Потокобезопасные синхронные воркеры для потоков (THREAT POOL) ---
def _sync_save_woker(vacancy_shema: VacancyCreate, skills: list[str]) -> None:
    """Воркер для безопасного вызова CRUD сохранения внутри системного потока."""
    with SessionLocal() as session:
        save_vacancy(session, vacancy_shema, skills)


def _sync_get_unparsed_worker(limit: int) -> list:
    """Воркер для безопасного чтения необработанных вакансий внутри системного потока."""
    with SessionLocal() as session:
        return get_unparsed_vacancies(session, limit)


# --- Асинхронная логика конвейера ---
async def parse_vacancies(search_text: str) -> None:
    """Сканирует страницы поисковой выдачи HH и сохраняет скелеты вакансий."""
    page = 0
    logger.info(f"Запуск краулера по запросу: '{search_text}'")
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
        while True:
            params = {
                "text": search_text,
                "area": 113,
                "page": page
            }
            client.headers.update({"User-Agent": random.choice(USER_AGENTS_POOL)})

            try:
                response = await client.get(HH_WEB_URL, params=params)
            except httpx.RequestError as exc:
                parser_state.last_error = "Глобальный сбой сети: не удалось связаться с hh.ru"
                parser_state.status = "failed"
                raise RuntimeError(f"Глобальный сбой сети: не удалось связаться с hh.ru") from exc

            if response.status_code != 200:
                parser_state.last_error = f"HeadHunter заблокировал запрос. Статус-код: {response.status_code}"
                parser_state.status = "failed"
                raise ValueError(f"HeadHunter заблокировал запрос. Статус-код: {response.status_code}")
            current_url = str(response.url).lower()
            if "captcha" in current_url:
                logger.warning(f"БЛОКИРОВКА! HeadHunter выдал капчу на странице {page + 1}!")
                parser_state.captcha_encountered = True
                parser_state.status = "failed"
                break
            tree = html.fromstring(response.text)
            vacancies = tree.xpath("//article[@data-qa='vacancy-serp__vacancy']")
            if not vacancies:
                logger.warning(f"На странице {page + 1} разметка вакансий не обнаружена. Завершение.")
                break
            logger.info(f"Успешно сканирована страница {page + 1}. Найдено карточек вакансий {len(vacancies)}")
            parser_state.pages_scanned += 1
            parser_state.vacancies_found += len(vacancies)
            for vacancy_html in vacancies:
                title = (vacancy_html.xpath(
                    "string(.//span[@data-qa='serp-item__title-text'])") or "Без названия").strip()
                url = (
                        vacancy_html.xpath(".//a[@data-qa='serp-item__title']/@href") or [""]
                )[0].strip()
                company = (
                        vacancy_html.xpath("string(.//span[@data-qa='vacancy-serp__vacancy-employer-text'])")
                        or "Компания не указана").strip()
                city = (vacancy_html.xpath(
                    "string(.//span[@data-qa='vacancy-serp__vacancy-address'])") or "Не указано"
                        ).strip()
                v_id = "0"
                if "/vacancy" in url:
                    v_id = url.split("/vacancy/")[-1].split("?")[0]
                if not title or v_id == "0":
                    continue

                published_at = "Не указано"
                skills = []
                salary_from = None
                salary_to = None
                salary_currency = "Не указано"

                prepared_vacancy = {
                    "id": v_id,
                    "title": title,
                    "company": company,
                    "url": url if url.startswith("http") else f"https://hh.ru{url}",
                    "city": city,
                    "published_at": published_at,
                    "salary_from": salary_from,
                    "salary_to": salary_to,
                    "salary_currency": salary_currency,
                    "search_text": search_text.lower()
                }
                vacancy_shema = VacancyCreate(**prepared_vacancy)
                await asyncio.to_thread(_sync_save_woker, vacancy_shema, skills)
            logger.info(f"Вакансии со страницы {page + 1} успешно импортированы в базу.")
            next_page_button = tree.xpath("//a[@data-qa='pager-next']")
            if next_page_button:
                page += 1
                await asyncio.sleep(random.uniform(15.0, 45.0))
            else:
                logger.info("Сбор полностью завершен!")
                break


async def hydrate_vacancies(limit: int = 100) -> None:
    """Опрашивает обертку БД, запрашивает детали вакансий и обогащает их навыками."""
    logger.info("Обогащаем вакансии детальными данными")
    unparsed = await asyncio.to_thread(_sync_get_unparsed_worker, limit)
    if not unparsed:
        logger.info("Все вакансии в БД уже полностью обогащены")
        return
    logger.info(f"Найдено {len(unparsed)} вакансий для детального анализа.")
    headers = {"User-Agent": random.choice(USER_AGENTS_POOL)}

    async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
        for vacancy in unparsed:
            random_page = random.randint(1, 5)
            search_referer_url = f"{HH_WEB_URL}?text={vacancy.search_text}&area=113&page={random_page}"
            client.headers.update({
                "Referer": search_referer_url,
                "User-Agent": random.choice(USER_AGENTS_POOL)
            })
            await asyncio.sleep(random.uniform(5.0, 10.0))

            try:
                v_response = await client.get(vacancy.url)

                if "captcha" in str(v_response.url).lower():
                    logger.warning(f"Ловушка капчи внутри вакансии ID:{vacancy.id}! Пропускаем её.")
                    continue

                if v_response.status_code == 200:
                    inner_tree = html.fromstring(v_response.text)

                    salary_from = None
                    salary_to = None
                    salary_currency = "Не указано"
                    skills = []

                    published_at = inner_tree.xpath(
                        "string(//div[@class='bloko-gap bloko-gap_bottom']//time)").strip()
                    salary = inner_tree.xpath("//div[@data-qa='vacancy-salary']//data[@value]/@value")
                    if salary:
                        try:
                            salary_from = int(salary[0])
                            salary_currency = str(salary[-1]).strip()
                            if len(salary) > 2:
                                salary_to = int(salary[1])
                        except ValueError:
                            logger.warning(f"Не удалось преобразовать числа зарплаты для вакансии ID: {vacancy.id}")
                    skills_elements = inner_tree.xpath("//li[@data-qa='skills-element']//text()")
                    if skills_elements:
                        skills.extend([skill.replace("\xa0", "").strip() for skill in skills_elements if skill])
                    prepared_vacancy = {
                        "id": vacancy.id,
                        "title": vacancy.title,
                        "company": vacancy.company,
                        "url": vacancy.url,
                        "city": vacancy.city,
                        "published_at": published_at,
                        "salary_from": salary_from,
                        "salary_to": salary_to,
                        "salary_currency": salary_currency,
                        "search_text": vacancy.search_text,
                        "is_detailed_parsed": True
                    }
                    vacancy_shema = VacancyCreate(**prepared_vacancy)
                    await asyncio.to_thread(_sync_save_woker, vacancy_shema, skills)
                    logger.info(f"Вакансия ID:{vacancy.id} ({vacancy.title}) успешно обогащена. Навыков: {len(skills)}")

                else:
                    logger.warning(f"Вакансия ID:{vacancy.id} вернула статус-код: {v_response.status_code}")

            except Exception as e:
                logger.error(f"Ошибка обработки содержимого вакансии ID:{vacancy.id}: {e}")


async def background_hydrator_loop(crawler_task: asyncio.Task) -> None:
    """Фоновый цикл, который параллельно выгребает вакансии из БД и обогащает их."""
    logger.info("Фоновый воркер обогащения успешно запущен в параллельном потоке Event Loop.")

    while True:
        await hydrate_vacancies(limit=100)

        remaining = await asyncio.to_thread(_sync_get_unparsed_worker, 1)

        if not remaining:
            if crawler_task.done():
                logger.info("Очередь пуста, и сборщик страниц завершил работу. Фоновое обогащение остановлено.")
                break
            logger.debug("Очередь временно пуста. Ожидаем, пока Crawler соберет следующую страницу...")
            await asyncio.sleep(10.0)
        else:
            logger.info("Пауза охлаждения перед следующей пачкой...")
            await asyncio.sleep(10.0)


async def run_full_parsing_pipeline(search_text: str) -> None:
    """Главный оркестратор конкурентного конвейера."""
    logger.info(f"--- ЗАПУСК КОНКУРЕНТНОГО КОНВЕЙЕРА ДЛЯ ПОИСКА: '{search_text}' ---")

    crawler_task = asyncio.create_task(parse_vacancies(search_text))
    hydrator_task = asyncio.create_task(background_hydrator_loop(crawler_task))

    ACTIVE_TASKS["crawler"] = crawler_task
    ACTIVE_TASKS["hydrator"] = hydrator_task

    try:
        await asyncio.gather(crawler_task, hydrator_task)
    except asyncio.CancelledError:
        logger.warning("Конвейер парсинга принудительно прерван пользователем.")
    except Exception as e:
        parser_state.status = "failed"
        parser_state.last_error = str(e)
        logger.exception("Критическая ошибка конвейера")
    finally:
        # Принудительно гасим таски, если одна упала, а вторая зависла
        if not crawler_task.done():
            crawler_task.cancel()
        if not hydrator_task.done():
            hydrator_task.cancel()

        if parser_state.status == "running":
            parser_state.status = "completed"

        ACTIVE_TASKS["crawler"] = None
        ACTIVE_TASKS["hydrator"] = None
        logger.info(f"--- КОНКУРЕНТНЫЙ КОНВЕЙЕР ПО ЗАПРОСУ '{search_text}' ПОЛНОСТЬЮ ЗАВЕРШЕН ---")


if __name__ == "__main__":
    asyncio.run(run_full_parsing_pipeline("Python"))
