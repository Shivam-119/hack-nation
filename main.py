"""Entry point: run the VC Brain server."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("vc_brain.api.app:app", host="0.0.0.0", port=8000, reload=True)
