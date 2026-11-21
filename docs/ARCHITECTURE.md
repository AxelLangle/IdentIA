# Arquitectura de IdentIA

## 1. Visión General

**IdentIA** separa claramente la captura de video en el cliente (navegador vía WebRTC) del procesamiento biométrico y persistencia en el servidor (FastAPI + OpenCV ONNX + SQLAlchemy). Esto corrige la limitación crítica de la versión heredada, donde el servidor abría la cámara física local mediante `cv2.VideoCapture(0)` y bloqueaba la aplicación con hilos sin sincronización.

```text
[Navegador Web / Kiosco / Tablet]
   └─ WebRTC getUserMedia() -> Canvas JPEG (en memoria)
        │
        ▼ HTTP multipart/form-data (POST /api/.../enroll-frame | recognize-frame)
[Backend FastAPI]
   ├─ Decode en RAM (np.frombuffer + cv2.imdecode) -> descarte inmediato al finalizar
   ├─ BiometricEngine (Thread-safe con Lock)
   │    ├─ YuNet ONNX (face_detection_yunet_2023mar.onnx) -> cajas + 5 landmarks (con fallback LAB/CLAHE en contraluz)
   │    ├─ Quality Gate (tamaño min, nitidez, brillo, contraluz, sombra lateral y validación geométrica de 6 poses)
   │    └─ SFace ONNX (face_recognition_sface_2021dec.onnx) -> alignCrop + normalización selectiva de extremos LAB + embedding L2 (`sface_2021dec_v2`)
   ├─ Matching 1:N por similitud coseno + margen de ambigüedad
   └─ Persistencia SQLAlchemy (SQLite WAL -> compatible con PostgreSQL)
```

---

## 2. Decisión de Privacidad Biométrica y Seguridad de la Información

Al diseñar el manejo de los 3–5 registros iniciales por persona se evaluó si conservar las imágenes originales o únicamente los vectores matemáticos (*embeddings*). Se adoptó la política de **no persistir imágenes crudas de enrolamiento** con base en estándares de seguridad biométrica (**ISO/IEC 24745**) y protección de datos sensibles (**LFPDPPP**):

1. **Procesamiento volátil en RAM:** Cada frame recibido en `/api/persons/{id}/enroll-frame` se decodifica directamente desde el buffer HTTP en memoria, se valida su calidad, se alinea y se transforma en un vector `float32` normalizado L2 de 128 dimensiones (**512 bytes**). El buffer de imagen nunca se escribe en disco y se libera al terminar la petición.
2. **Minimización de riesgo:** En caso de acceso no autorizado a la base de datos o respaldos, no existe un repositorio masivo de fotografías faciales crudas reutilizables o filtrables.
3. **Trazabilidad de versión del modelo:** La tabla `face_embeddings` registra `model_name` (`"sface"`) y `model_version` (`"sface_2021dec_v2"`). Si en el futuro se actualiza el modelo o el preprocesamiento, el backend identifica automáticamente qué perfiles tienen `needs_reenroll = true` y solo considera vectores del modelo vigente durante el matching.
4. **Avatar opcional desacoplado:** Para mejorar la usabilidad en listas y kioscos, la organización puede habilitar `store_avatar_by_default` (opcional por persona en la pose `"frontal"`), guardando únicamente una miniatura comprimida de `200x200` px en JPEG. Puede desactivarse por completo en entornos de alta privacidad.
5. **Consentimiento y derecho de revocación:** El campo `biometric_consent` es obligatorio antes de enrolar cualquier frame, y `DELETE /api/persons/{id}/biometrics` (así como `ON DELETE CASCADE` con `PRAGMA foreign_keys=ON`) permite borrar de inmediato toda huella matemática y avatar del usuario.

---

## 3. Modelo de Datos Unificado (Escuelas y Empresas)

El mismo motor soporta ambos casos de uso mediante configuración organizacional:

