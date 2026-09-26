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


class EngineDecisionModel(Base):
    """
    Caches EngineSelector's per-series auto-discovery decision (Holt vs TimesFM),
    so the mini-backtest that produces it (see backend/services/auto_discovery.py)
    only runs once per series per TTL window, not on every forecast request.
    One row per series_id — "set" semantics (upsert), never appended history.
    """
    __tablename__ = "engine_decisions"

    series_id = Column(String(50), primary_key=True)
    engine_choice = Column(String(20), nullable=False)  # "holt" or "timesfm"
    evaluated_at = Column(DateTime, default=get_utc_now, nullable=False)
    mase_holt = Column(Float, nullable=False)
    mase_timesfm = Column(Float, nullable=True)  # null if TimesFM was unavailable during evaluation
    n_points_at_evaluation = Column(Integer, nullable=False)
    # Cutoffs where TimesFM was loaded but fell back to Holt internally (so its
    # "MASE" there would really be Holt's and is discarded). NULL on rows from
    # before this column existed, or when TimesFM wasn't available at all.
    timesfm_failed_cutoffs = Column(Integer, nullable=True)
    # Version of the evaluation criterion (auto_discovery.AUTO_DISCOVERY_CRITERIA_VERSION).
    # Older version -> stale. NULL on rows from before this column (= v1).
    criteria_version = Column(Integer, nullable=True)
    # What TimesFM was compared against (v3+): "holt" or "holt_winters", and
    # with which metric: "mase" (1-step) or "mase_seasonal". NULL = legacy
    # (Holt, 1-step MASE). mase_holt holds the BASELINE's error.
    baseline_engine = Column(String(20), nullable=True)
    metric = Column(String(20), nullable=True)
    baseline_skipped_cutoffs = Column(Integer, nullable=True)


class ClaudeCliUsageModel(Base):
    """
    Tracks Claude Code CLI usage (backend/services/llm_router.py's
    ClaudeCliLLMClient) per day per model. Not for billing — Claude CLI runs on
    the user's Pro/Max SUBSCRIPTION, not pay-per-use — but total_cost_usd is
    the only signal available anywhere for how much of the user's SHARED
    5-hour/weekly Claude usage window this feature is consuming, since that
    quota isn't visible from any other part of this project. One row per
    (usage_date, model) pair, incremented across calls that day.
    """
    __tablename__ = "claude_cli_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    usage_date = Column(String(10), nullable=False)  # ISO date, e.g. "2026-09-24"
    model = Column(String(50), nullable=False)
    call_count = Column(Integer, default=0, nullable=False)
    total_cost_usd = Column(Float, default=0.0, nullable=False)
