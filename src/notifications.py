import requests
import os

def enviar_telegram(mensaje):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("❌ Error: Faltan credenciales de Telegram en .env")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=payload)
        print("📨 Notificación enviada.")
    except Exception as e:
        print(f"Error enviando Telegram: {e}")
