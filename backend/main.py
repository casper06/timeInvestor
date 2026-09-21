import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

from contextlib import asynccontextmanager
from backend.config import settings
from backend.database.connection import init_db
from backend.api.routes import router as api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TimeInvestor")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando tablas de base de datos SQLite...")
    init_db()
    yield

app = FastAPI(
    title="TimeInvestor API",
    description="Quantitative Investment Thesis Analysis, Monitoring and Forecasting Engine",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local modern web frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register REST API routes
app.include_router(api_router)

# Mount frontend static distribution if built
dist_path = settings.STATIC_DIR
if dist_path.exists() and (dist_path / "index.html").exists():
    logger.info(f"Serving built frontend from {dist_path}")
    # Mount static assets (assets/css/js)
    app.mount("/assets", StaticFiles(directory=str(dist_path / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Serve index.html for client-side routing if file doesn't exist
        file_candidate = dist_path / full_path
        if full_path and file_candidate.exists() and file_candidate.is_file():
            return FileResponse(file_candidate)
        return FileResponse(dist_path / "index.html")
else:
    @app.get("/")
    async def root_fallback():
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>TimeInvestor API Engine</title>
            <meta charset="utf-8">
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; }
                .card { background: #1e293b; border-radius: 12px; padding: 24px; max-width: 650px; margin: 0 auto; border: 1px solid #334155; }
                h1 { color: #38bdf8; margin-top: 0; }
                a { color: #38bdf8; text-decoration: none; }
                a:hover { text-decoration: underline; }
                .badge { background: #0284c7; color: white; padding: 4px 10px; border-radius: 6px; font-size: 13px; }
                pre { background: #090d16; padding: 12px; border-radius: 8px; color: #a5f3fc; overflow-x: auto; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>TimeInvestor API <span class="badge">Backend Active</span></h1>
                <p>El backend de TimeInvestor está corriendo exitosamente.</p>
                <ul>
                    <li><a href="/docs" target="_blank">Explorar documentación Swagger interactiva (/docs)</a></li>
                    <li><a href="/api/health" target="_blank">Verificar estado del sistema (/api/health)</a></li>
                </ul>
                <p>El frontend se está construyendo o puede ejecutarse en modo desarrollo mediante:</p>
                <pre>cd frontend && npm run dev</pre>
            </div>
        </body>
        </html>
        """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
