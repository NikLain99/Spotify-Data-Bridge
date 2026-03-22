import json
import time
import uuid
import requests
import os
import base64
from src.infrastructure.logging import setup_logging
from dotenv import load_dotenv

# Load environment variables
ENV_PATH = "config/.env"
load_dotenv(ENV_PATH)

# Spotify app credentials
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

class SpotifyExtractor:

    # Spotify endpoints
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    BASE_URL = "https://api.spotify.com/v1/"

    def __init__(self, max_retries=3, retry_delay=1):
        # App credentials
        self.client_id = SPOTIFY_CLIENT_ID
        self.client_secret = SPOTIFY_CLIENT_SECRET

        # Fail fast if creds missing
        if not self.client_id or not self.client_secret:
            raise ValueError("Missing required Spotify credentials")

        # Retry config
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Token state
        self.access_token = None
        self.token_expiry = 0

        # Logging setup
        self.batch_id = str(uuid.uuid4())
        self.logger = setup_logging(batch_id = self.batch_id)

        # Get token on init
        self._get_access_token()

    def _get_access_token(self):
        """Request new access token via Client Credentials flow"""

        self.logger.info("Requesting an access token for the Spotify API")

        # Encode client credentials -> base64
        credentials = f"{self.client_id}:{self.client_secret}"
        auth_bytes = credentials.encode("utf-8")
        basic_token = base64.b64encode(auth_bytes).decode("utf-8")
        
        # Request headers (Basic auth)
        headers = {
            "Authorization": f"Basic {basic_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        # Request body (no user context)
        data = {
            "grant_type": "client_credentials"
        }

        # Retry loop for network resilience
        for attempt in range(1, self.max_retries + 1):
            try:
                # Request token
                response = requests.post(self.TOKEN_URL, headers=headers, data=data)
                if response.status_code == 200:
                    json_result = response.json()

                    self.access_token = json_result["access_token"]
                    expires_in = json_result["expires_in"]

                    self.token_expiry = time.time() + expires_in - 60

                    self.logger.info(f"Successfully obtained Spotify access token")
                    return
                else:
                    self.logger.warning(
                        f"Failed to get token (status {response.status_code}): {response.text}"
                    )

            except requests.exceptions.RequestException as e:
                # Network-level failure
                self.logger.error(f"Request error while getting token: {e}")

            if attempt < self.max_retries:
                self.logger.info(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)

        raise Exception("Failed to obtain Spotify access token after retries")

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """Make GET request to Spotify API with retry and token handling"""

        url = self.BASE_URL + endpoint

        for attempt in range(1, self.max_retries + 1):

            # Refresh token if expired
            if time.time() >= self.token_expiry:
                self.logger.info("Access token expired. Refreshing...")
                self._get_access_token()

            headers = {
                "Authorization": f"Bearer {self.access_token}"
            }

            try:
                response = requests.get(url, headers=headers, params=params)

                #Success
                if response.status_code == 200:
                    data = response.json()
                    formatted_json = json.dumps(data, indent=4)
                    return formatted_json
                
                #Token expired / invalid
                elif response.status_code == 401:
                    self.logger.warning("Unauthorized. Refreshing token...")
                    self._get_access_token()
                    continue

                #Rate limit
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    self.logger.warning(f"Rate limited. Retrying after {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue
                
                elif response.status_code == 404:
                    self.logger.error(f"Resource not found: {endpoint}")
                    raise ValueError(f"Resource not found: {endpoint}")

                #Other errors
                else:
                    self.logger.warning(
                        f"Request failed (status {response.status_code}): {response.text}"
                    )

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Request error: {e}")

            #Retry delay
            if attempt < self.max_retries:
                self.logger.info(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)

        raise Exception(f"Failed request to {endpoint} after retries")

    def get_artist(self, artist_id: str):
        return self._make_request(f"artists/{artist_id}")
    
    def get_artists(self, artist_ids: str):
        return self._make_request("artists", params={"ids": artist_ids})

#test
if __name__ == "__main__":
    extractor = SpotifyExtractor()
    ids = "4q3ewBCX7sLwd24euuV69X,06HL4z0CvFAxyc27GXpf02"
    get_artists = extractor.get_artists(ids)
    print(get_artists)