from fastapi import FastAPI
import uvicorn
from app.bot import run as run_bot
import threading

app = FastAPI()


@app.on_event("startup")
async def startup_event():
    print("Starting Mattermost bot in a background thread...")
    thread = threading.Thread(target=run_bot)
    thread.daemon = True  # This ensures the thread exits when the main process exits
    thread.start()


@app.get("/")
async def root():
    return {"message": "Marty Bot is running!"}


if __name__ == "__main__":
    # This is for running FastAPI directly, e.g., for development
    # Uvicorn will be run from the command line in production or using the suggested command
    uvicorn.run(app, host="0.0.0.0", port=8000)
