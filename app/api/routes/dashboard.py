"""
app/api/routes/dashboard.py
Dashboard administrativo con métricas del sistema.
Solo accesible por usuarios con rol "admin".
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db, engine
from app.core.security import get_current_user
from app.models.models import Incidente, Taller, Usuario, Pago
from datetime import datetime, timedelta

router = APIRouter()


def require_admin(current_user=Depends(get_current_user)):
    if current_user.rol != "admin":
        raise HTTPException(403, "Acceso restringido a administradores")
    return current_user


@router.get("/resumen")
def resumen_general(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """KPIs principales del sistema."""
    hoy = datetime.utcnow().date()
    inicio_mes = datetime(hoy.year, hoy.month, 1)

    total_incidentes = db.query(func.count(Incidente.id)).scalar()
    incidentes_hoy = db.query(func.count(Incidente.id)).filter(
        func.date(Incidente.creado_en) == hoy
    ).scalar()
    incidentes_mes = db.query(func.count(Incidente.id)).filter(
        Incidente.creado_en >= inicio_mes
    ).scalar()

    total_talleres = db.query(func.count(Taller.id)).scalar()
    talleres_activos = db.query(func.count(Taller.id)).filter(Taller.disponible == True).scalar()

    total_usuarios = db.query(func.count(Usuario.id)).filter(Usuario.rol == "conductor").scalar()

    ingresos_mes = db.query(func.sum(Pago.comision_plataforma)).filter(
        Pago.creado_en >= inicio_mes,
        Pago.estado == "completado"
    ).scalar() or 0

    ingresos_total = db.query(func.sum(Pago.comision_plataforma)).filter(
        Pago.estado == "completado"
    ).scalar() or 0

    return {
        "incidentes": {
            "total": total_incidentes,
            "hoy": incidentes_hoy,
            "este_mes": incidentes_mes,
        },
        "talleres": {
            "total": total_talleres,
            "activos": talleres_activos,
        },
        "conductores": total_usuarios,
        "ingresos": {
            "este_mes_bs": round(float(ingresos_mes), 2),
            "total_bs": round(float(ingresos_total), 2),
        }
    }


@router.get("/incidentes-por-tipo")
def incidentes_por_tipo(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Distribución de incidentes por tipo — para gráfica de torta."""
    resultados = db.query(
        Incidente.tipo,
        func.count(Incidente.id).label("cantidad")
    ).group_by(Incidente.tipo).all()

    return [{"tipo": r.tipo, "cantidad": r.cantidad} for r in resultados]


@router.get("/incidentes-por-dia")
def incidentes_por_dia(dias: int = 30, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Incidentes por día en los últimos N días — para gráfica de línea."""
    desde = datetime.utcnow() - timedelta(days=dias)
    resultados = db.query(
        func.date(Incidente.creado_en).label("fecha"),
        func.count(Incidente.id).label("cantidad")
    ).filter(
        Incidente.creado_en >= desde
    ).group_by(
        func.date(Incidente.creado_en)
    ).order_by("fecha").all()

    return [{"fecha": str(r.fecha), "cantidad": r.cantidad} for r in resultados]


@router.get("/top-talleres")
def top_talleres(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Top 10 talleres por número de servicios y calificación."""
    resultados = db.query(
        Taller.id,
        Taller.nombre,
        Taller.calificacion,
        func.count(Incidente.id).label("servicios")
    ).outerjoin(
        Incidente, Incidente.taller_id == Taller.id
    ).group_by(
        Taller.id, Taller.nombre, Taller.calificacion
    ).order_by(
        func.count(Incidente.id).desc()
    ).limit(10).all()

    return [{
        "taller_id": str(r.id),
        "nombre": r.nombre,
        "calificacion": r.calificacion,
        "servicios_totales": r.servicios
    } for r in resultados]


@router.get("/incidentes-por-zona")
def incidentes_por_zona(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Coordenadas de todos los incidentes para mapa de calor.
    Retorna lat/lng + tipo + prioridad.
    """
    incidentes = db.query(
        Incidente.lat_incidente,
        Incidente.lng_incidente,
        Incidente.tipo,
        Incidente.prioridad
    ).filter(
        Incidente.lat_incidente != None,
        Incidente.lng_incidente != None
    ).all()

    return [{
        "lat": i.lat_incidente,
        "lng": i.lng_incidente,
        "tipo": i.tipo,
        "prioridad": i.prioridad
    } for i in incidentes]


@router.get("/ingresos-por-mes")
def ingresos_por_mes(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Ingresos (comisiones) agrupados por mes — últimos 12 meses."""
    if engine.dialect.name == "sqlite":
        mes_expr = func.strftime("%Y-%m", Pago.pagado_en)
    else:
        mes_expr = func.to_char(Pago.pagado_en, 'YYYY-MM')

    resultados = db.query(
        mes_expr.label("mes"),
        func.sum(Pago.comision_plataforma).label("total")
    ).filter(
        Pago.estado == "completado",
        Pago.pagado_en >= datetime.utcnow() - timedelta(days=365)
    ).group_by("mes").order_by("mes").all()

    return [{"mes": r.mes, "total_bs": round(float(r.total), 2)} for r in resultados]
