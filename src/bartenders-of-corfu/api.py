import os
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from gameManager import GameManager
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI()
gameManager = GameManager()

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# HSTS Middleware
class HSTSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response

app.add_middleware(HSTSMiddleware)

@app.get("/")
async def root():
    index_path = os.path.join("static", "index.html")
    return FileResponse(index_path)

@app.get("/health")
async def health():
    return JSONResponse(content={"isAvailable": True})

@app.get("/v1/games")
async def list_games():
    games = gameManager.list_games()
    print(f"Listing {len(games)} games")
    return JSONResponse(content={"games": [game.to_dict() for game in games]})

@app.post("/v1/games")
async def new_game():
    id = gameManager.new_game()
    return JSONResponse(content={"id": str(id)})
