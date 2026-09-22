import json
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.connection import get_db
from backend.database.models import ThesisModel, ForecastSnapshotModel, ResearchNoteModel
from backend.schemas.models import (
    ThesisRequest,
    ThesisResponse,
    TimeSeriesData,
    ForecastRequest,
    ForecastResponse,
    FundamentalsResponse,
    InterpretationContext,
    InterpretationResponse,
    HealthResponse,
    ThesisCreateRequest,
    ThesisUpdateRequest,
    ThesisSummaryItem,
    ThesisDetailResponse,
    ForecastSnapshotCreateRequest,
    ForecastSnapshotResponse,
    ResearchNoteCreateRequest,
    ResearchNoteResponse,
    BacktestRequest,
    BacktestResponse,
    CorrelationRequest,
    CorrelationMatrixResponse,
    TickerSuggestion,
    MacroSuggestion,
    PortfolioOptimizeRequest,
    PortfolioOptimizeResponse,
    PortfolioRiskRequest,
    PortfolioRiskResponse,
)
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher
from backend.services.llm_router import get_llm_client
from backend.services.forecast_engine import get_forecast_engine
from backend.services.backtest_engine import BacktestEngine
from backend.services.correlation_engine import CorrelationEngine
from backend.services.portfolio_engine import PortfolioEngine
from backend.services.risk_engine import RiskEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["TimeInvestor API"])

fred_fetcher = FREDDataFetcher()

