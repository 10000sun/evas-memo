from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import ws

app = FastAPI(title="evas-memo", lifespan=ws.lifespan)
app.include_router(ws.router)
app.mount("/static", StaticFiles(directory="static"), name="static")
