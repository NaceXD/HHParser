"""
Модуль CRUD-операций (Create, Read, Update, Delete).

Реализует атомарные функции взаимодействия с базой данных, включая
умный UPSERT вакансий и синхронизацию связей со справочником ключевых навыков.
"""

import io

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import joinedload, Session

from .models import Vacancy, Skill
from .schemas import VacancyCreate


def get_vacancies(session: Session, search: str | None = None, limit: int | None = None) -> list[Vacancy]:
    """Получает список вакансий из БД с предзагруженными навыками"""
    stmt = select(Vacancy).options(joinedload(Vacancy.skills))
    stmt = stmt.where(Vacancy.is_detailed_parsed == 1)
    stmt = stmt.order_by(Vacancy.created_at.desc())

    if search is not None:
        search = search.lower().strip()
        stmt = stmt.where(Vacancy.search_text.contains(search))

    if limit is not None:
        stmt = stmt.limit(limit)
    else:
        stmt = stmt.limit(20)

    return list(session.scalars(stmt).unique().all())


def save_vacancy(session: Session, vacancy_schema: VacancyCreate, skills_list: list[str]) -> Vacancy:
    """
        Сохраняет вакансию в БД (создает или атомарно обновляет) и синхронизирует навыки.

        Предотвращает затирание полезных данных пустыми значениями при повторном поиске.
        Защищает связи Many-to-Many от случайного сброса краулером.
    """
    vacancy_data = vacancy_schema.model_dump(exclude_unset=True)
    db_vacancy = session.get(Vacancy, vacancy_data["id"])

    # Логика UPSERT для вакансии
    if db_vacancy is not None:
        for key, value in vacancy_data.items():
            old_value = getattr(db_vacancy, key)
            is_new_empty = (value is None) or (value == "Не указано")
            is_old_useful = (old_value is not None) and (old_value != "Не указано")
            if is_old_useful and is_new_empty:
                continue
            setattr(db_vacancy, key, value)
        result_vacancy = db_vacancy
    else:
        new_vacancy = Vacancy(**vacancy_data)
        session.add(new_vacancy)
        result_vacancy = new_vacancy

    # Безопасная обработка навыков (Регистронезависимая очистка)
    cleaned_names = list(set(n.strip() for n in skills_list if n.strip()))
    if cleaned_names:
        stmt = select(Skill).where(Skill.name.in_(cleaned_names))
        db_skills = {s.name: s for s in session.scalars(stmt).all()}

        updated_skills = []
        for name in cleaned_names:
            skill_obj = db_skills.get(name)
            if skill_obj is None:
                skill_obj = Skill(name=name)
                session.add(skill_obj)
            updated_skills.append(skill_obj)

        # Обновляем коллекцию навыков у вакансии
        result_vacancy.skills = updated_skills

    session.commit()
    return result_vacancy


def get_unparsed_vacancies(session: Session, limit: int = 100) -> list[Vacancy]:
    """
        Выбирает из базы данных список необработанных вакансий для гидратора.

        Args:
            session (Session): Активная сессия базы данных.
            limit (int): Максимальное количество вакансий в одной пачке. По умолчанию 100.
    """
    stmt = select(Vacancy).where(Vacancy.is_detailed_parsed == False).limit(limit)
    return session.scalars(stmt).all()


def export_vacancies_to_exel(session: Session, search: str | None = None) -> io.BytesIO:
    """
        Выгружает вакансии из базы данных и формирует файл Excel в памяти.

        Args:
            session (Session): Активная сессия базы данных.
            search (str | None): Строка поискового запроса для фильтрации вакансий.

        Returns:
            io.BytesIO: Бинарный поток данных с готовым файлом Excel.
    """
    stmt = select(Vacancy).options(joinedload(Vacancy.skills))
    if search is not None:
        search = search.lower().strip()
        stmt = stmt.where(Vacancy.search_text.contains(search))
    vacancies = list(session.scalars(stmt).unique().all())
    data = []
    for v in vacancies:
        skills_str = ", ".join([skill.name for skill in v.skills])

        data.append({
            "ID Вакансии": v.id,
            "Название": v.title,
            "Компания": v.company,
            "Зарплата От": v.salary_from,
            "Зарплата До": v.salary_to,
            "Валюта": v.salary_currency,
            "Город": v.city,
            "Дата публикации": v.published_at,
            "Поисковой запрос": v.search_text,
            "Ключевые навыки": skills_str,
            "Ссылка": v.url
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()

    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return output
