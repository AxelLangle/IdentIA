# IdentIA — Sistema de Asistencia y Control Biométrico

**IdentIA** es una aplicación web full-stack para control de asistencia mediante reconocimiento facial, diseñada con un **modelo unificado** que soporta tanto instituciones educativas (pase de lista por clase/grupo) como empresas (check-in y check-out de jornada laboral).

Surgió como una reconstrucción completa desde cero del proyecto académico anterior, reemplazando Haar Cascades + OpenCV en servidor por un pipeline moderno basado en **WebRTC en el navegador + FastAPI + OpenCV YuNet (detección) + SFace ONNX (embeddings vectoriales)** ejecutándose en CPU con latencia de milisegundos.

---

## Arquitectura Rápida

- **Backend (`backend/`):** Python + FastAPI + SQLAlchemy 2.0 (SQLite en desarrollo, listo para PostgreSQL) + OpenCV ONNX (`FaceDetectorYN` + `FaceRecognizerSF`).
- **Frontend (`frontend/`):** React + Vite + TypeScript + Tailwind CSS + WebRTC (`getUserMedia`).
- **Motor Biométrico:**
  1. Decodificación de frame en memoria RAM (sin guardar fotografías crudas en disco).
  2. Detección multi-rostro con **YuNet (`face_detection_yunet_2023mar.onnx`)** con fallback LAB/CLAHE en contraluz.
  3. Validación de calidad (tamaño mínimo, nitidez, iluminación, sombra lateral, contraluz y validación geométrica de 6 poses: `frontal`, `left`, `right`, `up`, `down`, `smile`).
  4. Alineación facial, normalización selectiva de iluminación extrema LAB y extracción de embedding L2-normalizado de 128 dimensiones con **SFace (`sface_2021dec_v2`)**.
  5. Búsqueda 1:N por similitud coseno con umbral calibrado (`0.42`) y verificación de margen contra el segundo candidato (`0.05`).

> Consulta también el [Manual de Uso y Operación](docs/USER_MANUAL.md) y la [Arquitectura Técnica](docs/ARCHITECTURE.md).

---

## Privacidad y Seguridad Biométrica

De acuerdo con mejores prácticas de seguridad de la información (ISO/IEC 24745 y LFPDPPP):

- **No se almacenan las fotos crudas de enrolamiento.** Cada imagen enviada se procesa únicamente en memoria RAM y se descarta al instante tras extraer su vector matemático de 512 bytes.
- **Consentimiento explícito obligatorio:** No es posible registrar datos biométricos sin aceptar `consentimiento_biometrico`.
- **Avatar opcional desacoplado:** Solo se conserva opcionalmente 1 miniatura comprimida (`200x200` JPEG) para identificación visual en pantalla.
- **Derecho de revocación:** Desde la interfaz o vía `POST /api/persons/biometrics/revoke` se borran todos los embeddings y el avatar al instante con trazabilidad en bitácora.
- **Trazabilidad de modelo:** Cada vector almacena `nombre_modelo` y `version_modelo` para detectar automáticamente re-enrolamientos necesarios ante futuras actualizaciones del modelo.

---

## Requisitos Previos

- **Python 3.11+** (probado en Python 3.13.7 sin compilación C++ ni `dlib`).
- **Node.js 20+** y **npm**.
- Navegador moderno con soporte WebRTC (`localhost` permite acceso a cámara sin HTTPS adicional).

---

## Cómo Ejecutar Localmente

### 1. Backend (FastAPI + Motor Biométrico)

**En Git Bash (terminal principal):**
```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.vision.models_loader
uvicorn app.main:app --reload --port 8000
```

**En PowerShell:**
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
python -m app.vision.models_loader
uvicorn app.main:app --reload --port 8000
```

> Al arrancar `models_loader` (o automáticamente al iniciar la API), se descargan en `backend/models/` los modelos oficiales ONNX de OpenCV Zoo (`face_detection_yunet_2023mar.onnx` y `face_recognition_sface_2021dec.onnx`).

#### Credenciales Demo Iniciales (entorno local)

- **Superadmin Global:** `admin@identia.local` / `IdentIA2026!`
- **Admin Organización Demo:** `empresa@identia.local` / `Empresa2026!`

### 2. Frontend (React + Vite)

En otra terminal, desde la raíz del proyecto:

**En Git Bash (terminal principal):**
```bash
cd frontend
npm install
npm run dev
```

**En PowerShell:**
```powershell
cd frontend
npm install
npm run dev
```

Abre en tu navegador: `http://localhost:5173`.

