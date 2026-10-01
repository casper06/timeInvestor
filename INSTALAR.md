# Instalar TimeInvestor (Windows, sin saber programar)

Tiempo total: unos **20 minutos**, casi todo descargas (en la prueba, instalar las librerías tardó 78 s y la primera compilación 33 s). No hace falta pagar nada.

> Los comandos se escriben en el **Símbolo del sistema** (buscalo en el menú
> Inicio: escribí `cmd` y Enter). Cada línea de las cajas grises se copia, se
> pega y se aprieta Enter.

---

## 1. Instalá tres programas

| Programa | De dónde | Ojo con |
|---|---|---|
| **Python 3.12** | <https://www.python.org/downloads/release/python-31210/> (bajá el "Windows installer (64-bit)") | En la primera pantalla del instalador, tildá **"Add python.exe to PATH"** |
| **Node.js** (versión LTS) | <https://nodejs.org/en/download> | Tiene que ser la 20.19 o más nueva (la LTS actual lo es). Es necesario: sin Node la app no tiene pantalla |
| **Git** (opcional) | <https://git-scm.com/downloads/win> | Solo si preferís clonar en vez de bajar el ZIP del paso 2 |

Después de instalar, **cerrá y volvé a abrir** el Símbolo del sistema. Para
comprobar que quedaron bien:

```
py -3.12 --version
node --version
```

Tienen que mostrar `Python 3.12.x` y `v22...` (o `v20.19` o más). Si dice "no se
reconoce", repetí la instalación y revisá lo del PATH.

## 2. Bajá el programa

Bajá <https://github.com/casper06/timeInvestor/archive/refs/heads/main.zip>,
y extraelo en una carpeta **con ruta corta**, por ejemplo `C:\TimeInvestor`
(Windows se traba con rutas muy largas). Tiene que quedar así:
`C:\TimeInvestor\timeInvestor-main\run.py`.

Entrá a esa carpeta desde el Símbolo del sistema:

```
cd C:\TimeInvestor\timeInvestor-main
```

## 3. Sacá las dos claves (gratis)

Una clave es un código que te da un servicio para que lo uses a tu nombre.
Cada una se saca en un minuto. **No las compartas ni las subas a ningún lado.**

**FRED** (los datos económicos: desempleo, inflación, producción)

1. Entrá a <https://fred.stlouisfed.org/docs/api/api_key.html> y seguí el link
   para crear una cuenta gratuita (la cuenta es de la Reserva Federal de St.
   Louis).
2. En tu cuenta, **API Keys → Request API Key**, poné un motivo cualquiera
   ("uso personal") y aceptá.
3. Copiá la clave: son **32 letras minúsculas y números**.

**Gemini** (traduce tu tesis a series y escenarios)

1. Entrá a <https://aistudio.google.com/apikey> con tu cuenta de Google.
2. **Create API key** y copiala (empieza con `AIza`).
3. **Dos avisos del plan gratuito**:
   - **Google puede usar lo que escribas para mejorar sus productos.** No pongas
     en una tesis nada que no quieras compartir con Google.
   - El cupo es chico: **20 pedidos por día y por modelo**, y una tesis puede
     gastar hasta 3. Alcanza para unas pocas tesis por día; se renueva solo.

Sin la clave de FRED no hay series macro. Sin la de Gemini no se traduce la
tesis (las series de acciones y ETFs funcionan igual, sin ninguna clave).

## 4. Poné las claves en el archivo `.env`

Es un archivo de texto donde el programa lee sus claves. Se arma copiando el
modelo que viene incluido:

```
copy .env.example .env
notepad .env
```

Se abre el Bloc de notas. Buscá estas dos líneas y pegá cada clave **justo
después del `=`**, sin espacios ni comillas:

```
GEMINI_API_KEY=AIzaSy...tu-clave
FRED_API_KEY=0123456789abcdef0123456789abcdef
```

Guardá (Ctrl+S) y cerrá. **No toques nada más del archivo.**

## 5. Preparalo (una sola vez, ~2 minutos)

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
```

El primero crea un espacio aislado para el programa (tarda unos segundos). El
segundo descarga las librerías: **verás muchas líneas pasar durante uno o dos
minutos**; es normal. Termina con una línea `Successfully installed ...` y,
después, un aviso de "new release of pip": ignoralo.

## 6. Arrancá

```
.venv\Scripts\python.exe run.py
```

**La primera vez tarda más**, porque compila la pantalla: vas a ver
`Compilando frontend por primera vez...`, `Instalando dependencias de Node...` y
muchas líneas más. Son **entre 20 segundos y un par de minutos**, según tu
conexión. Cuando termina aparece un recuadro con
`Accede en tu navegador: http://127.0.0.1:8000` y **se abre solo el
navegador** con la aplicación. Si no se abre, copiá esa dirección en el
navegador.

- **No cierres la ventana negra** mientras uses la app: es el programa
  funcionando.
- Para apagarlo: en esa ventana, **Ctrl+C**.
- **Las próximas veces** solo hacen falta `cd C:\TimeInvestor\timeInvestor-main`
  y la línea del paso 6: arranca en segundos.

La app abre en `http://127.0.0.1:8000`, que solo se ve desde tu computadora.

## Si algo no anda

| Qué ves | Qué pasa | Qué hacer |
|---|---|---|
| `Advertencia al compilar frontend` y en el navegador una portada que dice "TimeInvestor API" en vez de la app | Falta Node.js o es muy viejo | Instalá Node (paso 1), cerrá y abrí el Símbolo del sistema y repetí el paso 6 |
| `py` o `python` "no se reconoce" | Python no quedó en el PATH | Reinstalá Python tildando **Add python.exe to PATH** |
| `The filename or extension is too long` al instalar | La carpeta está en una ruta muy larga | Movela a `C:\TimeInvestor` |
| La app abre pero las series macro dan error | La clave de FRED está mal pegada | Revisá el `.env`: 32 caracteres, sin espacios ni comillas. Después apagá (Ctrl+C) y volvé a arrancar |
| La tesis no se traduce y dice que no hay cupo | Gastaste los 20 pedidos de hoy de Gemini | Esperá a mañana |
| `Only one usage of each socket address` | Ya hay una copia corriendo | Cerrá la otra ventana negra, o arrancá con `... run.py --port 8001` |

## Mac o Linux

Es lo mismo, con otros comandos: `python3.12 -m venv .venv`,
`.venv/bin/python -m pip install -r requirements.lock`, `cp .env.example .env`,
`.venv/bin/python run.py`. Node y las claves, igual.
