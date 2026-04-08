from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def root():
    return {"ok": True, "route": "ia"}
