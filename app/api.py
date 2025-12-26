import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.gameManager import GameManager
from app.UserManager import UserManager
from app.JWTHandler import JWTHandler
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

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
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response

# No Cache Middleware for static files
class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

app.add_middleware(HSTSMiddleware)
app.add_middleware(NoCacheStaticMiddleware)

@app.get("/")
async def root():
    index_path = os.path.join("static", "index.html")
    return FileResponse(index_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})

@app.get("/login")
async def login_page():
    login_path = os.path.join("static", "login.html")
    return FileResponse(login_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})

@app.get("/health")
async def health():
    return JSONResponse(content={"isAvailable": True})

@app.get("/v1/games")
async def list_games():
    games = gameManager.list_games()
    logger.info("Listing %d games", len(games))
    return JSONResponse(content={"games": [game.to_dict() for game in games]})

@app.post("/v1/games")
async def new_game():
    id = gameManager.new_game()
    logger.info("Created new game with ID %s", id)
    return JSONResponse(content={"id": str(id)})

@app.get("/v1/users")
async def list_users():
    users = userManager.list_users()
    logger.info("Listing %d users", len(users))
    return JSONResponse(content={"users": [user.to_dict() for user in users]})

class UserCreate(BaseModel):
    name: str
    email: str
    password: str

@app.post("/v1/users")
async def new_user(user: UserCreate):
    try:
        created = userManager.new_user(user.name, user.email, user.password)
        logger.info("Created new user with ID %s", getattr(created, "id", "<unknown>"))
        return JSONResponse(content=created.to_dict(), status_code=201)
    except Exception as e:
        logger.error("Error creating user: %s", str(e))
        return JSONResponse(content={"error": str(e)}, status_code=400)

@app.post("/register")
async def register(user: UserCreate):
    try:
        created = userManager.new_user(user.name, user.email, user.password)
        logger.info("Registered new user with ID %s", getattr(created, "id", "<unknown>"))
        response = JSONResponse(content=created.to_dict(), status_code=201, headers={"Location": "/"})
        token = jwt_handler.sign(created.name)
        response.set_cookie(key="userjwt", value=token, httponly=True, secure=False, samesite="Strict")
        return response
    except Exception as e:
        logger.error("Error registering user: %s", str(e))
        return JSONResponse(content={"error": str(e)}, status_code=400)

class UserLogin(BaseModel):
    username: str
    password: str

@app.post("/login")
async def login(userLogin: UserLogin):
    try:
        user = userManager.authenticate_user(userLogin.username, userLogin.password)
        if user:
            token = jwt_handler.sign(user.name)
            logger.info("User %s logged in successfully", user)
            response = JSONResponse(content={"token": token}, status_code=200, headers={"Location": "/"})
            response.set_cookie(key="userjwt", value=token, httponly=True, secure=False, samesite="Strict")
            return response
        else:
            logger.warning("Authentication failed for user %s", userLogin.username)
            return JSONResponse(content={"error": "Invalid credentials"}, status_code=401)
    except Exception as e:
        logger.error("Error during login for user %s: %s", userLogin.username, str(e))
        return JSONResponse(content={"error": str(e)}, status_code=400)
    
@app.get("/userDetails")
async def user_details(request: Request):
    try:
        token = request.cookies.get("userjwt")
        username = jwt_handler.verify(token)
        if username:
            logger.info("Token verified for user %s", username)
            return JSONResponse(content={"username": username}, status_code=200)
        else:
            logger.warning("Invalid or expired token")
            response = JSONResponse(content={"error": "Invalid or expired token"}, status_code=401)
            response.delete_cookie(key="userjwt")
            return response
    except Exception as e:
        logger.error("Error verifying token: %s", str(e))
        return JSONResponse(content={"error": str(e)}, status_code=400)
