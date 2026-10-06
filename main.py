from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from db import get_vacancies
from parser import parse_vacancies

app = FastAPI(title="HH Parser API")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    CORSMiddleware,  # type: ignore
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_index():
    return FileResponse("templates/index.html")


@app.get("/api/vacancies")
def get_vacancies_api(search: str = None, limit: int = None):
    return get_vacancies(search=search, limit=limit)


@app.post("/api/parser/start")
def start_parsing_api(search_text: str, background_tasks: BackgroundTasks):
    if not search_text.strip():
        return {"error": "Поисковой запрос не может быть пустым"}

    background_tasks.add_task(parse_vacancies, search_text.strip())
    return {"message": f"Парсинг по запросу '{search_text}' успешно запущено в фоновом режиме."}
