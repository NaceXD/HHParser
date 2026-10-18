from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# --- Блок конфигураций путей и окружения ---
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parent.parent
DB_PATH = PROJECT_ROOT / "hh_vacancies.db"

# --- Инициализация движка SQLAlchemy ---
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"timeout": 30, "check_same_thread": False},
    pool_size=10,
    max_overflow=20
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record):
    """
    Событийный воркер для оптимизации производительности SQLite при подключении.
    Включает режим WAL(Write-Ahead Logging) для безопасной параллельной записи
    и синхронизацию NORMAL для ускорения транзакций фонового конвейера.
    """
    cursor = dbapi_connection.cursor()
    try:
        # 2. Выполняем оптимизирующие команды
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
    finally:
        # 3. Блок finally выполнится ВСЕГДА, даже если execute упадет с ошибкой.
        # Это гарантирует защиту от утечки соединений без использования блока 'with'.
        cursor.close()

# --- Настройка фабрики сессий ---
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Зависимость для управления жизненным циклом сессии БД в FastAPI.
    Открывает изолированную транзакцию на один HTTP-запрос и гарантированно
    закрывает сессию после отправки ответа клиенту.

    Yields:
         Generator[Session, None, None]: Экземпляр активной сессии SQAlchemy.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
