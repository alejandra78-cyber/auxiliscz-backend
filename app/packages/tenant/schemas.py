from pydantic import BaseModel, EmailStr, Field


class TenantBase(BaseModel):
    codigo: str | None = Field(default=None, max_length=80)
    nombre: str = Field(..., min_length=2, max_length=150)
    descripcion: str | None = None
    estado: str = "activo"
    contacto_email: EmailStr | None = None
    contacto_telefono: str | None = Field(default=None, max_length=30)


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    codigo: str | None = Field(default=None, max_length=80)
    nombre: str | None = Field(default=None, min_length=2, max_length=150)
    descripcion: str | None = None
    estado: str | None = None
    contacto_email: EmailStr | None = None
    contacto_telefono: str | None = Field(default=None, max_length=30)


class TenantOut(BaseModel):
    id: str
    taller_id: str | None = None
    taller_nombre: str | None = None
    taller_estado: str | None = None
    codigo: str
    nombre: str
    descripcion: str | None = None
    estado: str
    contacto_email: str | None = None
    contacto_telefono: str | None = None
    usuarios: int = 0
    talleres: int = 0
    tecnicos: int = 0
    incidentes: int = 0
    incidentes_atendidos: int = 0
    servicios_completados: int = 0
    administrador_principal: str | None = None
    creado_en: str | None = None
    ultima_actividad: str | None = None


class TenantAsignarUsuarioIn(BaseModel):
    usuario_id: str


class TenantAsignarTallerIn(BaseModel):
    taller_id: str


class TenantOpcionOut(BaseModel):
    id: str
    label: str
    tenant_id: str | None = None
