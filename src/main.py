"""
Точка входа веб-сервера FastAPI.

Реализует REST API эндпоинты для получения данных из БД, экспорта отчетов,
а также предоставляет интерфейс асинхронного управления жизненным циклом парсера.
"""

from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .crud import export_vacancies_to_exel, get_vacancies
from .db import get_db
from .parser.parser import run_full_parsing_pipeline
from .schemas import VacancyResponse
from .state import ACTIVE_TASKS, parser_state

app = FastAPI(title="HH Parser API")


@app.get("/api/parser/status")
def get_parser_status_api():
    """Возвращает текущий операционный статус и метрики фонового парсера."""
    return parser_state


@app.get("/api/vacancies", response_model=list[VacancyResponse])
def get_vacancies_api(db: Session = Depends(get_db), search: str | None = None, limit: int | None = None):
    """Опрашивает БД и возвращает список детально обработанных вакансий."""
    return get_vacancies(session=db, search=search, limit=limit)


@app.post("/api/parser/start")
async def start_parsing_api(search_text: str):
    """ Инициализирует и запускает асинхронный фоновый конвейер сбора вакансий."""
    if not search_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поисковой запрос не может быть пустым")
    if parser_state.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Парсер уже запущен")

    # Сброс метрик состояния перед стартом
    parser_state.status = "running"
    parser_state.current_keyword = search_text.lower().strip()
    parser_state.pages_scanned = 0
    parser_state.vacancies_found = 0
    parser_state.captcha_encountered = False
    parser_state.last_error = None

    asyncio.create_task(run_full_parsing_pipeline(search_text.lower().strip()))

    return {"message": f"Парсинг по запросу '{search_text}' успешно запущен в фоновом режиме"}

@app.post("/api/parser/stop")
def stop_parsing_api():
    """Принудительно останавливает активные задачи краулера и гидратора."""
    if parser_state.status != "running":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Парсер не запущен")

    if ACTIVE_TASKS["crawler"] is not None:
        ACTIVE_TASKS["crawler"].cancel()
    if ACTIVE_TASKS["hydrator"] is not None:
        ACTIVE_TASKS["hydrator"].cancel()

    parser_state.status = "stopped"
    parser_state.last_error = "Процесс остановлен пользователем"

    ACTIVE_TASKS["crawler"] = None
    ACTIVE_TASKS["hydrator"] = None

    return {"message": "Парсинг успешно остановлен пользователем"}


@app.get("/api/vacancies/export/exel")
def export_vacancies_api(search: str | None = None, db: Session = Depends(get_db)):
    """Формирует и отдает клиенту файл Excel со списком вакансий в виде бинарного потока."""
    file_buffer = export_vacancies_to_exel(session=db, search=search)
    return StreamingResponse(
        file_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=vacancies.xlsx"},
    )
