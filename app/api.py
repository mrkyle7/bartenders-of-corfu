import os
import logging
from datetime import datetime, timezone
from uuid import UUID
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.gameManager import GameManager
from app.UserManager import UserManager, UserManagerPermissionError
from app.JWTHandler import JWTHandler
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import traceback

from app.user import TokenUser, UserValidationError

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


def _verify_token(request: Request) -> TokenUser | None:
    """Extract and verify the JWT cookie. Returns TokenUser or None."""
    token = request.cookies.get("userjwt")
    if not token:
        return None
    return jwt_handler.verify(token)


def _require_auth(request: Request) -> tuple[TokenUser | None, JSONResponse | None]:
    """Return (token_user, None) on success or (None, error_response) on failure.

    Performs both cryptographic JWT verification and server-side invalidation check:
    a token issued at or before the user's logged_out_at timestamp is rejected.
    """
    token_user = _verify_token(request)
    if token_user is None:
        return None, JSONResponse(
            status_code=401, content={"error": "Authentication required"}
        )

    # Server-side invalidation: reject tokens whose issue time is at or before the
    # last logout. iat_us in the JWT is a float with microsecond precision so that
    # tokens issued after a logout are distinguishable even within the same second.
    if token_user.iat is not None:
        user = userManager.get_user(token_user.id)
        if user and user.logged_out_at:
            try:
                logged_out_dt = datetime.fromisoformat(user.logged_out_at)
                if logged_out_dt.tzinfo is None:
                    logged_out_dt = logged_out_dt.replace(tzinfo=timezone.utc)
                if token_user.iat <= logged_out_dt:
                    response = JSONResponse(
                        status_code=401,
                        content={"error": "Token has been invalidated. Please log in again."},
                    )
                    response.delete_cookie(key="userjwt")
                    return None, response
            except (ValueError, TypeError):
                pass

    return token_user, None


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
async def list_users(request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    users = userManager.list_users()
    logger.info("Listing %d users", len(users))
    return JSONResponse(content={"users": [user.to_dict() for user in users]})


@app.get("/v1/users/{user_id}")
async def get_user(user_id: str, request: Request):
    _, err = _require_auth(request)
    if err:
        return err
    user = userManager.get_user(UUID(user_id))
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
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
        token = jwt_handler.sign(created)
        response = JSONResponse(
            content=created.to_dict(), status_code=201, headers={"Location": "/"}
        )
        response.set_cookie(
            key="userjwt", value=token, httponly=True, secure=False, samesite="Strict"
        )
        return response
    except Exception as e:
        logger.exception("Error registering user")
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
async def logout(request: Request):
    token_user = _verify_token(request)
    if token_user:
        try:
            userManager.logout_user(token_user.id)
        except Exception:
            logger.exception("Error recording logout for user %s", token_user.username)
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
        token_user, err = _require_auth(request)
        if err:
            return err
        user = userManager.get_user(token_user.id)
        if not user:
            response = JSONResponse(
                content={"error": "User not found"}, status_code=404
            )
            response.delete_cookie(key="userjwt")
            return response
        logger.info("User details for %s", token_user.username)
        return JSONResponse(content=user.to_dict(include_sensitive=True), status_code=200)
    except Exception as e:
        logger.error("Error verifying token: %s", str(e))
        response = JSONResponse(content={"error": str(e)}, status_code=400)
        response.delete_cookie(key="userjwt")
        return response


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@app.patch("/v1/users/me/password")
async def change_password(body: ChangePasswordRequest, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        userManager.change_password(token_user.id, body.old_password, body.new_password)
        logger.info("Password changed for user %s", token_user.username)
        return JSONResponse(content={"message": "Password changed successfully"})
    except UserValidationError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception:
        logger.exception("Error changing password for %s", token_user.username)
        return JSONResponse(status_code=500, content={"error": "Failed to change password"})


@app.delete("/v1/users/me")
async def delete_account(request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        userManager.delete_user(token_user.id)
        logger.info("Account deleted for user %s", token_user.username)
        response = JSONResponse(content={"message": "Account deleted"})
        response.delete_cookie(key="userjwt")
        return response
    except UserValidationError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception:
        logger.exception("Error deleting account for %s", token_user.username)
        return JSONResponse(status_code=500, content={"error": "Failed to delete account"})


@app.post("/v1/users/{user_id}/deactivate")
async def deactivate_user(user_id: str, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        userManager.deactivate_user(token_user.id, UUID(user_id))
        logger.info("User %s deactivated by admin %s", user_id, token_user.username)
        return JSONResponse(content={"message": "User deactivated"})
    except UserManagerPermissionError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})
    except UserValidationError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception:
        logger.exception("Error deactivating user %s", user_id)
        return JSONResponse(status_code=500, content={"error": "Failed to deactivate user"})


@app.post("/v1/users/{user_id}/reactivate")
async def reactivate_user(user_id: str, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        userManager.reactivate_user(token_user.id, UUID(user_id))
        logger.info("User %s reactivated by admin %s", user_id, token_user.username)
        return JSONResponse(content={"message": "User reactivated"})
    except UserManagerPermissionError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})
    except UserValidationError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception:
        logger.exception("Error reactivating user %s", user_id)
        return JSONResponse(status_code=500, content={"error": "Failed to reactivate user"})


@app.get("/v1/admin/users")
async def admin_list_users(request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    admin = userManager.get_user(token_user.id)
    if not admin or not admin.is_admin:
        return JSONResponse(status_code=403, content={"error": "Admin access required"})
    users = userManager.list_users()
    logger.info("Admin %s listing %d users", token_user.username, len(users))
    return JSONResponse(
        content={"users": [u.to_dict(include_sensitive=True) for u in users]}
    )
