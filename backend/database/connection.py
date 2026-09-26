from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import settings

# Database connection string
DATABASE_URL = settings.DATABASE_URL

# Ensure parent directory exists for SQLite database
if DATABASE_URL.startswith("sqlite:///"):
    db_raw = DATABASE_URL.replace("sqlite:///", "")
    db_file = Path(db_raw)
    if not db_file.is_absolute():
        db_file = settings.BASE_DIR / db_file
    db_file.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{db_file}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Columns added to an existing table after it was first created. create_all()
# only creates missing TABLES, never missing columns, so an older database
# needs these added by hand. (table, column, SQL type), all nullable.
_ADDED_COLUMNS = [
    ("engine_decisions", "timesfm_failed_cutoffs", "INTEGER"),
    ("engine_decisions", "criteria_version", "INTEGER"),
    ("engine_decisions", "baseline_engine", "VARCHAR(20)"),
    ("engine_decisions", "metric", "VARCHAR(20)"),
    ("engine_decisions", "baseline_skipped_cutoffs", "INTEGER"),
]


def migrate_added_columns(bind) -> list:
    """Adds any column from _ADDED_COLUMNS missing in an existing table.
    Idempotent. Returns the "table.column" names it added."""
    added = []
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    with bind.begin() as conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            if table not in existing_tables:
                continue  # create_all() creates it with every column
            if column in {c["name"] for c in inspector.get_columns(table)}:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
            added.append(f"{table}.{column}")
    return added


def init_db():
    """Automatically initialize database tables."""
    from backend.database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    migrate_added_columns(engine)
