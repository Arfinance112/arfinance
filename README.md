# ARFinance · Gestión PyME AR – versión web

Plataforma web multi-cliente de control de gestión financiera para PyMEs argentinas. Lleva a la web la
Planilla de Gestión Integral v2 (28 pestañas): ingesta de extractos de bancos y billeteras, conciliación,
tesorería multi-moneda, P&L de gestión, prime cost, presupuesto con AxI y tableros.

- Arquitectura, modelo de datos, algoritmo de ingesta y roadmap: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md)
- Conectar Supabase: [docs/SUPABASE.md](docs/SUPABASE.md) · Publicar (Netlify + Fly.io): [docs/PUBLICAR.md](docs/PUBLICAR.md)
- Esquema de base de datos: [db/migraciones/](db/migraciones/)

## Estructura

```
backend/   API FastAPI + motor de ingesta (app/ingesta) + motor financiero (app/finanzas)
           + persistencia PostgreSQL (app/db) + autenticación Supabase (app/api/auth.py) + tests
frontend/  React + TypeScript con el tema visual de arfinance-mza.netlify.app (src/styles/tema.css)
           preview/: vista estática de la conciliación para revisar la estética sin Node
db/        migraciones/ (SQL numerado) y seeds/ exportados de la planilla
tools/     exportar_seeds.py (regenera db/seeds desde el .xlsx) · pg_local.py (PostgreSQL embebido para desarrollo)
```

## Backend

```bash
cd backend
pip install -r requirements.txt
pytest                                   # 121 tests (los de PostgreSQL se saltean si no hay TEST_DATABASE_URL)
uvicorn app.api.main:app --reload        # http://localhost:8000/docs
```

Variables de entorno (copiá `.env.example` a `.env`):

| Variable | Para qué | Sin definir |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL / Supabase (cadena de conexión del proyecto) | Repositorio en memoria (los datos se pierden al reiniciar) |
| `SUPABASE_URL` | Proyecto de Supabase: valida las sesiones con sus claves de firma (JWKS, ES256/RS256) y, con la service key, guarda archivos | Sin esta ni `SUPABASE_JWT_SECRET`: modo desarrollo con un usuario fijo, nunca en producción |
| `SUPABASE_JWT_SECRET` | Solo proyectos que firman sesiones con secreto HS256 (legacy) | — |
| `CORS_ORIGENES` | Orígenes permitidos para el frontend, separados por coma | `http://localhost:5173` |
| `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` | Guarda los archivos originales en Supabase Storage (bucket privado `SUPABASE_BUCKET`, por defecto `documentos`). La service key es solo del backend | Disco local en `STORAGE_DIR` (por defecto `backend/.storage`) |
| `TAMANO_MAXIMO_MB` | Límite por archivo subido (se corta la lectura apenas se pasa) | 20 |
| `UMBRAL_ASINCRONO_KB` | Archivos más grandes van a la cola de trabajos (respuesta 202 y se consulta `GET /trabajos/{id}`) | 2048 |
| `WORKER_EMBEBIDO` | `1` = el worker corre como hilo dentro de la API | `1` en modo memoria, `0` con `DATABASE_URL` (correr `python -m app.worker` aparte) |
| `CLAMAV_HOST` / `CLAMAV_PORT` | Antivirus clamd para escanear cada archivo subido | Sin antivirus (los controles de formato se aplican igual) |
| `CLAMAV_OBLIGATORIO` | `1` = si el antivirus no responde, la subida se rechaza (503) | Si no responde, se acepta |
| `METRICAS_TOKEN` | Exige `Authorization: Bearer <token>` en `/metricas` | `/metricas` abierto |
| `RESPALDOS_A_CONSERVAR` | Cuántos respaldos quedan en la carpeta | 14 |
| `PG_BIN` | Carpeta de `pg_dump`/`pg_restore` | PATH, o el PostgreSQL de `.pgenv` |
| `ENTORNO` | `produccion` = la API no arranca si falta el secreto JWT, `METRICAS_TOKEN` o `DATABASE_URL`, o si CORS tiene `*`; oculta `/docs` y agrega HSTS | Solo avisa en el log |
| `ADMINS_PLATAFORMA` | Emails o ids (separados por coma) que pueden cargar índices y tipos de cambio, comunes a todos los estudios | Nadie (en modo desarrollo, el usuario fijo) |
| `TESSERACT_CMD` / `OCR_IDIOMA` | Motor de OCR para PDF escaneados | `tesseract` del PATH o `C:\Program Files\Tesseract-OCR`; idioma `spa`. Sin motor, los escaneados se rechazan con explicación |

Frontend (`frontend/.env.local`, ver `frontend/.env.example`): `VITE_API_URL`, `VITE_SUPABASE_URL` y `VITE_SUPABASE_ANON_KEY`.
Sin las variables de Supabase el frontend corre sin login, en modo desarrollo.

### Base de datos

```bash
cd backend
python -m app.db.migrar            # aplica migraciones pendientes y carga los maestros globales
python -m app.db.migrar --recrear  # SOLO desarrollo: borra y recrea la base de DATABASE_URL
```

En Supabase: guía paso a paso en [docs/SUPABASE.md](docs/SUPABASE.md); al final, `python -m app.db.verificar_supabase`
chequea claves, conexión, migraciones, RLS en todas las tablas, bucket privado y Storage.

### Operación (fase 4a)

