"""Відправка повідомлень у канал через Telegram Bot API."""

import json
import time
import urllib.error
import urllib.request

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRY_AFTER_SECONDS = 60
HTTP_TOO_MANY_REQUESTS = 429


class TelegramError(Exception):
    """Telegram не прийняв повідомлення."""


def _post(token: str, payload: dict) -> None:
    request = urllib.request.Request(
        API_URL.format(token=token),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        response.read()


def _error_details(error: urllib.error.HTTPError) -> dict:
    try:
        return json.loads(error.read().decode("utf-8"))
    except ValueError:
        return {}


def send_message(token: str, chat_id: str, text: str) -> None:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    # Тексти помилок складаємо самі: адреса запиту містить токен і не має потрапити в лог
    try:
        try:
            _post(token, payload)
        except urllib.error.HTTPError as error:
            details = _error_details(error)
            retry_after = details.get("parameters", {}).get("retry_after")
            if error.code != HTTP_TOO_MANY_REQUESTS or retry_after is None:
                raise TelegramError(f"{error.code}: {details.get('description', error.reason)}")
            time.sleep(min(int(retry_after), MAX_RETRY_AFTER_SECONDS))
            _post(token, payload)
    except urllib.error.HTTPError as error:
        raise TelegramError(f"{error.code}: {_error_details(error).get('description', error.reason)}")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise TelegramError(f"Немає зв'язку з Telegram: {type(error).__name__}")
