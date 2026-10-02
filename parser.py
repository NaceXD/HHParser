import os
import asyncio
import logging
from dotenv import load_dotenv
import httpx2 as httpx
from lxml import html
from db import save_vacancy

load_dotenv()
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")
HH_WEB_URL = "https://hh.ru/search/vacancy"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("parser.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("HHParser")


async def parse_vacancies(search_text: str):
    headers = {"User-Agent": USER_AGENT}
    page = 0

    logger.info(f"Инициализация парсинга по ключевому слову: '{search_text}'")

    async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
        while True:
            params = {
                "text": search_text,
                "area": 113,
                "page": page
            }
            try:
                response = await client.get(HH_WEB_URL, params=params)
            except httpx.RequestError as exc:
                logger.error(f"Сетевой сбой при доступе к поисковой странице {page + 1}: {exc}")
                raise RuntimeError(f"Глобальный сбой сети: не удалось связаться с hh.ru") from exc

            if response.status_code != 200:
                logger.error(f"Сервер hh.ru ответил с ошибкой {response.status_code} на странице {page + 1}")
                raise ValueError(f"HeadHunter заблокировал запрос. Статус-код: {response.status_code}")

            tree = html.fromstring(response.text)
            vacancies = tree.xpath("//article[@data-qa='vacancy-serp__vacancy']")
            if not vacancies:
                logger.warning(f"На странице {page + 1} разметка вакансий не обнаружена. Завершение.")
                break
            logger.info(f"Успешно сканирована страница {page + 1}. Найдено карточек вакансий {len(vacancies)}")
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
                vacancy_url = url if url.startswith("http") else f"https://hh.ru{url}"
                published_at = "Не указано"
                skills = []
                salary_from = None
                salary_to = None
                salary_currency = "Не указано"
                try:
                    await asyncio.sleep(3)
                    v_response = await client.get(vacancy_url)
                    if v_response.status_code == 200:
                        inner_tree = html.fromstring(v_response.text)
                        published_at = inner_tree.xpath(
                            "string(//div[@class='bloko-gap bloko-gap_bottom']//span)").strip()
                        salary = inner_tree.xpath("//div[@data-qa='vacancy-salary']//data[@value]/@value")
                        if salary:
                            try:
                                salary_from = int(salary[0])
                                salary_currency = str(salary[-1]).strip()
                                if len(salary) > 2:
                                    salary_to = int(salary[1])
                            except ValueError:
                                logger.warning(f"Не удалось преобразовать числа зарплаты для вакансии ID: {v_id}")
                        skills_elements = inner_tree.xpath("//li[@data-qa='skills-element']//text()")
                        if skills_elements:
                            skills.extend([skill.replace("\xa0", "").strip() for skill in skills_elements if skill])
                    else:
                        logger.warning(f"Вакансия ID:{v_id} вернула статус-код: {v_response.status_code}")
                except Exception as e:
                    logger.error(f"Ошибка обработки содержимого вакансии ID:{v_id}: {e}")

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
                    "search_text" : search_text,
                    "skills": skills
                }
                logger.info(f"Собрано: {title} | Навыков: {len(skills)} | ЗП от: {salary_from}")
                save_vacancy(prepared_vacancy)

            logger.info(f"Вакансии со страницы {page + 1} успешно импортированы в базу.")
            next_page_button = tree.xpath("//a[@data-qa='pager-next']")
            if next_page_button:
                page += 1
                await asyncio.sleep(5)
            else:
                logger.info("Сбор полностью завершен!")
                break


if __name__ == "__main__":
    asyncio.run(parse_vacancies("Python"))
