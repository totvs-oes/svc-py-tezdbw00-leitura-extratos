from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.endpoints import router

app = FastAPI()


app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    # allow_credentials não é usado: a autenticação é por Bearer token, não por cookie,
    # e o navegador recusa allow_origins="*" combinado com allow_credentials=True.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)