```bash
python -m app.worker                                   # worker de la cola (uno o varios; toman con SKIP LOCKED)
python -m app.db.respaldo verificar                    # respalda, restaura en una copia, compara conteos y la borra
python -m app.db.respaldo restaurar --archivo respaldos/gestion_AAAAMMDD_HHMMSS.dump --url postgresql://.../gestion_nueva
```

- `GET /salud`: base, almacenamiento y cola; 200 o 503. Es el chequeo del balanceador y del monitoreo externo.
- `GET /metricas`: formato Prometheus (pedidos por ruta y estado, duración, trabajos por estado, rechazos).
- Logs: una línea JSON por evento en stdout, con `request_id` (también en el header `X-Request-Id` de cada
  respuesta, para rastrear lo que reporta un usuario). No se loguean contenidos de archivos.
- Programar `respaldo verificar` una vez por día (Programador de tareas o cron) y alertar si sale con código 1.
  En Supabase, además, los respaldos diarios del plan; este script es el que prueba que se pueden restaurar.
- Subidas: se controla nombre, que el contenido coincida con la extensión, bombas ZIP en .xlsx y PDF con
  acciones automáticas; con `CLAMAV_HOST`, además, antivirus.

### Alta de clientes, OCR y seguridad (fase 4b)

- **Nuevo cliente** (`#/alta`): desde la Planilla de Gestión Integral v2 (vista previa de lo que se trae antes de
  crear nada; las filas "EJEMPLO" de la plantilla se omiten) o desde cero (datos, cuentas habituales, próximos pasos).
  La planilla tiene que estar guardada desde Excel: se usan los importes que calcularon sus fórmulas.
- **OCR**: un PDF sin texto (escaneo o foto) va a la cola y el worker lo lee con Tesseract. Instalación:
  - Windows: `winget install -e --id UB-Mannheim.TesseractOCR --source winget`. Trae solo inglés: el español
    (`spa.traineddata` de github.com/tesseract-ocr/tessdata_fast) va en `backend/.tessdata/` junto con copias de
    `eng` y `osd`, sin permisos de administrador (o en otra carpeta indicada con `OCR_DATOS`).
  - Linux: `apt install tesseract-ocr tesseract-ocr-spa`.

  Cada página se lee con 3 variantes de limpieza (polvo, grises, resolución) y se queda la lectura cuyos importes
  cierran con el saldo; el signo menos que el OCR suele perder se reconstruye con la diferencia de saldos.
  Medido: 97 % de renglones exactos en 18 escaneos con ruido y giro, unos 2 segundos por página.
  Lo leído por OCR queda "con alertas": revisar fechas e importes antes de aprobar.
- **Seguridad**: el backend se conecta a la base con un usuario que no pasa por RLS, así que el aislamiento entre
  estudios lo garantiza la API (cada ruta verifica que el usuario vea ese cliente). RLS queda como segunda barrera
  para accesos directos con la clave anónima. Límite de pedidos por usuario: configurarlo en el proxy o balanceador.

### PostgreSQL local sin instalar nada (desarrollo)

`pgserver` trae PostgreSQL embebido, pero requiere Python 3.12 o 3.13:

```bash
py -V:3.12 -m venv .pgenv
.pgenv\Scripts\pip install pgserver
.pgenv\Scripts\python tools\pg_local.py     # imprime la URL, por ejemplo postgresql://postgres:@127.0.0.1:50590/postgres
```

Para los tests de PostgreSQL, apuntá `TEST_DATABASE_URL` a una base de prueba en ese servidor (se recrea en cada corrida).

### Datos de demostración

Con la API corriendo en modo desarrollo: `python tools/demo_datos.py` crea un cliente con un extracto
aprobado, comprobantes emitidos y recibidos, F.931 e índices de octubre, e imprime su id.

### Cómo se arma el resultado (fase 2a)

Ventas = Mis Comprobantes emitidos. Compras = recibidos con rubro (el rubro se asigna una vez por proveedor).
Personal = F.931. Gastos sin factura (comisiones, impuestos bancarios) = Tesorería. Si en un mes un rubro ya
tiene facturas, lo pagado por Tesorería con ese rubro no se vuelve a sumar. Costo de mercadería (CV01) y
mermas (CV10) = detalle de ventas por ítem × costo estándar al tipo de cambio del mes. Las compras de
mercadería a stock (INV01) no son resultado: el costo entra cuando se vende o se pierde.

## Primer uso de la API

1. `POST /me/organizacion` con el nombre del estudio: crea la organización y te deja como admin.
2. `POST /clientes` → `POST /clientes/{id}/cuentas` → `POST /clientes/{id}/documentos` (el extracto).
3. `GET /lotes/{id}`: revisión; `POST /clientes/{id}/reglas` y `PATCH /lotes/{id}/movimientos/{n}` para corregir.
4. `POST /lotes/{id}/aprobar`: pasa a Tesorería y devuelve la conciliación.

## Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
npm run build   # chequeo de tipos estricto + build de producción en dist/
```

Requiere Node 18 o superior (probado con Node 26). npm 11+ avisa que bloqueó el script de instalación
de esbuild: no hace falta aprobarlo, el binario de la plataforma se instala igual y el build funciona.

Pantallas: clientes (`#/clientes`), y por cliente documentos con carga drag-and-drop, cuentas, tesorería,
flujo de caja y conciliación de cada extracto.

Para ver la estética sin Node: `python -m http.server 5180 --directory frontend` y abrir
http://localhost:5180/preview/documentos.html, `tesoreria.html` o `conciliacion.html`.
