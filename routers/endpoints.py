from fastapi import APIRouter

from routers.extratos_router import router as extratos_router
from routers.lancamentos_router import router as lancamentos_router
from routers.sftp_router import router as sftp_router
from routers.transcribe_router import router as transcribe_router

router = APIRouter()

router.include_router(transcribe_router)
router.include_router(extratos_router)
router.include_router(sftp_router)
router.include_router(lancamentos_router)
