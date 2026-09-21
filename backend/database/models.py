import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from backend.database.connection import Base

def get_utc_now():
    return datetime.now(timezone.utc)

class ThesisModel(Base):
    __tablename__ = "theses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    status = Column(String(50), default="Activa", nullable=False)
    tickers_json = Column(Text, nullable=False, default="[]")
    macro_series_json = Column(Text, nullable=False, default="[]")
    rationales_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    snapshots = relationship(
        "ForecastSnapshotModel",
        back_populates="thesis",
        cascade="all, delete-orphan",
        order_by="desc(ForecastSnapshotModel.created_at)"
    )
    notes = relationship(
        "ResearchNoteModel",
        back_populates="thesis",
        cascade="all, delete-orphan",
        order_by="desc(ResearchNoteModel.created_at)"
    )


class ForecastSnapshotModel(Base):
    __tablename__ = "forecast_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thesis_id = Column(String(36), ForeignKey("theses.id", ondelete="CASCADE"), nullable=False)
    series_id = Column(String(50), nullable=False)
    cutoff_date = Column(String(50), nullable=False)
    horizon = Column(Integer, default=60, nullable=False)
    confidence = Column(Float, default=0.95, nullable=False)
    timestamps_json = Column(Text, nullable=False, default="[]")
    projected_values_json = Column(Text, nullable=False, default="[]")
    lower_bound_json = Column(Text, nullable=False, default="[]")
    upper_bound_json = Column(Text, nullable=False, default="[]")
    model_name = Column(String(100), default="timesfm-mock-v1", nullable=False)
    created_at = Column(DateTime, default=get_utc_now, nullable=False)

    thesis = relationship("ThesisModel", back_populates="snapshots")


class ResearchNoteModel(Base):
    __tablename__ = "research_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thesis_id = Column(String(36), ForeignKey("theses.id", ondelete="CASCADE"), nullable=False)
    note_text = Column(Text, nullable=False)
    author = Column(String(100), default="Analista", nullable=False)
    created_at = Column(DateTime, default=get_utc_now, nullable=False)

    thesis = relationship("ThesisModel", back_populates="notes")
