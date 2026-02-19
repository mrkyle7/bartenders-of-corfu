import os
import logging
from uuid import UUID
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.gameManager import GameManager
from app.UserManager import UserManager
from app.JWTHandler import JWTHandler
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import traceback

from app.user import TokenUser

logger = logging.getLogger(__name__)

app = FastAPI()
gameManager = GameManager()
userManager = UserManager()
jwt_handler = JWTHandler()

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")


# HSTS Middleware
class HSTSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )
        return response


# No Cache Middleware for static files
class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(HSTSMiddleware)
app.add_middleware(NoCacheStaticMiddleware)


@app.get("/")
async def root():
    index_path = os.path.join("static", "index.html")
    return FileResponse(
        index_path,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/login")
async def login_page():
    login_path = os.path.join("static", "login.html")
    return FileResponse(
        login_path,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/game")
async def game_page():
    login_path = os.path.join("static", "game.html")
    return FileResponse(
        login_path,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/health")
async def health():
    return JSONResponse(content={"isAvailable": True})


@app.get("/v1/games")
async def list_games():
    games = gameManager.list_games()
    logger.info("Listing %d games", len(games))
    return JSONResponse(content={"games": [game.to_dict() for game in games]})


@app.get("/v1/games/{game_id}")
async def get_game(game_id: str, request: Request):
    token = request.cookies.get("userjwt")
    if token is None:
        return JSONResponse(
            status_code=401, content={"error": "Please log in to view a game"}
        )
    try:
        user = jwt_handler.verify(token)
        if user:
            game = gameManager.get_game_by_id(UUID(game_id))
            if user.id not in game.players:
                return JSONResponse(
                    status_code=403,
                    content={"error": "User is not a member of this game"},
                )
            else:
                logger.info(f"{user.username} get game info for ID {game_id}")
                return JSONResponse(content=game.to_dict())
        else:
            logger.warning("Invalid or expired token")
            response = JSONResponse(
                content={"error": "Invalid or expired token"}, status_code=401
            )
            response.delete_cookie(key="userjwt")
            return response
    except Exception:
        logger.exception("Failed to validate user on get game")
        return JSONResponse(
            status_code=401, content={"error": "Please re-login in to view a game"}
        )


@app.post("/v1/games")
async def new_game(request: Request):
    token = request.cookies.get("userjwt")
    if token is None:
        return JSONResponse(
            status_code=401, content={"error": "Please log in to create a game"}
        )
    try:
        token_user: TokenUser = jwt_handler.verify(token)
        if token_user:
            # Get the full user object from the database
            user = userManager.get_user(token_user.id)
            if user:
                game_id = gameManager.new_game(user)
                logger.info(f"{user.username} created new game with ID {game_id}")
                return JSONResponse(content={"id": str(game_id)})
            else:
                return JSONResponse(
                    status_code=401, content={"error": "User not found"}
                )
        else:
            logger.warning("Invalid or expired token")
            response = JSONResponse(
                content={"error": "Invalid or expired token"}, status_code=401
            )
            response.delete_cookie(key="userjwt")
            return response
    except Exception:
        logger.exception("Error creating game")
        return JSONResponse(status_code=500, content={"error": "Failed to create game"})


@app.post("/v1/games/{game_id}/join")
async def join_game(game_id: str, request: Request):
    from uuid import UUID

    token = request.cookies.get("userjwt")
    if token is None:
        return JSONResponse(
            status_code=401, content={"error": "Please log in to join a game"}
        )
    try:
        user_short = jwt_handler.verify(token)
        if user_short:
            try:
                gameManager.add_player(user_short.id, UUID(game_id))
                logger.info(f"{user_short.username} joined game with ID {game_id}")
                return JSONResponse(content={"message": "Joined game successfully"})
            except Exception:
                logging.exception("Failed to add user to game")
                return JSONResponse(
                    status_code=404, content={"error": "Game not found"}
                )
        else:
            logger.warning("Invalid or expired token")
            response = JSONResponse(
                content={"error": "Invalid or expired token"}, status_code=401
            )
            response.delete_cookie(key="userjwt")
            return response
    except Exception:
        logger.exception("Error joining game")
        return JSONResponse(status_code=400, content={"error": "Failed to join game"})


@app.get("/v1/users")
async def list_users():
    users = userManager.list_users()
    logger.info("Listing %d users", len(users))
    return JSONResponse(content={"users": [user.to_dict() for user in users]})


@app.get("/v1/users/{user_id}")
async def get_user(user_id: str):
    user = userManager.get_user(UUID(user_id))
    return JSONResponse(content=user.to_dict())


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


@app.post("/v1/users")
async def new_user(user: UserCreate):
    try:
        created = userManager.new_user(user.username, user.email, user.password)
        logger.info("Created new user with ID %s", getattr(created, "id", "<unknown>"))
        return JSONResponse(content=created.to_dict(), status_code=201)
    except Exception as e:
        logger.error("Error creating user: %s", str(e))
        return JSONResponse(content={"error": str(e)}, status_code=400)


@app.post("/register")
async def register(user: UserCreate):
    try:
        created = userManager.new_user(user.username, user.email, user.password)
        logger.info(
            "Registered new user with ID %s", getattr(created, "id", "<unknown>")
        )
        response = JSONResponse(
            content=created.to_dict(), status_code=201, headers={"Location": "/"}
        )
        token = jwt_handler.sign(created)
        response.set_cookie(
            key="userjwt", value=token, httponly=True, secure=False, samesite="Strict"
        )
        return response
    except Exception as e:
        logger.exception("Error registering user")
        # If DEBUG is enabled, include the stack trace in the JSON response for debugging
        if os.getenv("DEBUG", "false").lower() in ("1", "true", "yes"):
            tb = traceback.format_exc()
            return JSONResponse(
                content={"error": str(e), "traceback": tb}, status_code=400
            )
        return JSONResponse(content={"error": str(e)}, status_code=400)


class UserLogin(BaseModel):
    username: str
    password: str


@app.post("/logout")
async def logout():
    response = JSONResponse(content={"message": "Logged out"}, status_code=200)
    response.delete_cookie(key="userjwt")
    logger.info("User logged out")
    return response


@app.post("/login")
async def login(userLogin: UserLogin):
    try:
        user = userManager.authenticate_user(userLogin.username, userLogin.password)
        if user:
            token = jwt_handler.sign(user)
            logger.info("User %s logged in successfully", user)
            response = JSONResponse(
                content=user.to_dict(), status_code=200, headers={"Location": "/"}
            )
            response.set_cookie(
                key="userjwt",
                value=token,
                httponly=True,
                secure=False,
                samesite="Strict",
            )
            return response
        else:
            logger.warning("Authentication failed for user %s", userLogin.username)
            return JSONResponse(
                content={"error": "Invalid credentials"}, status_code=401
            )
    except Exception as e:
        logger.error("Error during login for user %s: %s", userLogin.username, str(e))
        return JSONResponse(content={"error": str(e)}, status_code=400)


@app.get("/userDetails")
async def user_details(request: Request):
    try:
        token = request.cookies.get("userjwt")
        user = jwt_handler.verify(token)
        if user:
            logger.info("Token verified for user %s", user)
            return JSONResponse(content=user.to_dict(), status_code=200)
        else:
            logger.warning("Invalid or expired token")
            response = JSONResponse(
                content={"error": "Invalid or expired token"}, status_code=401
            )
            response.delete_cookie(key="userjwt")
            return response
    except Exception as e:
        logger.error("Error verifying token: %s", str(e))
        response = JSONResponse(content={"error": str(e)}, status_code=400)
        response.delete_cookie(key="userjwt")
        return response
