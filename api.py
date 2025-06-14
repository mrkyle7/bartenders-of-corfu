import os
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from gameManager import GameManager

app = FastAPI()
gameManager = GameManager()

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    return JSONResponse(content={"games": [game.to_dict() for game in games]})

@app.post("/v1/games")
async def new_game():
    id = gameManager.new_game()
    return JSONResponse(content={"id": str(id)})
