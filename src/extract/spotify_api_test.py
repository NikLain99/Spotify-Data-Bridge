# src/extract/spotify_api.py

import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv
from config.logging_config import setup_logging

# Загрузка .env
load_dotenv("config/.env")

# Инициализация логирования
import uuid
batch_id = str(uuid.uuid4())
logger = setup_logging(batch_id=batch_id)

# Spotify credentials
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

class SpotifyExtractor:
    """
    Production-ready Spotify extractor:
    - Client Credentials Flow для получения токена
    - Retry + логирование
    - Возвращает DataFrame
    """

    TOKEN_URL = "https://accounts.spotify.com/api/token"
    BASE_URL = "https://api.spotify.com/v1/"

    def __init__(self, max_retries=3, retry_delay=5):
        self.client_id = SPOTIFY_CLIENT_ID
        self.client_secret = SPOTIFY_CLIENT_SECRET
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.access_token = None
        self.token_expiry = 0
        self._get_access_token()

    def _get_access_token(self):
        """
        Получение access token через Client Credentials Flow
        """
        self.logger_info("Запрос access token к Spotify API")
        try:
            response = requests.post(
                self.TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
                timeout=10
            )
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            self.token_expiry = time.time() + token_data.get("expires_in", 3600) - 60  # буфер 1 мин
            self.logger_info("Успешно получен access token")
        except requests.exceptions.RequestException as e:
            logger.exception(f"Не удалось получить access token: {e}")
            raise

    def _refresh_token_if_needed(self):
        if self.access_token is None or time.time() >= self.token_expiry:
            self._get_access_token()

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """
        Универсальный метод GET запроса к Spotify API
        с retry и логированием
        """
        url = f"{self.BASE_URL}{endpoint}"
        attempt = 0

        while attempt < self.max_retries:
            self._refresh_token_if_needed()
            headers = {"Authorization": f"Bearer {self.access_token}"}
            try:
                logger.info(f"Запрос к Spotify API: {url}, params={params}, попытка {attempt+1}")
                response = requests.get(url, headers=headers, params=params, timeout=10)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", self.retry_delay))
                    logger.warning(f"Rate limit hit, ожидаем {retry_after} секунд")
                    time.sleep(retry_after)
                    attempt += 1
                    continue

                response.raise_for_status()
                logger.info(f"Успешный ответ от Spotify API: {url}")
                return response.json()

            except requests.exceptions.RequestException as e:
                logger.error(f"Ошибка запроса к {url}: {e}")
                attempt += 1
                if attempt < self.max_retries:
                    logger.info(f"Повторная попытка через {self.retry_delay} секунд")
                    time.sleep(self.retry_delay)
                else:
                    logger.exception("Достигнут предел повторных попыток")
                    raise

    def extract_top_tracks(self, limit: int = 50, time_range: str = "short_term") -> pd.DataFrame:
        """
        Извлечение top tracks текущего пользователя
        """
        endpoint = "me/top/tracks"
        params = {"limit": limit, "time_range": time_range}
        data = self._make_request(endpoint, params)
        items = data.get("items", [])
        df = pd.json_normalize(items)
        logger.info(f"Извлечено {len(df)} треков")
        return df

    def extract_playlists(self, user_id: str, limit: int = 50) -> pd.DataFrame:
        """
        Извлечение плейлистов пользователя
        """
        endpoint = f"users/{user_id}/playlists"
        params = {"limit": limit}
        data = self._make_request(endpoint, params)
        items = data.get("items", [])
        df = pd.json_normalize(items)
        logger.info(f"Извлечено {len(df)} плейлистов")
        return df

    def logger_info(self, message):
        """
        Локальный метод для логирования из __init__
        """
        logger.info(message)