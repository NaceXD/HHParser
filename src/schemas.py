"""
Модуль схем валидации Pydantic v2.

Используется для сериализации данных, поступающих от парсера,
и валидации ответов API (FastAPI) с поддержкой ORM-совместимости SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SkillSchema(BaseModel):
    """Схема для валидации и сериализации профессиональных навыков."""
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class VacancyBase(BaseModel):
    """Базовая схема вакансии, содержащая общие поля для создания и ответа"""
    id: str
    title: str
    company: Optional[str] = None
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    salary_currency: Optional[str] = None
    url: str
    city: Optional[str] = None
    published_at: Optional[str] = None
    search_text: str


class VacancyCreate(VacancyBase):
    """Схема, используемая парсером при первичной регистрации вакансии в БД."""
    is_detailed_parsed: Optional[bool] = False


class VacancyResponse(VacancyBase):
    """Схема ответа API для передачи полной информации о вакансии клиенту."""
    created_at: datetime
    is_detailed_parsed: bool
    skills: list[SkillSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
