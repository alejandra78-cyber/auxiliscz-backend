from pydantic import BaseModel


class AdminDemoOut(BaseModel):
    mensaje: str
