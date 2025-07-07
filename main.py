# main.py
import uvicorn
from server import app

if __name__ == "__main__":
    # host 0.0.0.0 se serve da altre macchine,
    # altrimenti 127.0.0.1 va bene.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
