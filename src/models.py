from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Базовый декларативный класс для генерации метаданных моделей SQAlchemy."""
    pass


vacancy_skills_association = Table(
    "vacancy_skills",
    Base.metadata,
    Column(
        "skill_id",
        Integer,
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True
    ),
    Column(
        "vacancy_id",
        String,
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        primary_key=True
    )
)


class Vacancy(Base):
    """
       ORM-модель для хранения информации о вакансиях с HeadHunter.

       Содержит базовые данные, собранные на этапе поисковой выдачи (Crawler),
       и расширенные данные (зарплата, точная дата, навыки), собираемые на этапе обогащения (Hydrator).

       Attributes:
           id (str): Уникальный идентификатор вакансии HH (извлекается из URL).
           search_text (str): Ключевое слово, по которому вакансия была найдена. Изучается через LIKE.
           is_detailed_parsed (bool): Флаг-маркер состояния конвейера. True, если вакансия обогащена деталями.
           skills (list[Skill]): Коллекция связанных ключевых навыков (отношение Many-to-Many).
       """
    __tablename__ = 'vacancies'

    id: Mapped[str] = mapped_column(String, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    salary_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    published_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    search_text: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_detailed_parsed: Mapped[bool] = mapped_column(Boolean, default=False, server_default='0', index=True)
    skills: Mapped[list["Skill"]] = relationship(
        secondary=vacancy_skills_association,
        back_populates="vacancies",
        passive_deletes=True
    )


class Skill(Base):
    """
        ORM-модель уникального справочника ключевых профессиональных навыков.

        Хранит очищенные текстовые теги технологий и требований (например, 'Python', 'Git').
        Связана с таблицей вакансий через ассоциативную таблицу со стратегией каскадного удаления.

        Attributes:
            id (int): Автоинкрементный первичный ключ.
            name (str): Уникальное имя навыка (индексировано для быстрого поиска при UPSERT).
            vacancies (list[Vacancy]): Список вакансий, в которых встречается данный навык.
    """
    __tablename__ = 'skills'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    vacancies: Mapped[list["Vacancy"]] = relationship(
        secondary=vacancy_skills_association,
        back_populates="skills",
    )
