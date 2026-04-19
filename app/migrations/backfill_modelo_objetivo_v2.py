from app.core.database import SessionLocal
from app.models.models import Cliente, Emergencia, Historial, HistorialEstado, Incidente, Solicitud


def backfill():
    db = SessionLocal()
    try:
        incidentes = db.query(Incidente).all()
        for incidente in incidentes:
            cliente = db.query(Cliente).filter(Cliente.usuario_id == incidente.usuario_id).first()
            if not cliente:
                cliente = Cliente(usuario_id=incidente.usuario_id)
                db.add(cliente)
                db.flush()

            solicitud = db.query(Solicitud).filter(Solicitud.incidente_id == incidente.id).first()
            if not solicitud:
                solicitud = Solicitud(
                    incidente_id=incidente.id,
                    cliente_id=cliente.id,
                    vehiculo_id=incidente.vehiculo_id,
                    estado=str(incidente.estado),
                    prioridad=incidente.prioridad or 2,
                )
                db.add(solicitud)
                db.flush()

            if not solicitud.emergencia:
                db.add(
                    Emergencia(
                        solicitud_id=solicitud.id,
                        tipo=str(incidente.tipo) if incidente.tipo else 'otro',
                        descripcion=incidente.descripcion,
                        estado=str(incidente.estado),
                        prioridad=incidente.prioridad or 2,
                    )
                )

            historial_actual = db.query(Historial).filter(Historial.solicitud_id == solicitud.id).count()
            if historial_actual == 0:
                rows = db.query(HistorialEstado).filter(HistorialEstado.incidente_id == incidente.id).all()
                for h in rows:
                    db.add(
                        Historial(
                            solicitud_id=solicitud.id,
                            estado_anterior=h.estado_anterior,
                            estado_nuevo=h.estado_nuevo,
                            comentario='Migrado desde historial_estados',
                            creado_en=h.cambiado_en,
                        )
                    )
        db.commit()
        print('Backfill completado correctamente')
    finally:
        db.close()


if __name__ == '__main__':
    backfill()
