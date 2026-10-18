"""
Модуль глобального состояния фонового парсера.

Обеспечивает централизованный контроль за статусом выполнения задач,
метриками сбора данных и хранит ссылки на активные асинхронные потоки (Tasks)
для возможности их корректной отмены из API.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel


class ParserState(BaseModel):
    """
       Pydantic-модель текущего операционного статуса парсера.

       Хранит динамические метрики текущей сессии сбора данных. Значения
       могут напрямую отдаваться клиенту через API-эндпоинты.
   """
    status: str = "idle"
    current_keyword: str | None = None
    pages_scanned: int = 0
    vacancies_found: int = 0
    captcha_encountered: bool = False
    last_error: str | None = None


# Единый глобальный объект состояния для всего приложения
parser_state = ParserState()

# Глобальны реестр активных асинхронных задач для управления их жизненным циклом
ACTIVE_TASKS: dict[str, asyncio.Task[Any] | None] = {
    "crawler": None,
    "hydrator": None
}
