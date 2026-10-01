from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
import uvicorn
from fastapi.middleware.cors import CORSMiddleware

from routers.endpoints import router

app = FastAPI()


app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)