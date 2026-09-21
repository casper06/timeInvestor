#!/usr/bin/env python3
"""
TimeInvestor - TimesFM Download, Diagnostics & Benchmarking Utility
===================================================================
Script standalone para verificar el entorno de ejecución, descargar pesos oficiales
de Hugging Face ('google/timesfm-1.0-200m-pytorch'), y evaluar latencia y precisión
frente a Damped Holt y Naive Random Walk.

REGLA DE INTEGRIDAD:
Si PyTorch o los pesos de TimesFM no están presentes, NUNCA fabrica datos ficticios:
el reporte declara explícitamente "TimesFM no evaluado: pesos no disponibles".
"""

import sys
import os
import time
import argparse
import platform
from pathlib import Path
from typing import Optional, Dict, Tuple
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.forecast_engine import DampedHoltForecastEngine


def get_system_ram_gb() -> float:
    """Returns available system RAM in GB using psutil or platform-specific methods."""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        pass

    if platform.system() == "Windows":
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        except Exception:
            return -1.0
    return -1.0


def check_dependencies(allow_missing: bool = False):
    """Verifica presencia de torch, transformers y huggingface_hub."""
    missing = []
    for pkg in ["torch", "transformers", "huggingface_hub"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print("\n" + "=" * 70)
        print(" [!] AVISO: Faltan dependencias requeridas para ejecutar TimesFM real:")
        for m in missing:
            print(f"     - {m}")
        print("\n Para instalarlas, ejecute:")
        print(f"     pip install {' '.join(missing)}")
        if not allow_missing:
            print(" Para continuar y evaluar los modelos base declarando TimesFM no disponible:")
            print("     python scripts/download_and_benchmark_timesfm.py --allow-missing")
            print("=" * 70 + "\n")
            sys.exit(1)
        print("=" * 70 + "\n")
    return missing


def report_environment(forced_device: str = None) -> str:
    """Reporta dispositivo, VRAM y RAM del sistema."""
    print("=" * 70)
    print(" 1. DIAGNÓSTICO DEL ENTORNO DE HARDWARE Y SOFTWARE")
    print("=" * 70)
    ram_gb = get_system_ram_gb()
    print(f"  Sistema Operativo:    {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  Python:               {platform.python_version()}")
    print(f"  Memoria RAM Total:    {ram_gb:.1f} GB" if ram_gb > 0 else "  Memoria RAM Total:    No disponible")

    try:
        import torch
        available_device = "cpu"
        if torch.cuda.is_available():
            available_device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            available_device = "mps"

        target_device = forced_device if forced_device else available_device
        print(f"  Dispositivo detectado: {available_device.upper()}")
        print(f"  Dispositivo en uso:   {target_device.upper()}")

        if target_device == "cuda":
            gpu_name = torch.cuda.get_device_name(0)
            total_vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            free_vram = torch.cuda.memory_reserved(0) / (1024 ** 3)
            print(f"  GPU Modelo:           {gpu_name}")
            print(f"  VRAM Total / Libre:   {total_vram:.2f} GB / {total_vram - free_vram:.2f} GB")

        return target_device
    except ImportError:
        print("  PyTorch:              No instalado en el entorno de Python actual")
        print(f"  Dispositivo activo:   CPU (ejecución mediante motor local estadístico)")
        return "cpu"


def check_and_download_weights(repo_id: str = "google/timesfm-1.0-200m-pytorch", auto_confirm: bool = False) -> bool:
    """Verifica si el checkpoint está en caché local de HF y gestiona su descarga."""
    print("\n" + "=" * 70)
    print(" 2. VERIFICACIÓN DE CHECKPOINT HUGGING FACE")
    print("=" * 70)
    try:
        from huggingface_hub import constants, snapshot_download
    except ImportError:
        print("  [!] huggingface_hub no está instalado. Omitiendo verificación de descarga.")
        return False

    cache_dir = Path(constants.HF_HUB_CACHE)
    expected_repo_dir = cache_dir / f"models--{repo_id.replace('/', '--')}"
    print(f"  Repositorio objetivo:  {repo_id}")
    print(f"  Directorio caché HF:  {cache_dir}")

    is_cached = expected_repo_dir.exists() and any(expected_repo_dir.iterdir())
    if is_cached:
        print("  [✓] El modelo ya se encuentra descargado en la caché local.")
        return True

    print("  [i] El modelo NO se encuentra en la caché local.")
    print("      Tamaño estimado de descarga: ~800 MB (pesos PyTorch bfloat16 / fp32).")

    if not auto_confirm:
        resp = input("  ¿Desea iniciar la descarga ahora? [y/N]: ").strip().lower()
        if resp not in ["y", "yes", "s", "si", "sí"]:
            print("  [!] Descarga cancelada por el usuario. No se puede ejecutar TimesFM real.")
            return False

    print("  Iniciando descarga mediante snapshot_download (esto puede tardar unos minutos)...")
    try:
        snapshot_download(repo_id=repo_id)
        print("  [✓] Descarga completada con éxito.")
        return True
    except Exception as e:
        print(f"  [ERROR] Falló la descarga: {e}")
        return False


def get_real_timesfm_engine():
    """
    Intenta inicializar y verificar TimesFMForecastEngine con su modelo real cargado.
    Retorna el engine si y solo si el modelo PyTorch real fue instanciado exitosamente.
    En caso contrario, retorna None.
    """
    try:
        from backend.services.forecast_engine import TimesFMForecastEngine
        engine = TimesFMForecastEngine()
        if engine._model is None:
            engine._load_model()
        if engine._model is not None:
            return engine
        return None
    except Exception:
        return None


def generate_benchmark_series():
    """Genera 5 series sintéticas representativas de dinámicas de mercado."""
    rng = np.random.default_rng(2026)
    T = 512
    H = 60
    total = T + H

    # 1. Alcista (Uptrend)
    shocks_up = rng.normal(0.0010, 0.012, total)
    up = 100.0 * np.exp(np.cumsum(shocks_up))

    # 2. Bajista (Downtrend)
    shocks_down = rng.normal(-0.0010, 0.012, total)
    down = 100.0 * np.exp(np.cumsum(shocks_down))

    # 3. Lateral (Mean-Reverting Ornstein-Uhlenbeck)
    lateral = np.zeros(total)
    lateral[0] = 100.0
    for t in range(1, total):
        lateral[t] = lateral[t-1] + 0.08 * (100.0 - lateral[t-1]) + rng.normal(0, 1.2)

    # 4. Alta Volatilidad (Jump diffusion)
    jumps = rng.choice([0.0, 0.04, -0.04], size=total, p=[0.94, 0.03, 0.03])
    shocks_vol = rng.normal(0.0, 0.030, total) + jumps
    high_vol = 100.0 * np.exp(np.cumsum(shocks_vol))

    # 5. Estacional (Seasonal + trend)
    time_idx = np.arange(total)
    seasonal = 100.0 + 0.03 * time_idx + 8.0 * np.sin(2 * np.pi * time_idx / 30.0) + rng.normal(0, 1.0, total)

    return {
        "1. Tendencia Alcista": (up[:T], up[T:T+H]),
        "2. Tendencia Bajista": (down[:T], down[T:T+H]),
        "3. Lateral / Reversión": (lateral[:T], lateral[T:T+H]),
        "4. Alta Volatilidad": (high_vol[:T], high_vol[T:T+H]),
        "5. Estacional Cíclica": (seasonal[:T], seasonal[T:T+H]),
    }


def compute_mase(y_train: np.ndarray, y_test: np.ndarray, y_pred: np.ndarray) -> float:
    """Calcula el Mean Absolute Scaled Error (MASE)."""
    naive_diff = np.abs(np.diff(y_train))
    scale = np.mean(naive_diff)
    if scale < 1e-8:
        scale = 1e-8
    mae = np.mean(np.abs(y_test - y_pred))
    return float(mae / scale)


def compute_interval_coverage(y_test: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    """Calcula el porcentaje de valores reales que caen dentro del intervalo proyectado."""
    inside = (y_test >= lower) & (y_test <= upper)
    return float(np.mean(inside) * 100.0)


def run_latency_benchmark(real_tfm_engine=None):
    """Ejecuta benchmark de latencia para horizontes H=30, 60, 90 con 512 puntos de contexto."""
    print("\n" + "=" * 70)
    print(" 3. BENCHMARK DE LATENCIA Y THROUGHPUT (Contexto = 512 puntos)")
    print("=" * 70)
    horizons = [30, 60, 90]
    n_warmup = 3
    n_runs = 20

    rng = np.random.default_rng(2026)
    sim_points = [
        TimeSeriesPoint(timestamp=f"2023-01-{i:04d}", value=float(100.0 * np.exp(np.sum(rng.normal(0.0002, 0.015, i+1)))))
        for i in range(512)
    ]

    if real_tfm_engine is not None and getattr(real_tfm_engine, "_model", None) is not None:
        print(" [✓] Evaluando latencia de inferencia REAL de Google TimesFM 200M:")
        print(f" {'Horizonte (H)':<16} | {'Warm-up':<10} | {'Corridas':<10} | {'p50 (ms)':<12} | {'p95 (ms)':<12} | {'Throughput (pts/s)':<20}")
        print("-" * 90)

        for H in horizons:
            latencies = []
            for i in range(n_warmup + n_runs):
                t0 = time.perf_counter()
                _ = real_tfm_engine.forecast(sim_points, horizon=H, confidence=0.95)
                elapsed = time.perf_counter() - t0
                if i >= n_warmup:
                    latencies.append(elapsed)

            p50_ms = np.median(latencies) * 1000.0
            p95_ms = np.percentile(latencies, 95) * 1000.0
            throughput = H / np.median(latencies) if np.median(latencies) > 0 else 0
            print(f" H = {H:<12} | {n_warmup:<10} | {n_runs:<10} | {p50_ms:<12.2f} | {p95_ms:<12.2f} | {throughput:<20.1f}")
    else:
        print(" [-] TimesFM no evaluado en latencia: torch o pesos oficiales no disponibles.")
        print("     Evaluando latencia del motor estadístico local activo (Damped Holt MLE):")
        print(f" {'Horizonte (H)':<16} | {'Warm-up':<10} | {'Corridas':<10} | {'p50 (ms)':<12} | {'p95 (ms)':<12} | {'Throughput (pts/s)':<20}")
        print("-" * 90)

        damped_engine = DampedHoltForecastEngine()
        for H in horizons:
            latencies = []
            for i in range(n_warmup + n_runs):
                t0 = time.perf_counter()
                _ = damped_engine.forecast(sim_points, horizon=H, confidence=0.95)
                elapsed = time.perf_counter() - t0
                if i >= n_warmup:
                    latencies.append(elapsed)

            p50_ms = np.median(latencies) * 1000.0
            p95_ms = np.percentile(latencies, 95) * 1000.0
            throughput = H / np.median(latencies) if np.median(latencies) > 0 else 0
            print(f" H = {H:<12} | {n_warmup:<10} | {n_runs:<10} | {p50_ms:<12.2f} | {p95_ms:<12.2f} | {throughput:<20.1f}")


def run_precision_benchmark(real_tfm_engine=None):
    """Compara TimesFM real (si está disponible) vs Damped Holt MLE vs Random Walk Naive."""
    print("\n" + "=" * 70)
    print(" 4. BENCHMARK DE PRECISIÓN Y COBERTURA (H = 60 días)")
    print("=" * 70)

    series_dict = generate_benchmark_series()
    damped_engine = DampedHoltForecastEngine()
    timesfm_available = real_tfm_engine is not None and getattr(real_tfm_engine, "_model", None) is not None

    tfm_header = "TimesFM (Real 200M)" if timesfm_available else "TimesFM (Real)"
    print(f" {'Serie Evaluada':<24} | {'Métrica':<10} | {tfm_header:<30} | {'Damped Holt MLE':<16} | {'Naive Random Walk':<18}")
    print("-" * 108)

    for name, (y_train, y_test) in series_dict.items():
        H = len(y_test)
        pts = [TimeSeriesPoint(timestamp=f"2023-01-{i:04d}", value=float(v)) for i, v in enumerate(y_train)]

        # 1. Damped Holt MLE
        holt_res = damped_engine.forecast(pts, horizon=H, confidence=0.95)
        holt_pred = np.array(holt_res.values)
        holt_lower = np.array(holt_res.lower_bound)
        holt_upper = np.array(holt_res.upper_bound)
        mase_holt = compute_mase(y_train, y_test, holt_pred)
        cov_holt = compute_interval_coverage(y_test, holt_lower, holt_upper)

        # 2. Naive Random Walk: y_{T+h} = y_T, cono sigma_naive * sqrt(h)
        last_val = y_train[-1]
        rw_pred = np.full(H, last_val)
        daily_vol = np.std(np.diff(y_train))
        h_vec = np.arange(1, H + 1)
        rw_lower = last_val - 1.96 * daily_vol * np.sqrt(h_vec)
        rw_upper = last_val + 1.96 * daily_vol * np.sqrt(h_vec)
        mase_rw = compute_mase(y_train, y_test, rw_pred)
        cov_rw = compute_interval_coverage(y_test, rw_lower, rw_upper)

        # 3. TimesFM Real (Solo si está disponible; NUNCA simular datos falsos)
        if timesfm_available:
            try:
                tfm_res = real_tfm_engine.forecast(pts, horizon=H, confidence=0.95)
                tfm_pred = np.array(tfm_res.values)
                tfm_lower = np.array(tfm_res.lower_bound)
                tfm_upper = np.array(tfm_res.upper_bound)
                mase_tfm_str = f"{compute_mase(y_train, y_test, tfm_pred):.3f}"
                cov_tfm_str = f"{compute_interval_coverage(y_test, tfm_lower, tfm_upper):.1f}%"
            except Exception as e:
                mase_tfm_str = "Error de inferencia"
                cov_tfm_str = "Error de inferencia"
        else:
            mase_tfm_str = "No evaluado (sin pesos)"
            cov_tfm_str = "No evaluado (sin pesos)"

        print(f" {name:<24} | {'MASE':<10} | {mase_tfm_str:<30} | {mase_holt:<16.3f} | {mase_rw:<18.3f}")
        print(f" {'':<24} | {'Cob. 95%':<10} | {cov_tfm_str:<30} | {f'{cov_holt:.1f}%':<16} | {f'{cov_rw:.1f}%':<18}")
        print("-" * 108)

    if not timesfm_available:
        print("\n [!] AVISO DE INTEGRIDAD METODOLÓGICA:")
        print("     Google TimesFM no fue evaluado porque PyTorch o los pesos de 'google/timesfm-1.0-200m-pytorch'")
        print("     no están instalados o cargados en la caché local.")
        print("     TimeInvestor NO fabrica datos simulados para TimesFM.")
    print("\n Nota: MASE < 1.0 indica un desempeño superior al predictor ingenuo de un paso hacia adelante.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Diagnóstico, Descarga y Benchmarking de Google TimesFM para TimeInvestor"
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Omitir confirmaciones interactivas para descargar pesos HF"
    )
    parser.add_argument(
        "--device", type=str, choices=["cpu", "cuda", "mps"], default=None,
        help="Forzar dispositivo de cómputo (ej: 'cpu')"
    )
    parser.add_argument(
        "--allow-missing", action="store_true",
        help="Permitir ejecutar el diagnóstico y benchmark base si torch o los pesos no están instalados"
    )
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Omitir verificación y descarga de pesos de Hugging Face"
    )

    args = parser.parse_args()

    # 1. Dependencias
    check_dependencies(allow_missing=args.allow_missing)

    # 2. Diagnóstico del entorno
    device = report_environment(forced_device=args.device)

    # 3. Descarga / Cache
    if not args.skip_download:
        check_and_download_weights(auto_confirm=args.yes)

    # 4. Intentar cargar motor real de TimesFM
    real_engine = get_real_timesfm_engine()

    # 5. Benchmark de Latencia
    run_latency_benchmark(real_tfm_engine=real_engine)

    # 6. Benchmark de Precisión
    run_precision_benchmark(real_tfm_engine=real_engine)

    print("\n[✓] Ejecución de benchmark finalizada.")


if __name__ == "__main__":
    main()