# ----------------- FASE 1: HEALTH, THESIS & INGESTION -----------------

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Returns operational status and active engine configurations."""
    engine = get_forecast_engine()
    return HealthResponse(
        status="ok",
        llm_provider=settings.effective_llm_provider,
        forecast_engine=engine.model_name,
        use_real_timesfm=settings.USE_REAL_TIMESFM,
        has_gemini_key=bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip()),
        has_fred_key=bool(settings.FRED_API_KEY and settings.FRED_API_KEY.strip()),
        has_openai_key=bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip())
    )

@router.post("/thesis", response_model=ThesisResponse)
async def analyze_thesis(
    payload: ThesisRequest,
    force_mock: bool = Query(
        default=False,
        description="Si es true, fuerza MockLLMClient (gratis, sin red) ignorando el proveedor "
                    "configurado. Usado por el frontend para el placeholder inicial en mount, "
                    "donde nunca se debe consumir cuota de un proveedor real sin acción del usuario."
    ),
):
    """
    Translates a free-form investment thesis into structured tickers and macro series.
    Uses Gemini API if configured, or falls back to local semantic router.
    Note: force_mock can only ever *downgrade* to the free local engine — it cannot
    be used to select or escalate to a paid provider.
    """
    try:
        client = get_llm_client("mock") if force_mock else get_llm_client()
        result = await client.parse_thesis(payload.thesis)
        return result
    except Exception as e:
        logger.error(f"Error processing thesis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to analyze thesis: {str(e)}")

@router.get("/data/market", response_model=TimeSeriesData)
def get_market_data(
    ticker: str = Query(..., description="Stock ticker symbol, e.g. NVDA"),
    period: str = Query(default="2y", description="Time period: 1mo, 6mo, 1y, 2y, 5y, max")
):
    """Fetches normalized historical market price time series using yfinance."""
    try:
        return MarketDataFetcher.get_history(ticker=ticker, period=period)
    except ValueError as ve:
        logger.warning(f"Validation/Missing data for {ticker}: {ve}")
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Error fetching market data for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not retrieve data for {ticker}: {str(e)}")

@router.get("/data/macro", response_model=TimeSeriesData)
def get_macro_data(
    series_id: str = Query(..., description="FRED series ID, e.g. IPG2211A2N"),
    limit: int = Query(default=500, ge=10, le=1000)
):
    """Fetches normalized macroeconomic or energy time series from FRED."""
    try:
        return fred_fetcher.get_series(series_id=series_id, limit=limit)
    except ValueError as ve:
        logger.warning(f"Validation/Missing data for FRED {series_id}: {ve}")
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Error fetching FRED series {series_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not retrieve FRED series {series_id}: {str(e)}")

@router.get("/data/fundamentals", response_model=FundamentalsResponse)
def get_fundamentals_data(
    tickers: str = Query(..., description="Comma-separated ticker list, e.g. NVDA,MSFT,CEG")
):
    """Fetches fundamental financial metrics (Capex and Revenue) for comparison."""
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        if not ticker_list:
            raise HTTPException(status_code=400, detail="No tickers provided")
        metrics, warnings = MarketDataFetcher.get_fundamentals(ticker_list)
        return FundamentalsResponse(metrics=metrics, warnings=warnings)
    except Exception as e:
        logger.error(f"Error fetching fundamentals: {e}")
        raise HTTPException(status_code=500, detail=f"Could not retrieve fundamentals: {str(e)}")

@router.post("/forecast", response_model=ForecastResponse)
def generate_forecast(payload: ForecastRequest):
    """
    Generates time series projection and confidence intervals.
    Returns TimesFM-compliant structure: { timestamps, values, lower_bound, upper_bound }.
    """
    try:
        engine = get_forecast_engine()
        result = engine.forecast(
            points=payload.points,
            horizon=payload.horizon,
            confidence=payload.confidence,
            freq=payload.freq or "D"
        )
        return result
    except Exception as e:
        logger.error(f"Error computing forecast: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Forecast generation failed: {str(e)}")

@router.post("/interpret", response_model=InterpretationResponse)
async def interpret_thesis_situation(payload: InterpretationContext):
    """
    Copilot endpoint providing plain-language quantitative interpretation
    of active curves, thesis alignment, and next suggested series to inspect.
    """
    try:
        client = get_llm_client()
        return await client.interpret_situation(payload)
    except Exception as e:
        logger.error(f"Error interpreting situation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Interpretation failed: {str(e)}")

@router.get("/catalog/macro")
async def get_macro_catalog():
    """Returns curated catalog of macroeconomic and energy indicators available."""
    return FREDDataFetcher.SERIES_CATALOG


# ----------------- FASE 2: PERSISTENCIA CRUD DE TESIS -----------------

@router.get("/theses", response_model=List[ThesisSummaryItem])
def list_theses(db: Session = Depends(get_db)):
    """Lists all saved investment theses with summary counts."""
    theses = db.query(ThesisModel).order_by(ThesisModel.created_at.desc()).all()
    results = []
    for t in theses:
        try:
            tickers = json.loads(t.tickers_json)
            ticker_syms = [item.get("symbol") for item in tickers if isinstance(item, dict)]
        except Exception:
            ticker_syms = []

        try:
            macros = json.loads(t.macro_series_json)
            macro_ids = [item.get("series_id") for item in macros if isinstance(item, dict)]
        except Exception:
            macro_ids = []

        results.append(ThesisSummaryItem(
            id=t.id,
            title=t.title,
            prompt=t.prompt,
            summary=t.summary or "",
            status=t.status,
            ticker_symbols=ticker_syms,
            macro_ids=macro_ids,
            created_at=t.created_at.isoformat() if t.created_at else "",
            updated_at=t.updated_at.isoformat() if t.updated_at else "",
            snapshot_count=len(t.snapshots),
            note_count=len(t.notes)
        ))
    return results

@router.post("/theses", response_model=ThesisDetailResponse)
def create_thesis(payload: ThesisCreateRequest, db: Session = Depends(get_db)):
    """Saves a new investment thesis with assigned assets and rationales."""
    thesis_id = str(uuid.uuid4())
    new_thesis = ThesisModel(
        id=thesis_id,
        title=payload.title,
        prompt=payload.prompt,
        summary=payload.summary or "",
        status=payload.status or "Activa",
        tickers_json=json.dumps([t.model_dump() for t in payload.tickers]),
        macro_series_json=json.dumps([m.model_dump() for m in payload.macro_series]),
        rationales_json=json.dumps(payload.rationales or {})
    )
    db.add(new_thesis)
    db.commit()
    db.refresh(new_thesis)

    return _format_thesis_detail(new_thesis)

@router.get("/theses/{thesis_id}", response_model=ThesisDetailResponse)
def get_thesis(thesis_id: str, db: Session = Depends(get_db)):
    """Retrieves full details of a saved thesis including snapshots and research notes."""
    thesis = db.query(ThesisModel).filter(ThesisModel.id == thesis_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Tesis no encontrada")
    return _format_thesis_detail(thesis)

@router.put("/theses/{thesis_id}", response_model=ThesisDetailResponse)
def update_thesis(thesis_id: str, payload: ThesisUpdateRequest, db: Session = Depends(get_db)):
    """Updates thesis title, status (e.g. 'Activa', 'Bajo estrés', 'Archivada') or summary."""
    thesis = db.query(ThesisModel).filter(ThesisModel.id == thesis_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Tesis no encontrada")

    if payload.title is not None:
        thesis.title = payload.title
    if payload.status is not None:
        thesis.status = payload.status
    if payload.summary is not None:
        thesis.summary = payload.summary
    if payload.tickers is not None:
        thesis.tickers_json = json.dumps([t.model_dump() for t in payload.tickers])

    db.commit()
    db.refresh(thesis)
    return _format_thesis_detail(thesis)

@router.delete("/theses/{thesis_id}")
def delete_thesis(thesis_id: str, db: Session = Depends(get_db)):
    """Deletes a saved thesis and its associated snapshots/notes."""
    thesis = db.query(ThesisModel).filter(ThesisModel.id == thesis_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Tesis no encontrada")
    db.delete(thesis)
    db.commit()
    return {"status": "deleted", "id": thesis_id}

@router.post("/theses/{thesis_id}/snapshots", response_model=ForecastSnapshotResponse)
def add_forecast_snapshot(
    thesis_id: str,
    payload: ForecastSnapshotCreateRequest,
    db: Session = Depends(get_db)
):
    """Registers an audit snapshot of a projection for historical reality-check."""
    thesis = db.query(ThesisModel).filter(ThesisModel.id == thesis_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Tesis no encontrada")

    snap = ForecastSnapshotModel(
        thesis_id=thesis_id,
        series_id=payload.series_id.upper(),
        cutoff_date=payload.cutoff_date,
        horizon=payload.horizon,
        confidence=payload.confidence,
        timestamps_json=json.dumps(payload.timestamps),
        projected_values_json=json.dumps(payload.projected_values),
        lower_bound_json=json.dumps(payload.lower_bound),
        upper_bound_json=json.dumps(payload.upper_bound),
        model_name=payload.model_name or "timesfm"
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)

    return ForecastSnapshotResponse(
        id=snap.id,
        thesis_id=snap.thesis_id,
        series_id=snap.series_id,
        cutoff_date=snap.cutoff_date,
        horizon=snap.horizon,
        confidence=snap.confidence,
        timestamps=json.loads(snap.timestamps_json),
        projected_values=json.loads(snap.projected_values_json),
        lower_bound=json.loads(snap.lower_bound_json),
        upper_bound=json.loads(snap.upper_bound_json),
        model_name=snap.model_name,
        created_at=snap.created_at.isoformat() if snap.created_at else ""
    )

@router.post("/theses/{thesis_id}/notes", response_model=ResearchNoteResponse)
def add_research_note(
    thesis_id: str,
    payload: ResearchNoteCreateRequest,
    db: Session = Depends(get_db)
):
    """Appends qualitative analyst research notes to a thesis."""
    thesis = db.query(ThesisModel).filter(ThesisModel.id == thesis_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Tesis no encontrada")

    note = ResearchNoteModel(
        thesis_id=thesis_id,
        note_text=payload.note_text,
        author=payload.author or "Analista"
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return ResearchNoteResponse(
        id=note.id,
        note_text=note.note_text,
        author=note.author,
        created_at=note.created_at.isoformat() if note.created_at else ""
    )

def _format_thesis_detail(t: ThesisModel) -> ThesisDetailResponse:
    tickers = [TickerSuggestion(**item) for item in json.loads(t.tickers_json or "[]")]
    macro = [MacroSuggestion(**item) for item in json.loads(t.macro_series_json or "[]")]
    rationales = json.loads(t.rationales_json or "{}")

    snapshots = [
        ForecastSnapshotResponse(
            id=s.id,
            thesis_id=s.thesis_id,
            series_id=s.series_id,
            cutoff_date=s.cutoff_date,
            horizon=s.horizon,
            confidence=s.confidence,
            timestamps=json.loads(s.timestamps_json or "[]"),
            projected_values=json.loads(s.projected_values_json or "[]"),
            lower_bound=json.loads(s.lower_bound_json or "[]"),
            upper_bound=json.loads(s.upper_bound_json or "[]"),
            model_name=s.model_name,
            created_at=s.created_at.isoformat() if s.created_at else ""
        )
        for s in t.snapshots
    ]

    notes = [
        ResearchNoteResponse(
            id=n.id,
            note_text=n.note_text,
            author=n.author,
            created_at=n.created_at.isoformat() if n.created_at else ""
        )
        for n in t.notes
    ]

    return ThesisDetailResponse(
        id=t.id,
        title=t.title,
        prompt=t.prompt,
        summary=t.summary or "",
        status=t.status,
        tickers=tickers,
        macro_series=macro,
        rationales=rationales,
        created_at=t.created_at.isoformat() if t.created_at else "",
        updated_at=t.updated_at.isoformat() if t.updated_at else "",
        snapshots=snapshots,
        notes=notes
    )


# ----------------- FASE 2: BACKTESTING Y CORRELACIÓN -----------------

@router.post("/backtest", response_model=BacktestResponse)
def run_backtest(payload: BacktestRequest):
    """
    Evaluates projection fidelity against ground-truth historical data.
    Truncates series at cutoff_date, forecasts horizon steps, and computes MAE, MAPE, Directional Accuracy.
    """
    try:
        return BacktestEngine.run_backtest(
            series_id=payload.series_id,
            cutoff_date=payload.cutoff_date,
            horizon=payload.horizon,
            confidence=payload.confidence
        )
    except ValueError as ve:
        err_msg = str(ve)
        if "sintética" in err_msg.lower():
            raise HTTPException(status_code=422, detail=err_msg)
        raise HTTPException(status_code=400, detail=err_msg)
    except Exception as e:
        logger.error(f"Error running backtest: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {str(e)}")

@router.post("/correlation", response_model=CorrelationMatrixResponse)
def compute_correlations(payload: CorrelationRequest):
    """
    Computes Pearson and Spearman cross-asset correlation matrices for portfolio tickers and macro series.
    """
    try:
        return CorrelationEngine.calculate_correlations(
            series_ids=payload.series_ids,
            period=payload.period,
            mode=payload.mode
        )
    except ValueError as ve:
        err_msg = str(ve)
        if "sintética" in err_msg.lower():
            raise HTTPException(status_code=422, detail=err_msg)
        raise HTTPException(status_code=400, detail=err_msg)
    except Exception as e:
        logger.error(f"Error calculating correlation matrix: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Correlation computation failed: {str(e)}")


@router.post("/portfolio/optimize", response_model=PortfolioOptimizeResponse)
def optimize_portfolio(payload: PortfolioOptimizeRequest):
    """
    Computes optimal portfolio allocations (Max Sharpe with SLSQP Dirichlet restarts,
    Risk Parity via Spinu barrier, and benchmarks) using Ledoit-Wolf shrinkage.
    """
    try:
        return PortfolioEngine.optimize_portfolio(payload)
    except ValueError as ve:
        err_msg = str(ve)
        if "synthetic" in err_msg.lower() or "sintética" in err_msg.lower():
            raise HTTPException(status_code=422, detail=err_msg)
        raise HTTPException(status_code=400, detail=err_msg)
    except Exception as e:
        logger.error(f"Error optimizing portfolio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Portfolio optimization failed: {str(e)}")


@router.post("/portfolio/risk", response_model=PortfolioRiskResponse)
def evaluate_portfolio_risk(payload: PortfolioRiskRequest):
    """
    Simulates portfolio risk distribution (Bootstrap, Student-t, Gaussian)
    and computes positive-loss VaR, CVaR, SE, and tail distribution metrics.
    """
    try:
        return RiskEngine.evaluate_risk(payload)
    except ValueError as ve:
        err_msg = str(ve)
        if "synthetic" in err_msg.lower() or "sintética" in err_msg.lower():
            raise HTTPException(status_code=422, detail=err_msg)
        raise HTTPException(status_code=400, detail=err_msg)
    except Exception as e:
        logger.error(f"Error evaluating portfolio risk: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Portfolio risk evaluation failed: {str(e)}")

