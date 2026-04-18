# AuxilioSCZ — Plataforma Inteligente de Emergencias Vehiculares 🚗🚨

Plataforma de software para reportar y gestionar emergencias vehiculares en tiempo real, conectando conductores, talleres y técnicos mediante una arquitectura web, móvil y backend inteligente.

---

## 📌 Descripción General

AuxilioSCZ permite:

- Registro e inicio de sesión seguro
- Reporte de emergencias con evidencia multimedia
- Envío de ubicación GPS
- Clasificación automática de incidentes con IA
- Asignación de talleres y técnicos
- Seguimiento del estado del servicio
- Notificaciones push
- Gestión de pagos

---

## 🧰 Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Frontend Web | Angular |
| App Móvil | Flutter |
| Backend API | FastAPI |
| Base de Datos | PostgreSQL |
| Inteligencia Artificial | Whisper, GPT-4o, GPT-4o-mini |
| Notificaciones | Firebase FCM |
| Almacenamiento de evidencias | AWS S3 |
| Autenticación | JWT |

---

## ⚡ Niveles de Prioridad

| Nivel | Valor | Tipos |
|---|---|---|
| Alta | 1 | choque, motor |
| Media | 2 | bateria, llanta, llave, incierto |
| Baja | 3 | otro |

---

## 🛠️ Tipos de Incidente

| Código | Descripción |
|---|---|
| bateria | Falla de batería o descarga total |
| llanta | Pinchazo o daño en neumático |
| motor | Falla mecánica del motor |
| choque | Accidente vehicular |
| llave | Pérdida o bloqueo de llaves |
| otro | Incidente no categorizado |
| incierto | Incidente con evidencia insuficiente |

---

## 🤖 Módulos de IA

| Módulo | Función |
|---|---|
| Whisper | Transcripción de audio del incidente |
| GPT-4o Vision | Análisis de imágenes para detectar daños |
| GPT-4o-mini | Clasificación del incidente y apoyo a priorización |

---

## 🔌 API Endpoints

| Método | Endpoint | Descripción |
|---|---|---|
| POST | /api/auth/register | Registrar un nuevo usuario |
| POST | /api/auth/login | Iniciar sesión y obtener token JWT |
| POST | /api/auth/logout | Cerrar sesión |
| POST | /api/auth/password/recovery-request | Solicitar recuperación de contraseña |
| POST | /api/auth/password/reset | Restablecer contraseña con token |
| PATCH | /api/auth/cambiar-password | Cambiar contraseña autenticado |
| POST | /api/emergencia/reportar | Reportar emergencia vehicular |
| PATCH | /api/emergencia/{incidente_id}/ubicacion | Actualizar ubicación GPS |
| GET | /api/emergencia/{incidente_id}/estado | Consultar estado de la solicitud |
| POST | /api/taller | Registrar taller |
| PATCH | /api/taller/disponibilidad | Gestionar disponibilidad del taller |
| POST | /api/asignacion/asignar | Asignar técnico o taller a un incidente |
| PATCH | /api/asignacion/{id}/estado | Actualizar estado de servicio |
| POST | /api/pagos/cotizacion | Generar cotización de servicio |
| POST | /api/pagos/procesar | Procesar pago del servicio |

---

## 🏗️ Arquitectura

### Componentes principales

- Flutter para conductores
- Angular para talleres y administración
- FastAPI como backend central
- PostgreSQL para persistencia
- AWS S3 para evidencias
- Firebase FCM para notificaciones
- Motor de IA para análisis de incidentes

### Diagrama de arquitectura en texto

```text
Flutter (Cliente)  ----\
                        \            +----------------------+
Angular (Web)     ------->  FastAPI  |  Módulos de negocio  |
                        /            +----------------------+
                       /
                      v
              +------------------+      +-----------------+      +----------------+
              |   PostgreSQL     |      |     AWS S3      |      | Firebase FCM   |
              | datos del sistema|      | evidencias media|      | notificaciones |
              +------------------+      +-----------------+      +----------------+
                               \
                                \
                                 +------------------+
                                 | Motor IA         |
                                 | Whisper + GPT-4o |
                                 +------------------+
```

---

## 👥 Roles del Sistema

- Cliente
- Taller
- Técnico
- Administrador

---

## ⚙️ Instalación

### Backend (FastAPI)

```bash
cd auxiliscz-backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Variables de entorno

Crear o ajustar el archivo `.env`:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/auxilio_scz
SECRET_KEY=tu_clave_secreta
OPENAI_API_KEY=tu_api_key_openai
FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
AWS_ACCESS_KEY_ID=tu_aws_access_key
AWS_SECRET_ACCESS_KEY=tu_aws_secret_key
AWS_BUCKET_NAME=tu_bucket
```

### Frontend Web (Angular)

```bash
cd auxiliscz-web
npm install
npm run start
```

### App Móvil (Flutter)

```bash
cd auxiliscz-movil
flutter pub get
flutter run
```

---

## 🚀 Despliegue

- Backend: Render o Railway
- Frontend Web: Vercel o Render Static
- App móvil: Android/iOS con configuración de Firebase por plataforma

---

## 📄 Licencia

Uso académico y de desarrollo interno del proyecto AuxilioSCZ.

