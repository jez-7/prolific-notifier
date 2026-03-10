import os
import json
import time
import boto3
import requests

TELEGRAM_BOT_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID     = os.environ.get('TELEGRAM_CHAT_ID')

SSM_REFRESH_TOKEN    = os.environ.get('SSM_REFRESH_TOKEN', '/prolificNotify/refresh_token')
SSM_ACCESS_TOKEN     = os.environ.get('SSM_ACCESS_TOKEN', '/prolificNotify/access_token')
SSM_SEEN_PARAM_NAME  = os.environ.get('SSM_SEEN_PARAM_NAME', '/prolificNotify/seen_study_ids')

# OIDC Config (Auth0)
PROLIFIC_AUTH_URL  = "https://auth.prolific.com/oauth/token"
PROLIFIC_CLIENT_ID = os.environ.get('PROLIFIC_CLIENT_ID')

SSM_CLIENT = None


def get_ssm_client():
    global SSM_CLIENT
    if SSM_CLIENT is None:
        SSM_CLIENT = boto3.client('ssm')
    return SSM_CLIENT


def get_ssm(name, default=None):
    """Lee un parámetro de SSM. Devuelve default si no existe."""
    client = get_ssm_client()
    try:
        r = client.get_parameter(Name=name, WithDecryption=True)
        return r['Parameter']['Value']
    except client.exceptions.ParameterNotFound:
        return default
    except Exception as e:
        print(f"SSM get error ({name}): {e}")
        return default


def put_ssm(name, value, secure=False):
    """Guarda o actualiza un parámetro en SSM."""
    param_type = 'SecureString' if secure else 'String'
    try:
        get_ssm_client().put_parameter(
            Name=name, Value=value, Type=param_type, Overwrite=True
        )
    except Exception as e:
        print(f"SSM put error ({name}): {e}")


def refresh_access_token():
    """
    Usa el refresh_token guardado en SSM para obtener un nuevo access_token
    desde Auth0 (auth.prolific.com). Si Auth0 rota el refresh_token,
    también guarda el nuevo.
    Returns: access_token (str) o None si falla.
    """
    refresh_token = get_ssm(SSM_REFRESH_TOKEN)
    if not refresh_token:
        print("Error: no hay refresh_token en SSM.")
        return None

    payload = {
        "grant_type": "refresh_token",
        "client_id": PROLIFIC_CLIENT_ID,
        "refresh_token": refresh_token,
    }

    try:
        r = requests.post(PROLIFIC_AUTH_URL, json=payload, timeout=10)

        if r.status_code == 200:
            data = r.json()
            new_access_token = data.get("access_token")
            new_refresh_token = data.get("refresh_token")

            # guardar nuevo access_token
            if new_access_token:
                put_ssm(SSM_ACCESS_TOKEN, new_access_token, secure=True)
                print("Access token renovado exitosamente.")

            # si Auth0 cambia el refresh_token, guardar el nuevo
            if new_refresh_token and new_refresh_token != refresh_token:
                put_ssm(SSM_REFRESH_TOKEN, new_refresh_token, secure=True)
                print("Refresh token rotado y guardado.")

            return new_access_token
        else:
            print(f"Error renovando token: {r.status_code} — {r.text[:200]}")
            return None

    except Exception as e:
        print(f"Error en refresh_access_token: {e}")
        return None


def send_telegram_alert(message):
 
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Error enviando alerta a Telegram: {e}")


def lambda_handler(event, context):
    from datetime import datetime, timedelta

    #  horas valle

    hora_argentina = (datetime.utcnow() - timedelta(hours=3)).hour
    
    if 4 <= hora_argentina < 10:
        print(f"Modo reposo: Son las {hora_argentina} hs. No se consultará Prolific.")
        return {"statusCode": 200, "body": "Horario inactivo"}

    prolific_url = "https://internal-api.prolific.com/api/v1/participant/studies/"

    # obtener access_token 
    access_token = refresh_access_token()
    if not access_token:
        send_telegram_alert(
            "🔴 *Error crítico*\n\n"
            "No se pudo renovar el token de Prolific.\n"
            "Es posible que el refresh token haya expirado.\n"
            "Necesitás actualizar el refresh token manualmente en SSM."
        )
        return {"statusCode": 401, "body": "No se pudo renovar el token"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, */*",
        "Accept-Language": "es-ES,es;q=0.9",
        "x-browser-info": "chrome/120",
        "x-client-version": "1.0.0",
    }

    try:
        response = requests.get(prolific_url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            estudios = data.get('results', [])

            if not estudios:
                print("Sin estudios disponibles.")
                return {"statusCode": 200, "body": "Sin estudios"}

            # solo notificar estudios nuevos
            ids_actuales = {str(e.get('id', '')) for e in estudios}
            ids_vistos_raw = get_ssm(SSM_SEEN_PARAM_NAME, default='')
            ids_vistos = set(ids_vistos_raw.split(',')) if ids_vistos_raw else set()

            nuevos = [e for e in estudios if str(e.get('id', '')) not in ids_vistos]

            if not nuevos:
                print(f"Sin estudios NUEVOS ({len(estudios)} conocidos, ya notificados).")
                return {"statusCode": 200, "body": "Sin estudios nuevos"}

            # armar y enviar alerta
            mensaje = f"🚨 *¡HAY {len(nuevos)} ESTUDIO(S) NUEVO(S)!* 🚨\n\n"
            for estudio in nuevos:
                nombre   = estudio.get('name', 'Estudio sin nombre')
                pago     = estudio.get('reward', 0) / 100
                lugares  = estudio.get('total_available_places', 'N/A')
                duracion = estudio.get('average_completion_time_minutes', '?')
                mensaje += f"📌 *{nombre}*\n💰 £{pago:.2f} | ⏱ {duracion} min | 🧑‍🤝‍🧑 Cupos: {lugares}\n\n"

            mensaje += "➡️ [Entrar a Prolific](https://app.prolific.com/studies)"
            send_telegram_alert(mensaje)
            print(f"Alerta enviada: {len(nuevos)} estudio(s) nuevo(s).")

            # guardar los IDs actuales como "ya vistos"
            put_ssm(SSM_SEEN_PARAM_NAME, ','.join(ids_actuales))

            return {"statusCode": 200, "body": f"Alerta enviada: {len(nuevos)} nuevos"}

        elif response.status_code == 401:
            print("Access token rechazado a pesar de ser recién renovado.")
            send_telegram_alert(
                "⚠️ *Token rechazado por Prolific*\n\n"
                "El access token recién renovado fue rechazado.\n"
                "Puede que el refresh token haya expirado.\n"
                "Actualizalo en SSM Parameter Store."
            )
            return {"statusCode": 401, "body": "Token rechazado"}

        else:
            print(f"Error de Prolific: {response.status_code} — {response.text[:200]}")
            return {"statusCode": response.status_code, "body": "Error de Prolific"}

    except requests.exceptions.Timeout:
        print("Timeout al conectar con Prolific.")
        return {"statusCode": 504, "body": "Timeout"}

    except Exception as e:
        print(f"Error inesperado: {e}")
        return {"statusCode": 500, "body": "Error interno"}


# pruebas locales
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

  
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID')

    print("Enviando mensaje de prueba a Telegram...")
    send_telegram_alert("✅ Bot de Prolific configurado con auto-refresh de tokens.")
    