| Entidad | Rol en Empresas | Rol en Instituciones Educativas |
|---|---|---|
| `Organization` | Empresa (`mode = "enterprise"`), define tolerancia de retardo y cooldown anti-duplicado | Escuela/Facultad (`mode = "education"`), define tolerancia y `academic_period_type` (`bimestral`, `trimestral`, `cuatrimestral`, `semestral`, `ciclo`) |
| `Career` | N/A | Carrera o programa académico; puede sobrescribir el tipo de periodo (`period_type`) |
| `Group` | Departamento, área o turno con horario (`schedule_start`, `schedule_end`) | Grupo académico vinculado a carrera (`career_id`), periodo (`semester`) y aula fija (`default_classroom`) |
| `Subject` / `CourseAssignment` | N/A | Catálogo de asignaturas vinculadas a grupo y profesor (`CourseAssignment`) con herencia automática para alumnos |
| `ClassSchedule` | N/A | Bloques de horario semanal por asignatura/grupo (`day_of_week`, `start_time`, `end_time`, `classroom`) |
| `Person` | Empleado (`external_id` = núm. de empleado) | Alumno o docente (`external_id` = matrícula) |
| `FaceEmbedding` | 6 vectores validados por pose (`frontal`, `left`, `right`, `up`, `down`, `smile`) | Mismo esquema de 6 poses |
| `AttendanceSession` | Jornada diaria (`session_type = "workday"`) | Sesión de clase ligada a `course_assignment_id` y `schedule_id` (`session_type = "class"`) |
| `AttendanceEvent` | Eventos `check_in` y `check_out` con cálculo de puntualidad y horas trabajadas | Evento `present` único por sesión (`on_time` o `late`) |
| `User` | Cuentas de acceso (`superadmin`, `org_admin`, `operator`) | Cuentas de acceso (`superadmin`, `org_admin`, `teacher`, `operator`) |
| `DelegatedCredential` | Claves delegadas hasheadas (`scrypt`) para operaciones sensibles | Misma delegación con trazabilidad de creador y asignado |
| `AuditLog` | Bitácora inmutable de altas, credenciales y revocaciones | Misma bitácora aislada por organización |

---

## 3.2. Modelo Educativo Completo y Aislamiento Docente (Bloque C)

- **Jerarquía académica (`0002_education_domain` + `0003_academic_periods_and_classrooms`):** `Organization` (`mode = "education"`, con `academic_period_type`) → `Career` (con `period_type` opcional) → `Group` (con `semester` y `default_classroom` para prellenar horarios por aula) → `Person` (alumnos) + `Subject` / `CourseAssignment` (asignatura + profesor) → `ClassSchedule` (bloques multi-día con aula editable) → `AttendanceSession`.
- **Herencia automática por grupo:** al asignar asignaturas a un grupo (`CourseAssignment`), todos los alumnos inscritos en ese grupo heredan automáticamente esas materias y son elegibles en su galería biométrica sin asignaciones individuales manuales (`/api/academic/students/{person_id}/courses`).
- **Aislamiento estricto por profesor:** un usuario con rol `teacher` únicamente visualiza y opera sesiones, alumnos y eventos de sus propios `CourseAssignment` (`403 Forbidden` en sesiones o estadísticas globales de otros docentes). Desde **Mi Agenda Docente**, abre su clase actual o próxima en 1 clic hacia el kiosco.
- **Generación idempotente de sesiones y estadísticas:** `/api/academic/sessions/generate` crea sesiones por horario del día sin duplicarlas, y `/api/academic/stats` consolida porcentajes de asistencia, retardos y faltas **por asignatura** y **por grupo/alumno** para `org_admin` y `superadmin`.

---

## 3.1. Seguridad Multi-Tenant RBAC, Credenciales Delegadas y Alembic

- **Aislamiento estricto en Backend:** Todo endpoint operativo exige token JWT (`Authorization: Bearer ...`) validado por `get_current_user`. Los roles `org_admin`, `teacher` y `operator` quedan fijados a su `organization_id` mediante `resolve_org_scope` y `assert_org_access`, devolviendo `403 Forbidden` ante cualquier intento de acceso cruzado.
- **Superadmin global:** `superadmin` accede a todas las organizaciones y es el único rol autorizado para crear nuevas organizaciones (asignando opcionalmente su `org_admin` inicial en la misma transacción).
- **Revocación protegida y credenciales delegadas (`security_service.py`):**
  - La revocación biométrica (individual o en lote vía `POST /api/persons/biometrics/revoke`) exige `authorization_secret` válido.
  - Acepta contraseña del `superadmin`, del `org_admin` de la organización o una `DelegatedCredential` activa (no expirada/revocada) con permiso `revoke_biometrics`.
  - Las contraseñas y claves delegadas se almacenan únicamente mediante hash **`scrypt`** con salt aleatorio (`hashlib.scrypt`) y comparación en tiempo constante (`hmac.compare_digest`).
  - Cada operación sensible escribe un registro en `audit_logs` indicando quién ejecutó, quién autorizó (o creó la credencial delegada), prefijo de credencial y objetivo afectado.
