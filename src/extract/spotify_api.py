import uuid
import os
from src.infrastructure.logging import setup_logging
from dotenv import load_dotenv
from dotenv import find_dotenv

ENV_PATH = "config/.env"
load_dotenv(ENV_PATH)

SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

class SpotifyExtractor:
    
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    BASE_URL = "https://api.spotify.com/v1/"

    def __init__(self, max_retries=3, retry_delay=5):
        self.client_id = SPOTIFY_CLIENT_ID
        self.client_secret = SPOTIFY_CLIENT_SECRET

        if not self.client_id or not self.client_secret:
            raise ValueError("Missing required Spotify credentials")

        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.access_token = None
        self.token_expiry = 0

        self.batch_id = str(uuid.uuid4())
        self.logger = setup_logging(batch_id = self.batch_id)
        
        self._get_access_token()