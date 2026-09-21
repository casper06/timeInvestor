#!/usr/bin/env python3
"""
TimeInvestor Launcher
Ejecuta el servidor FastAPI con el dashboard web moderno compilado en un solo comando.
"""
import sys
import subprocess
from pathlib import Path
import webbrowser
import time

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"

def ensure_frontend_built():
    """Compiles frontend if dist directory doesn't exist."""
    if not (DIST_DIR / "index.html").exists():
        print("[TimeInvestor] Compilando frontend por primera vez...")
        try:
            # Install if node_modules missing
            if not (FRONTEND_DIR / "node_modules").exists():
                print("[TimeInvestor] Instalando dependencias de Node...")
                subprocess.run("npm install", cwd=str(FRONTEND_DIR), shell=True, check=True)
            # Run build
            subprocess.run("npm run build", cwd=str(FRONTEND_DIR), shell=True, check=True)
            print("[TimeInvestor] Frontend compilado con éxito.")
        except Exception as e:
            print(f"[TimeInvestor] Advertencia al compilar frontend: {e}")
            print("[TimeInvestor] Continuando con la inicialización del backend...")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Lanza TimeInvestor (Backend + Frontend)")
    parser.add_argument("--dev", action="store_true", help="Modo desarrollo (FastAPI reload + Vite dev server)")
    parser.add_argument("--no-browser", action="store_true", help="No abrir automáticamente el navegador")
    parser.add_argument("--port", type=int, default=8000, help="Puerto del servidor (default: 8000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host del servidor (default: 127.0.0.1)")
    args = parser.parse_args()

    ensure_frontend_built()

    url = f"http://{args.host}:{args.port}"
    print("=" * 65)
    print(f"  TimeInvestor - Motor Cuantitativo y Proyección de Tesis")
    print(f"  Accede en tu navegador: {url}")
    print(f"  Documentación Swagger:   {url}/docs")
    print("=" * 65)

    if not args.no_browser:
        # Delay opening slightly so server can bind
        def open_browser():
            time.sleep(1.2)
            webbrowser.open(url)
        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn
    from backend.config import settings
    uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=args.dev)

if __name__ == "__main__":
    main()
