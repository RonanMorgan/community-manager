from fastapi import FastAPI
import uvicorn
import threading
import logging  # Added logging
from app.bot import MartyBot  # Changed import
from app import config  # Added direct config import

app = FastAPI()

# Configure logging for main.py as well, if not already configured by bot.py at this point
# This depends on import order and how/when bot.py's logging is set up.
# For safety, can configure it here too, or ensure bot.py's config is run first.
# Assuming bot.py's logging config is sufficient for now if it's imported early.
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

marty_bot_instance = None  # Optional: can be global if needed for shutdown or other interactions


@app.on_event("startup")
async def startup_event():
    global marty_bot_instance
    logging.info("Application startup: Initializing and starting MartyBot...")

    # Pass the actual config module to MartyBot constructor
    marty_bot_instance = MartyBot(config)

    logging.info("Starting MartyBot in a new thread...")
    # MartyBot.start() method handles its own asyncio loop management
    bot_thread = threading.Thread(target=marty_bot_instance.start, daemon=True)
    bot_thread.start()
    logging.info("MartyBot thread started.")


@app.get("/")
async def root():
    return {"message": "Marty Bot is running!"}


if __name__ == "__main__":
    # This is for running FastAPI directly, e.g., for development
    # Uvicorn will be run from the command line in production or using the suggested command
    uvicorn.run(app, host="0.0.0.0", port=8000)
