import os             # for environment variables and file paths
import time           # for measuring request duration and token expiry
import uuid           # for generating unique batch_id for logging
import base64         # for encoding client_id:client_secret for Spotify auth
import traceback      # for getting stack trace in exception logging
from urllib.parse import urlencode  # for building query strings in auth URLs

import httpx          # async HTTP client for requests to Spotify API
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from dotenv import load_dotenv  # load .env environment variables
import uvicorn        # ASGI server to run FastAPI
import logging        # Python logging library

from src.infrastructure.logging import setup_logging  # custom logging setup
# ----------------------------
# DESCRIPTION
# This module implements Spotify OAuth 2.0 authentication flow using FastAPI.
# It provides two main endpoints:
# 1. GET / - Redirects user to Spotify's authorization page to log in and authorize the app.
# 2. GET /callback - Handles the redirect from Spotify after user authorization
# exchanges the authorization code for an access token, and returns the token data as JSON.
# The SpotifyAuthServer class encapsulates the logic for building the auth URL and exchanging the code for a token.
# The module also includes middleware for logging all incoming requests and global exception handlers for consistent error responses and logging.
# ----------------------------


# ----------------------------
# 1. Settings & logging
# ----------------------------

batch_id = str(uuid.uuid4())               # unique ID for this run/session
logger = setup_logging(batch_id=batch_id)  # configure logging with batch_id

logger_api = logging.getLogger("src.api")        # logger for API endpoints & middleware
logger_spotify = logging.getLogger("src.spotify")# logger for Spotify-specific actions

load_dotenv("config/.env") # load environment variables from .env file

# Spotify app credentials
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

# OAuth & API settings
SCOPE = "user-read-private user-read-email"        # requested scopes
AUTH_URL = "https://accounts.spotify.com/authorize" # OAuth authorize endpoint
TOKEN_URL = "https://accounts.spotify.com/api/token" # OAuth token endpoint

app = FastAPI() # instantiate FastAPI app

# ----------------------------
# 2. Middleware logging
# ----------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()   # track request start time
    try:
        response = await call_next(request)  # call next middleware / endpoint
    except Exception:
        logger_api.error(f"Request failed | path={request.url.path}")
        raise

    duration = round((time.time() - start_time) * 1000, 2)

    logger_api.info(
        f"{request.method} {request.url.path} "
        f"status={response.status_code} "
        f"duration={duration}ms"
    )

    return response

# ----------------------------
# 3. Global exception handlers
# ----------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTPException errors (like 400, 404, 502)"""

    # Log the error with WARNING level
    logger_api.warning(f"HTTP error | path={request.url.path} | status={exc.status_code} | detail={exc.detail}")

    # Return JSON response to client with original HTTP status and detail
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all handler for unhandled exceptions"""

    # Log full traceback for debugging
    logger_api.error(f"Unhandled error | path={request.url.path} | error={str(exc)}\n{traceback.format_exc()}")

    # Return generic 500 Internal Server Error to client
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class SpotifyAuthServer:
    def __init__(self):
        self.client_id = CLIENT_ID
        self.client_secret = CLIENT_SECRET
        self.redirect_uri = REDIRECT_URI
        self.scope = SCOPE
        self.auth_url = AUTH_URL
        self.token_url = TOKEN_URL
    

    def get_auth_url(self):
        """build full authorization URL for user login"""
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
            "show_dialog": "true"
        }
        return f"{self.auth_url}?{urlencode(params)}"


    async def exchange_code_for_token(self, code: str):
        """Exchange authorization code for Spotify access token"""

        # Encode client_id:client_secret as Base64 for HTTP Basic Auth
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        # Prepare POST data for token request
        data = {
            "code": code,                        # authorization code received from Spotify
            "redirect_uri": self.redirect_uri,   # must match the one used in /authorize
            "grant_type": "authorization_code"   # OAuth 2.0 flow type
        }

        # HTTP headers for POST request
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_header}" # Spotify expects Basic auth here
        }

        # Async HTTP request to Spotify token endpoint
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.post(
                    self.token_url,
                    data=data,
                    headers=headers
                )
                response.raise_for_status() # raise exception for 4xx/5xx responses

            # Handle HTTP-level errors returned by Spotify
            except httpx.HTTPStatusError as e:
                logger_spotify.error(
                    f"Spotify API error | status={e.response.status_code} | body={e.response.text}"
                )
                raise HTTPException(
                    status_code=502,
                    detail="Spotify API error"
                )

            # Handle network / connection errors
            except httpx.RequestError as e:
                logger_spotify.error(f"Network error | error={str(e)}")
                raise HTTPException(
                    status_code=503,
                    detail="External service unavailable"
                )

        # Return JSON containing access_token, refresh_token, expires_in, etc.
        return response.json()

# ----------------------------
# 5. Dependency
# ----------------------------

def get_auth_service():
    return SpotifyAuthServer()

# ----------------------------
# 6. Endpoints
# ----------------------------

@app.get("/")
async def root(auth: SpotifyAuthServer = Depends(get_auth_service)):
    return RedirectResponse(auth.get_auth_url())

@app.get("/callback")
async def callback(request: Request, auth: SpotifyAuthServer = Depends(get_auth_service)):
    """
    Spotify OAuth callback endpoint
    Handles Spotify redirect after user login
    """

    # Read query parameters from Spotify redirect
    code = request.query_params.get("code")   # the authorization code
    error = request.query_params.get("error") # any error returned by Spotify

    # If Spotify returned an error, log and raise HTTP 400
    if error:
        logger_api.error(f"HTTPException: {error}")
        raise HTTPException(status_code=400, detail=error)

    # If code is missing, log and raise HTTP 400
    if not code:
        logger_api.error("HTTPException: No code provided")
        raise HTTPException(status_code=400, detail="No code provided")

    # Log that we are exchanging the code for an access token
    logger_api.info("Exchanging code for token")
    token_data = await auth.exchange_code_for_token(code)  # call method above

    # Log successful token retrieval
    logger_api.info("Token successfully received")

    # Return token JSON to client (access_token, refresh_token, expires_in, etc.)
    return token_data

# ----------------------------
# 7. Run server(for test if you need)
# ----------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)