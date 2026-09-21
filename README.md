# TimeInvestor ⚡📈
### Plataforma Cuantitativa Local para Análisis, Proyección y Validación de Tesis de Inversión

[![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19+-61DAFB.svg)](https://react.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-v4-38B2AC.svg)](https://tailwindcss.com/)
[![PyTorch](https://img.shields.io/badge/PyTorch-TimesFM-EE4C2C.svg)](https://pytorch.org/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg)](https://www.sqlite.org/)

**TimeInvestor** es una estación de trabajo cuantitativa y modular que corre **100% en entorno local**. Permite a analistas, gestores de fondos e inversores independientes traducir hipótesis cualitativas en lenguaje natural (ej: *"Demanda eléctrica por centros de datos de IA"*) a carteras cuantitativas estructuradas, proyectar precios futuros mediante modelos de series temporales de última generación (**Google TimesFM**), someter el modelo a pruebas empíricas retrospectivas (**Reality Check Backtesting**), analizar matrices de correlación cruzada y auditar desviaciones frente a bandas de confianza en tiempo real.

---

## 🏛️ Diagrama de Arquitectura (Puertos y Adaptadores)

El sistema está desacoplado mediante una arquitectura de "cables" (interfaces abstractas y adaptadores) que permite intercambiar motores predictivos, proveedores de modelos de lenguaje o fuentes de datos sin alterar los contratos de la aplicación ni la experiencia de usuario:

```
                                  ┌─────────────────────────────────────────────────────────┐
                                  │               Frontend Web (React 19 / Vite)            │
                                  │  Tailwind CSS v4 • Lucide Icons • Chart.js Interactivo │
                                  └────────────────────────────┬────────────────────────────┘
                                                               │ HTTP REST / JSON
                                                               ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                 FastAPI Core Engine                                                    │
│                                                                                                                        │
│   ┌─────────────────────┐   ┌───────────────────────────┐   ┌───────────────────────────┐   ┌──────────────────────┐   │
│   │   Ingesta de Datos  │   │      Cable Semántico      │   │     Cable Predictivo      │   │    Persistencia      │   │
│   │ (MarketDataFetcher) │   │     (BaseLLMClient)       │   │   (BaseForecastEngine)    │   │ (SQLite/SQLAlchemy)  │   │
│   └──────────┬──────────┘   └─────────────┬─────────────┘   └─────────────┬─────────────┘   └──────────┬───────────┘   │
└──────────────┼────────────────────────────┼───────────────────────────────┼────────────────────────────┼───────────────┘
               │                            │                               │                            │
       ┌───────┴────────┐          ┌────────┴────────┐             ┌────────┴────────┐          ┌────────┴────────┐
       ▼                ▼          ▼                 ▼             ▼                 ▼          ▼                 ▼
    yfinance          FRED API   Gemini 2.5       OpenAI /       Google TimesFM     Fallback    Theses         Snapshots
 (Precios/Capex)    (Macro/PPA)    Flash        Ollama / Mock   (PyTorch 200M)    (Damped Holt) Notes          Audit Log
```

---

## 🌟 Principales Funcionalidades

### 1. 🔮 Proyección Temporal con Cono de Incertidumbre (Google TimesFM)
- Proyección continua hacia adelante con horizontes paramétricos $H \in [30, 60, 90, 180]$ días.
- Conos de incertidumbre sombreados con intervalos de confianza al **80%**, **90%** y **95%**.
- Normalización porcentual optativa (**Base 100**) para comparar activos con escalas de precios dispares.

### 2. 📊 Telemetría y Resumen Estadístico (Puro Dato Objetivo)
- **Tendencia Central**: Desviación porcentual esperada desde el último precio observado hasta el valor objetivo.
- **Amplitud del Intervalo**: Ancho porcentual del cono al 95% (medida directa de volatilidad e incertidumbre implícita del modelo).
- **Estado de la Inercia**: Diagnóstico matemático automático (aceleración positiva, negativa o lateralización según la convexidad de los retornos recientes).

### 3. 🤖 Copiloto e Intérprete de Tesis (Asistente LLM)
- Botón *"Interpretar Situación"* con llamado a `/api/interpret`.
- Desglose estructurado en tres perspectivas financieras:
  - **Qué dicen los datos**: Traducción conceptual intuitiva de las curvas.
  - **Alineación con la tesis**: Validación o refutación cuantitativa de la premisa original.
  - **Siguiente serie a explorar**: Detección de cuellos de botella macro con botón de navegación directa.

### 4. ⏪ Reality Check (Backtesting Retrospectivo)
- Simulación *walk-forward*: Corta la serie histórica en una fecha $T_{\text{cutoff}}$ pasada, alimenta el modelo con los datos pre-corte y proyecta hacia el futuro para contrastar la predicción contra la realidad ocurrida.
- Métricas calculadas:
  - **MAE (Mean Absolute Error)**: Desvío medio en dólares.
  - **MAPE (Mean Absolute Percentage Error)**: Error relativo medio.
  - **Directional Accuracy**: Porcentaje de aciertos en el sentido del movimiento (+ / -).

### 5. 🌐 Matriz de Correlaciones y Comparación Dual
- Alineación temporal estricta de calendarios bursátiles con series macroeconómicas de FRED.
- Mapa de calor interactivo con conmutador entre correlación lineal (**Pearson**) y monótona no paramétrica (**Spearman**).
- Gráfico de doble eje (**Dual-Axis**) para contrastar acciones y variables macro en escalas independientes.

### 6. 💾 Persistencia Relacional Local (SQLite)
- Almacenamiento local en `backend/database/time_investor.db`.
- **Mis Tesis**: Panel lateral para guardar tesis, registrar *snapshots* históricos de curvas proyectadas y agregar bitácoras de notas de análisis cualitativo.
- Sin dependencias de servicios externos ni migraciones manuales (`init_db` automático al arrancar).

### 7. 🚨 Alerta de Quiebre de Tesis y Exportación Ejecutiva
- Detección automática en caso de que el precio real perfore la banda inferior al 95%.
- Generación y descarga instantánea de informes ejecutivos en formato Markdown (`exportReport.ts`).

---

## 🛠️ Guía Paso a Paso de Instalación y Puesta en Marcha

### Prerrequisitos
- **Python 3.10** o superior.
- **Node.js 18+** y **npm** (solo necesario si deseas recompilar el frontend).
- **Git**.

### 1. Clonar el repositorio
```bash
git clone https://github.com/casper06/timeInvestor.git
cd timeInvestor
```

### 2. Crear y activar el entorno virtual de Python
En Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
```
En Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Instalar dependencias del Backend
```bash
pip install -r requirements.txt
```

### 4. Instalar dependencias y compilar el Frontend
```bash
cd frontend
npm install
npm run build
cd ..
```

### 5. Configurar variables de entorno
Copia el archivo de ejemplo y edita tus claves:
```bash
cp .env.example .env
```
*(En Windows PowerShell: `Copy-Item .env.example .env`)*

Configura las siguientes variables en `.env`:
- **`GEMINI_API_KEY`**: [Obtén tu clave gratuita en Google AI Studio](https://aistudio.google.com/app/apikey).
- **`FRED_API_KEY`**: [Obtén tu clave gratuita en St. Louis Fed FRED](https://fred.stlouisfed.org/docs/api/api_key.html).
- *(Opcional)* Si no agregas ninguna clave, el sistema conmuta automáticamente a los adaptadores **Mock** de alta fidelidad para operar 100% offline.

### 6. Iniciar la aplicación (Comando Único)
```bash
python run.py
```
El script inicializa automáticamente la base de datos SQLite y levanta el servidor:
- 💻 **Dashboard Web**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- 📖 **Documentación Swagger API**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## ⚙️ Configuración del Motor TimesFM: Real PyTorch vs. Fallback Estadístico

TimeInvestor incluye dos modos de proyección en `backend/services/forecast_engine.py`:

| Parámetro en `.env` | Modo | Descripción |
|---|---|---|
| `USE_REAL_TIMESFM=false` *(default)* | **Fallback Estadístico Calibrado** | Suavizado exponencial amortiguado (Holt Linear Trend) con deriva estocástica y conos de incertidumbre. **Arranque instantáneo y cero uso de GPU**. |
| `USE_REAL_TIMESFM=true` | **Google TimesFM PyTorch Real** | Carga el modelo fundacional preentrenado `google/timesfm-1.0-200m-pytorch` desde Hugging Face. Detecta automáticamente aceleración por hardware GPU (**CUDA**), Apple Silicon (**MPS**) o CPU. |

Para habilitar TimesFM real con PyTorch:
```bash
pip install torch transformers
```
Y en tu archivo `.env`:
```env
FORECAST_ENGINE=timesfm
USE_REAL_TIMESFM=true
```

---

## 🧪 Pruebas Automatizadas

La plataforma cuenta con una suite completa de pruebas unitarias y de integración que verifican la estabilidad de los contratos JSON, los cálculos cuantitativos y la persistencia relacional:

```bash
python -m pytest tests/ -v
```

Cobertura de pruebas:
- `test_api_endpoints.py`: Verificación de endpoints REST (`/health`, `/forecast`, `/fundamentals`, `/interpret`).
- `test_backtest_engine.py`: Validación de algoritmos MAE, MAPE y Directional Accuracy.
- `test_correlation_engine.py`: Verificación de matrices de Pearson y Spearman con alineación temporal.
- `test_database.py`: Ciclo de vida CRUD de tesis, snapshots y notas de investigación en SQLite.
- `test_forecast_engine.py`: Conos de confianza, mapeo de frecuencias y contrato compatible con TimesFM.
- `test_llm_router.py`: Desestructuración semántica de tesis cualitativas e interpretación del copiloto.

---

## 📜 Licencia de Software

Este proyecto está bajo la licencia **GNU General Public License v2.0 (GPL-2.0)**. Consulta el archivo [LICENSE](LICENSE) para obtener los términos completos y condiciones de distribución, modificación y uso.
