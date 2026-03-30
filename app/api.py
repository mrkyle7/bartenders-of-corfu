import os
import logging
from datetime import datetime, timezone
from uuid import UUID
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.gameManager import GameManager
from app.game import GameException
from app.UserManager import UserManager, UserManagerPermissionError
from app.JWTHandler import JWTHandler
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import traceback

from app.user import TokenUser, UserValidationError
from typing import Optional, List

_VALID_STATUSES = {"NEW", "STARTED", "ENDED"}

logger = logging.getLogger(__name__)

app = FastAPI()
gameManager = GameManager()
userManager = UserManager()
jwt_handler = JWTHandler()


@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        os.path.join("static", "sw.js"),
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@app.get("/manifest.json")
async def manifest():
    return FileResponse(
        os.path.join("static", "manifest.json"),
        media_type="application/json",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@app.post("/refresh-token")
async def refresh_token(request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    user = userManager.get_user(token_user.id)
    if not user:
        return JSONResponse(status_code=401, content={"error": "User not found"})
    token = jwt_handler.sign(user)
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        key="userjwt",
        value=token,
        httponly=True,
        secure=False,
        samesite="Strict",
        max_age=14 * 24 * 60 * 60,
    )
    return response


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
                        content={
                            "error": "Token has been invalidated. Please log in again."
                        },
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


@app.get("/admin")
async def admin_page():
    admin_path = os.path.join("static", "admin.html")
    return FileResponse(
        admin_path,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/profile")
async def profile_page():
    profile_path = os.path.join("static", "profile.html")
    return FileResponse(
        profile_path,
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
async def list_games(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    player_id: Optional[str] = Query(default=None),
):
    status_list: Optional[List[str]] = None
    if status:
        status_list = [s.strip().upper() for s in status.split(",") if s.strip()]
        invalid = [s for s in status_list if s not in _VALID_STATUSES]
        if invalid:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
                },
            )
    player_uuid: Optional[UUID] = None
    if player_id:
        try:
            player_uuid = UUID(player_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid player_id"})

    games, total = gameManager.list_games(
        page=page, page_size=page_size, status=status_list, player_id=player_uuid
    )

    # Resolve usernames in a single batch query
    all_ids: set[UUID] = set()
    for game in games:
        all_ids.add(game.host)
        all_ids.update(game.players)
    user_lookup: dict[UUID, str] = {
        u.id: (u.username or "Unknown") for u in userManager.get_users_by_ids(all_ids)
    }

    def enrich(game) -> dict:
        d = game.to_dict()
        d["host_username"] = user_lookup.get(game.host, "Unknown")
        d["player_usernames"] = [
            user_lookup.get(pid, "Unknown") for pid in game.players
        ]
        return d

    logger.info("Listing %d games (page %d, total %d)", len(games), page, total)
    return JSONResponse(
        content={
            "games": [enrich(game) for game in games],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@app.get("/v1/games/{game_id}")
async def get_game(game_id: str, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        game = gameManager.get_game_by_id(UUID(game_id))
        if token_user.id not in game.players:
            return JSONResponse(
                status_code=403,
                content={"error": "User is not a member of this game"},
            )
        logger.info(f"{token_user.username} get game info for ID {game_id}")
        result = game.to_dict()
        result["pending_undo"] = gameManager.get_pending_undo(game.id)
        return JSONResponse(content=result)
    except Exception:
        logger.exception("Failed to validate user on get game")
        return JSONResponse(status_code=500, content={"error": "Failed to get game"})


@app.post("/v1/games")
async def new_game(request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        game_id = gameManager.new_game(token_user.id)
        logger.info(f"{token_user.username} created new game with ID {game_id}")
        return JSONResponse(content={"id": str(game_id)})
    except Exception:
        logger.exception("Error creating game")
        return JSONResponse(status_code=500, content={"error": "Failed to create game"})


@app.post("/v1/games/{game_id}/join")
async def join_game(game_id: str, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        gameManager.add_player(token_user.id, UUID(game_id))
        logger.info(f"{token_user.username} joined game with ID {game_id}")
        return JSONResponse(content={"message": "Joined game successfully"})
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "Game not found"})
    except Exception:
        logger.exception("Error joining game")
        return JSONResponse(status_code=500, content={"error": "Failed to join game"})


@app.post("/v1/games/{game_id}/start")
async def start_game(game_id: str, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        gameManager.start_game(token_user.id, UUID(game_id))
        logger.info(f"{token_user.username} started game {game_id}")
        return JSONResponse(content={"message": "Game started"})
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error starting game")
        return JSONResponse(status_code=500, content={"error": "Failed to start game"})


@app.delete("/v1/games/{game_id}/players/{player_id}")
async def remove_player(game_id: str, player_id: str, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        gameManager.remove_player(token_user.id, UUID(game_id), UUID(player_id))
        logger.info(
            f"{token_user.username} removed player {player_id} from game {game_id}"
        )
        return JSONResponse(content={"message": "Player removed successfully"})
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error removing player from game")
        return JSONResponse(
            status_code=500, content={"error": "Failed to remove player"}
        )


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
                max_age=14 * 24 * 60 * 60,  # 14 days in seconds
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
        return JSONResponse(
            content=user.to_dict(include_sensitive=True, include_email=True),
            status_code=200,
        )
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
        return JSONResponse(
            status_code=500, content={"error": "Failed to change password"}
        )


class ChangeEmailRequest(BaseModel):
    new_email: str


@app.patch("/v1/users/me/email")
async def change_email(body: ChangeEmailRequest, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        userManager.change_email(token_user.id, body.new_email)
        logger.info("Email changed for user %s", token_user.username)
        return JSONResponse(content={"message": "Email updated successfully"})
    except UserValidationError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception:
        logger.exception("Error changing email for %s", token_user.username)
        return JSONResponse(
            status_code=500, content={"error": "Failed to update email"}
        )


class ChangeThemeRequest(BaseModel):
    theme: str


@app.patch("/v1/users/me/theme")
async def change_theme(body: ChangeThemeRequest, request: Request):
    token_user, err = _require_auth(request)
    if err:
        return err
    try:
        userManager.change_theme(token_user.id, body.theme)
        logger.info("Theme changed for user %s to %s", token_user.username, body.theme)
        return JSONResponse(
            content={"message": "Theme updated successfully", "theme": body.theme}
        )
    except UserValidationError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception:
        logger.exception("Error changing theme for %s", token_user.username)
        return JSONResponse(
            status_code=500, content={"error": "Failed to update theme"}
        )


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
        return JSONResponse(
            status_code=500, content={"error": "Failed to delete account"}
        )


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
        return JSONResponse(
            status_code=500, content={"error": "Failed to deactivate user"}
        )


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
        return JSONResponse(
            status_code=500, content={"error": "Failed to reactivate user"}
        )


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


# ─── Game action endpoints ────────────────────────────────────────────────────


def _game_action_precheck(
    game_id: str, request: Request
) -> tuple[any, any, any] | tuple[None, None, any]:
    """Auth + membership check shared by all game action endpoints.
    Returns (token_user, game, None) on success or (None, None, error_response).
    """
    token_user, err = _require_auth(request)
    if err:
        return None, None, err
    try:
        game = gameManager.get_game_by_id(UUID(game_id))
    except ValueError:
        return (
            None,
            None,
            JSONResponse(status_code=400, content={"error": "Invalid game ID"}),
        )
    if game is None:
        return (
            None,
            None,
            JSONResponse(status_code=404, content={"error": "Game not found"}),
        )
    if token_user.id not in game.players:
        return (
            None,
            None,
            JSONResponse(
                status_code=403, content={"error": "Not a member of this game"}
            ),
        )
    return token_user, game, None


class DrawFromBagRequest(BaseModel):
    count: int


@app.post("/v1/games/{game_id}/actions/draw-from-bag")
async def action_draw_from_bag(
    game_id: str, body: DrawFromBagRequest, request: Request
):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.draw_from_bag(game, token_user.id, body.count)
        logger.info(
            "%s drew %d from bag in game %s", token_user.username, body.count, game_id
        )
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "drawn": payload["drawn"]}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in draw-from-bag for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


class TakeIngredientsRequest(BaseModel):
    assignments: List[dict]


@app.post("/v1/games/{game_id}/actions/take-ingredients")
async def action_take_ingredients(
    game_id: str, body: TakeIngredientsRequest, request: Request
):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.take_ingredients(
            game, token_user.id, body.assignments
        )
        logger.info("%s took ingredients in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in take-ingredients for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


class SellCupRequest(BaseModel):
    cup_index: int
    declared_specials: List[str] = []


@app.post("/v1/games/{game_id}/actions/sell-cup")
async def action_sell_cup(game_id: str, body: SellCupRequest, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.sell_cup(
            game, token_user.id, body.cup_index, body.declared_specials
        )
        logger.info("%s sold cup in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in sell-cup for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


class DrinkCupRequest(BaseModel):
    cup_index: int


@app.post("/v1/games/{game_id}/actions/drink-cup")
async def action_drink_cup(game_id: str, body: DrinkCupRequest, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.drink_cup(game, token_user.id, body.cup_index)
        logger.info("%s drank cup in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in drink-cup for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


@app.post("/v1/games/{game_id}/actions/go-for-a-wee")
async def action_go_for_a_wee(game_id: str, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.go_for_a_wee(game, token_user.id)
        logger.info("%s went for a wee in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in go-for-a-wee for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


class ClaimCardRequest(BaseModel):
    card_id: str
    cup_index: Optional[int] = None
    spirit_type: Optional[str] = None


@app.post("/v1/games/{game_id}/actions/claim-card")
async def action_claim_card(game_id: str, body: ClaimCardRequest, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.claim_card(
            game,
            token_user.id,
            body.card_id,
            cup_index=body.cup_index,
            spirit_type=body.spirit_type,
        )
        logger.info("%s claimed card in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in claim-card for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


class DrinkStoredSpiritRequest(BaseModel):
    store_card_index: int
    count: int = 1


@app.post("/v1/games/{game_id}/actions/drink-stored-spirit")
async def action_drink_stored_spirit(
    game_id: str, body: DrinkStoredSpiritRequest, request: Request
):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.drink_stored_spirit(
            game, token_user.id, body.store_card_index, body.count
        )
        logger.info("%s drank stored spirit in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in drink-stored-spirit for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


class UseStoredSpiritRequest(BaseModel):
    store_card_index: int
    cup_index: int


@app.post("/v1/games/{game_id}/actions/use-stored-spirit")
async def action_use_stored_spirit(
    game_id: str, body: UseStoredSpiritRequest, request: Request
):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.use_stored_spirit(
            game, token_user.id, body.store_card_index, body.cup_index
        )
        logger.info("%s used stored spirit in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in use-stored-spirit for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


class RefreshRowRequest(BaseModel):
    row_position: int


class RerollSpecialsRequest(BaseModel):
    chosen_specials: List[str]


@app.post("/v1/games/{game_id}/actions/reroll-specials")
async def action_reroll_specials(
    game_id: str, body: RerollSpecialsRequest, request: Request
):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.reroll_specials(
            game, token_user.id, body.chosen_specials
        )
        logger.info("%s rerolled specials in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in reroll-specials for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


@app.post("/v1/games/{game_id}/actions/refresh-card-row")
async def action_refresh_card_row(
    game_id: str, body: RefreshRowRequest, request: Request
):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.refresh_card_row(
            game, token_user.id, body.row_position
        )
        logger.info("%s refreshed card row in game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in refresh-card-row for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


@app.post("/v1/games/{game_id}/actions/quit")
async def action_quit_game(game_id: str, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.quit_game(game, token_user.id)
        logger.info("%s quit game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in quit for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


@app.post("/v1/games/{game_id}/cancel")
async def action_cancel_game(game_id: str, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        new_state, payload = gameManager.cancel_game(game, token_user.id)
        logger.info("%s cancelled game %s", token_user.username, game_id)
        return JSONResponse(
            content={"game_state": new_state.to_dict(), "move": payload}
        )
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error in cancel for game %s", game_id)
        return JSONResponse(status_code=500, content={"error": "Action failed"})


# ─── Move history & replay ────────────────────────────────────────────────────


@app.get("/v1/games/{game_id}/history")
async def get_game_history(game_id: str, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        moves = gameManager.get_history(UUID(game_id))
        return JSONResponse(content={"moves": moves})
    except Exception:
        logger.exception("Error fetching history for game %s", game_id)
        return JSONResponse(
            status_code=500, content={"error": "Failed to fetch history"}
        )


@app.get("/v1/games/{game_id}/history/{turn_number}")
async def get_state_at_turn(game_id: str, turn_number: int, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        state = gameManager.get_state_at_turn(UUID(game_id), turn_number)
        if state is None:
            return JSONResponse(status_code=404, content={"error": "Turn not found"})
        return JSONResponse(content={"game_state": state})
    except Exception:
        logger.exception(
            "Error fetching state at turn %d for game %s", turn_number, game_id
        )
        return JSONResponse(status_code=500, content={"error": "Failed to fetch state"})


# ─── Undo endpoints ───────────────────────────────────────────────────────────


@app.post("/v1/games/{game_id}/undo")
async def propose_undo(game_id: str, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    try:
        undo_req = gameManager.propose_undo(game, token_user.id)
        logger.info("%s proposed undo in game %s", token_user.username, game_id)
        return JSONResponse(content={"undo_request": undo_req})
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error proposing undo for game %s", game_id)
        return JSONResponse(
            status_code=500, content={"error": "Failed to propose undo"}
        )


class UndoVoteRequest(BaseModel):
    request_id: str
    vote: str  # "agree" | "disagree"


@app.post("/v1/games/{game_id}/undo/vote")
async def vote_undo(game_id: str, body: UndoVoteRequest, request: Request):
    token_user, game, err = _game_action_precheck(game_id, request)
    if err:
        return err
    if body.vote not in ("agree", "disagree"):
        return JSONResponse(
            status_code=400, content={"error": "vote must be 'agree' or 'disagree'"}
        )
    try:
        result = gameManager.vote_undo(game, token_user.id, body.request_id, body.vote)
        logger.info(
            "%s voted '%s' on undo in game %s", token_user.username, body.vote, game_id
        )
        return JSONResponse(content=result)
    except GameException as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})
    except Exception:
        logger.exception("Error voting on undo for game %s", game_id)
        return JSONResponse(
            status_code=500, content={"error": "Failed to vote on undo"}
        )
