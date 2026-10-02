import sqlite3
from contextlib import contextmanager
from queue import Queue
from typing import Generator

DB_NAME = "hh_vacancies.db"

# Пул на 5 соединений
_pool: Queue[sqlite3.Connection] = Queue(maxsize=5)


def _create_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except sqlite3.Error:
        pass
    return conn


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    if _pool.empty():
        conn = _create_connection()
    else:
        conn = _pool.get_nowait()
    try:
        yield conn
    finally:
        if _pool.full():
            conn.close()
        else:
            _pool.put_nowait(conn)


def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Таблица вакансий
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS vacancies (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT,
                salary_from INTEGER,
                salary_to INTEGER,
                salary_currency TEXT,
                url TEXT,
                city TEXT,
                published_at TEXT,
                search_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        # Таблица навыков
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vacancy_id TEXT,
                skill_name TEXT NOT NULL,
                FOREIGN KEY (vacancy_id) REFERENCES vacancies(id) ON DELETE CASCADE
            )"""
        )
        conn.commit()


def save_vacancy(vacancy: dict):
    new_search_text = vacancy.get("search_text", "").strip()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Используем ON CONFLICT DO UPDATE для склеивания поисковых запросов без дубликатов
        cursor.execute(
            """INSERT INTO vacancies (
                id, title, company, salary_from, salary_to, salary_currency, url, city, published_at, search_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    salary_from = excluded.salary_from,
                    salary_to = excluded.salary_to,
                    salary_currency = excluded.salary_currency,
                    url = excluded.url,
                    city = excluded.city,
                    published_at = excluded.published_at,
                    search_text = CASE 
                        WHEN vacancies.search_text LIKE '%' || ? || '%' THEN vacancies.search_text
                        ELSE vacancies.search_text || ', ' || ?
                    END
            """, (
                vacancy["id"],
                vacancy["title"],
                vacancy["company"],
                vacancy["salary_from"],
                vacancy["vacancy_to"] if "vacancy_to" in vacancy else vacancy.get("salary_to"),
                vacancy["salary_currency"],
                vacancy["url"],
                vacancy["city"],
                vacancy["published_at"],
                new_search_text,
                # Параметры для блока ON CONFLICT DO UPDATE:
                new_search_text,  # Для проверки LIKE
                new_search_text  # Для склейки, если слова еще нет
            ),
        )

        # Обновляем навыки (удаляем старые и пишем актуальные)
        cursor.execute("""DELETE FROM skills WHERE vacancy_id = ?""", (vacancy["id"],))
        for skill in vacancy.get("skills", []):
            cursor.execute(
                """INSERT INTO skills (vacancy_id, skill_name) VALUES (?, ?)""",
                (vacancy["id"], skill),
            )
        conn.commit()


def get_vacancies(limit: int = 100) -> list[dict]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        result = cursor.execute("""SELECT * FROM vacancies ORDER BY created_at DESC LIMIT ?""",
                                (limit,)).fetchall()
        return [dict(row) for row in result]


if __name__ == "__main__":
    init_db()
    print("База данных успешно инициализирована!")