- **Migraciones versionadas:** Esquema gestionado mediante **Alembic** (`backend/alembic.ini` y `backend/migrations/`).

---

## 4. Calibración del Motor Biométrico

- **Detector (`YuNet`):** `score_threshold = 0.75`, `nms_threshold = 0.30`. Protegido mediante `threading.Lock` debido a que `setInputSize((w, h))` modifica el estado interno de la instancia de OpenCV. Si el pase inicial no detecta rostros (p. ej. contraluz severo), ejecuta automáticamente un segundo pase con realce LAB/CLAHE (`enhance_frame_for_detection`).
- **Control de Calidad, Iluminación y 6 Poses (`quality.py`):**
  - Tamaño mínimo en enrolamiento: `64 px`; en kiosco: `56 px`.
  - Nitidez mínima calibrada para webcam real (varianza del Laplaciano, con estiramiento de contraste cuando `brightness < 65.0`): `18.0` en enrolamiento y `10.0` en kiosco.
  - Brillo mínimo en enrolamiento: `32.0` (con rechazo por sombra lateral > `68.0`); en kiosco tolera desde `18.0` (hasta `95.0` de asimetría).
  - Detección automática de contraluz comparando la luminancia de fondo contra la caja facial (`backlight_delta_threshold = 70.0`).
  - Validación geométrica de las 6 poses (`frontal`, `left`, `right`, `up`, `down`, `smile`) usando `yaw_ratio`, `pitch_ratio` relativo a la toma `frontal` y `mouth_ratio` contra `frontal`.
  - Auto-captura guiada mediante endpoint `dry_run=true` requiriendo 2 frames estables consecutivos antes de guardar.
  - Verificación de auto-consistencia en enrolamiento (`self_consistency_threshold = 0.25`) para impedir que un acompañante contamine las poses de otra persona.
- **Reconocimiento (`SFace` + `sface_2021dec_v2`):**
  - Si el recorte alineado está bien iluminado (`85.0 <= mean_l <= 195.0`), se envía intacto a SFace para conservar la precisión nativa del modelo. Solo en iluminación extrema (`mean_l < 85.0` o `> 195.0`) se aplica gamma adaptativa y mezcla suave (`75/25`) con CLAHE.
  - Umbral de similitud coseno: `0.42` (más estricto que el valor base de `0.363` de OpenCV Zoo para minimizar falsos positivos en control de asistencia).
  - Margen mínimo contra el segundo candidato más parecido: `0.05` (si dos personas superan el umbral con menos de `0.05` de diferencia, el sistema reporta `"ambiguous"` en lugar de asignar mal la asistencia).

---

## 5. Flujo de Ramas Git (Gitflow)

- `main`: Rama estable de producción.
- `staging`: Rama de preproducción y pruebas integradas.
- `develop`: Rama principal de integración de desarrollo.
- `feat/*`: Ramas de funcionalidades desarrolladas desde `develop` con un commit por archivo en Español (México).

---

## 6. Preparación para Fase 3 (Modo Grupal)

El modelo `AttendanceEvent` ya incluye el campo `capture_mode` (`"kiosk_individual"` | `"group_scan"` | `"manual"`), y `BiometricEngine.detect()` devuelve **todos** los rostros detectados en un frame ordenados por área. En la Fase 3 bastará añadir el endpoint `/api/attendance/recognize-group-frame` iterando sobre todas las detecciones y una vista de revisión rápida (verde/amarillo/rojo) en el frontend, sin modificar el esquema de base de datos ni el motor ONNX.