---

## Pruebas Automatizadas

**En Git Bash (terminal principal):**
```bash
cd backend
source .venv/Scripts/activate
pytest -v
```

**En PowerShell:**
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -v
```

Para validar compilación y tipos del frontend:

**En Git Bash / PowerShell:**
```bash
cd frontend
npm run build
```

---

## Ejecutables Offline de Escritorio (Release 1.1.0)

Desde la versión **1.1.0**, todo el código fuente (`backend/` y `frontend/`) utiliza identificadores descriptivos en español y documentación interna extensa (conservando sin cambios los nombres físicos de tablas/columnas SQLite y migraciones Alembic). Además, se distribuyen paquetes autónomos para Windows que embeben el servidor FastAPI, la interfaz web React compilada (`frontend_dist/`) y los modelos YuNet + SFace ONNX (`models/`), permitiendo operar 100% offline:

- **`release/IdentIA-1.1.0.exe` (~89.55 MB):** Ejecutable único (`--onefile`), listo para copiar y ejecutar directamente.
- **`release/IdentIA-1.1.0-portable.zip` (~89.64 MB):** Paquete portable (`--onedir`) de arranque instantáneo; basta descomprimir y ejecutar `IdentIA-1.1.0.exe`.

### Ejecutar el binario compilado

Al iniciar el ejecutable se crea la carpeta `datos_identia/` junto al binario para persistir la base de datos SQLite y se abre automáticamente el navegador web.

**En Git Bash (terminal principal):**
```bash
./release/IdentIA-1.1.0.exe
# Opciones disponibles: ./release/IdentIA-1.1.0.exe --puerto 8000 --sin-navegador
```

**En PowerShell:**
```powershell
.\release\IdentIA-1.1.0.exe
# Opciones disponibles: .\release\IdentIA-1.1.0.exe --puerto 8000 --sin-navegador
```

### Recompilar los ejecutables desde código fuente

**En Git Bash (terminal principal):**
```bash
powershell.exe -ExecutionPolicy Bypass -File scripts/compilar_release_1_1_0.ps1
```

**En PowerShell:**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\compilar_release_1_1_0.ps1
```

---

## Hoja de Ruta

- **Fase 0–1 (Completa):** Arquitectura unificada, repositorio limpio y motor biométrico ONNX YuNet + SFace con control de calidad.
- **Fase 2 (Completa):** MVP Individual (Kiosco check-in/check-out empresarial + pase de lista individual escolar, grupos, sesiones y exportación CSV).
- **Bloque A (Completa):** Compensación de contraluz/sombras LAB, bloqueo de contraluz en registro, asistente guiado de 6 poses con validación geométrica y manual de uso.
- **Bloque B (Completa):** Autenticación JWT, aislamiento multi-organización (`superadmin`, `org_admin`, `teacher`, `operator`), revocación individual/lote con contraseñas delegadas hasheadas (`scrypt`), bitácora de auditoría y migraciones Alembic.
- **Bloque C (Completa):** Modelo educativo completo (`Carrera`, `Grupo` académico con periodo/aula fija, `Materia`, `AsignacionCurso`, `HorarioClase`), periodos configurables, herencia automática de materias, portal docente con aislamiento estricto ("Tu clase ahora" en 1 clic), estadísticas por asignatura/grupo y migraciones `0002`/`0003`.
- **Bloque D (Completa):** Turnos empresariales (`TurnoLaboral` diurno y nocturno con cruce de medianoche), asignación individual/lote y herencia por departamento, reglas de puntualidad/salida anticipada/inasistencias, estadísticas por turno/empleado y migración `0004_enterprise_work_shifts`.
- **Release 1.1.0 (Actual en `feat/release-1.1.0`):** Refactorización integral del proyecto a variables descriptivas y comentarios detallados en español (conservando el esquema físico SQLite), lanzador autónomo (`backend/lanzador_escritorio.py`) y generación de ejecutables Windows offline (`release/IdentIA-1.1.0.exe` y `release/IdentIA-1.1.0-portable.zip`).
- **Fase 3 (Siguiente desde `develop`):** Modo Grupal de Alta Velocidad (captura panorámica / foto HD de aula o cuadrilla con detección simultánea multi-rostro y validación rápida de casos dudosos).

---

## Flujo de Ramas Git

- `main`: Rama estable.
- `staging`: Preproducción.
- `develop`: Integración principal; cada nueva funcionalidad parte en una rama `feat/*` desde `develop`.
