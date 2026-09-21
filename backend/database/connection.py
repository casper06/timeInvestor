from pathlib import Path
from sqlalchemy import create_engine
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

def init_db():
    """Automatically initialize database tables."""
    from backend.database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
