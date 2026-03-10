# Prolific Notifier 🚨

Un bot automatizado que consulta la API de Prolific periódicamente y envía notificaciones a través de Telegram cuando hay nuevos estudios disponibles para realizar.

Está diseñado para ejecutarse 100% de forma gratuita y sin servidores, utilizando **AWS Lambda** (Free Tier) y **Amazon EventBridge**. Además, incluye un sistema automático para renovar los tokens de sesión de Prolific (OIDC/Auth0), evitando inicios de sesión manuales continuos.

## Características ✨

- **Costo Cero ($0):** Utiliza la capa de uso gratuito continua de AWS Lambda.
- **Auto-Refresh de Tokens:** Usa tu `refresh_token` de Prolific para renovar el acceso de forma automática. ¡No necesitas actualizarlo todos los días!
- **Notificaciones por Telegram:** Cero correos perdidos; recibe un mensaje push instantáneo en el chat con nombre, pago, cupos disponibles y duración.
- **Deduplicación Inteligente:** Usa AWS Systems Manager (SSM) Parameter Store para recordar los estudios ya notificados. No envía notificaciones duplicadas por el mismo estudio.
- **Horas Valle ("Modo Reposo"):** Pausa las consultas durante la madrugada para no alertar innecesariamente y mantener un perfil bajo en la API de Prolific.

## Requisitos Previos 📋

1. Cuenta de **AWS** (Amazon Web Services).
2. Un bot de **Telegram** (creado vía [@BotFather](https://t.me/BotFather)) y tu ID de chat.
3. Cuenta activa de **Prolific**.

## Configuración 🛠️

### 1. Variables Locales (Para pruebas)
Copia el archivo `.env.example` y renómbralo a `.env`. Rellena tus datos:
```env
TELEGRAM_BOT_TOKEN=tu_token_de_bot
TELEGRAM_CHAT_ID=tu_id_de_chat
PROLIFIC_CLIENT_ID=tu_client_id_extraido_de_prolific
```
*(Nota: El `PROLIFIC_CLIENT_ID` se puede extraer del Local Storage del navegador al tener sesión iniciada en Prolific, dentro de la key `oidc.user:...`)*

### 2. AWS SSM Parameter Store
Debes crear los siguientes parámetros en AWS Systems Manager (SSM) en la misma región donde vas a ejecutar tu Lambda:

- `/prolificNotify/refresh_token` (Tipo: **SecureString**): Tu refresh token (sacado del Local Storage en `app.prolific.com`).
- `/prolificNotify/access_token` (Tipo: **SecureString**): Se generará y renovará automáticamente, pero puedes crearlo vacío al inicio.
- `/prolificNotify/seen_study_ids` (Tipo: **String**): Se actualiza automáticamente para recordar los estudios notificados. Puedes crearlo vacío.

### 3. Roles e IAM (Lambda)
La función de AWS Lambda necesita una política (Policy) de IAM adicional para acceder a SSM:
- `ssm:GetParameter`
- `ssm:PutParameter`

### 4. Deploy (AWS Lambda)
Como este proyecto usa librerías externas (como `requests`), necesitas empaquetarlo:
1. Instala las dependencias en una carpeta local: `pip install -r requirements.txt -t lambda_package/`
2. Copia `app.py` dentro de la carpeta.
3. Comprime el contenido de la carpeta en un `.zip`.
4. Sube este `.zip` a tu función AWS Lambda.
5. Configura las **Variables de Entorno** en tu AWS Lambda:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `PROLIFIC_CLIENT_ID`
   - `SSM_REFRESH_TOKEN` = `/prolificNotify/refresh_token`
   - `SSM_ACCESS_TOKEN` = `/prolificNotify/access_token`
   - `SSM_SEEN_PARAM_NAME` = `/prolificNotify/seen_study_ids`

### 5. Automatización (EventBridge)
Utiliza Amazon EventBridge Scheduler para ejecutar esta función Lambda cada `rate(2 minutes)` (o el tiempo que prefieras, respetando siempre no saturar la API).

## Licencia 📄
MIT - Eres libre de usar y modificar el código de forma personal.