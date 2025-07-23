# main.py
import os

import uvicorn

from server import app

if __name__ == "__main__":
    host = os.getenv("APP_HOST", "127.0.0.1")   # default: tutti gli IP
    port = int(os.getenv("PORT", 8000))       # porta configurabile
    uvicorn.run(app, host=host, port=port, log_level="info")
