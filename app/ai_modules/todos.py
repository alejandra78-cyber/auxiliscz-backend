"""
ai_modules/clasificador.py
Clasificación multimodal de incidentes vehiculares.
"""
import openai
import json
import logging
import os
from typing import List, Dict

logger = logging.getLogger(__name__)

CATEGORIAS = ["bateria", "llanta", "motor", "choque", "llave", "otro", "incierto"]

PRIORIDADES = {
    "choque": 1,     # Alta
    "motor": 1,
    "bateria": 2,    # Media
    "llave": 2,
    "llanta": 2,
    "otro": 3,       # Baja
    "incierto": 2,
}


async def clasificar_incidente(evidencias: List[Dict]) -> Dict:
    """
    Recibe lista de evidencias (texto, audio transcrito, datos de imagen)
    y retorna tipo, prioridad y confianza del incidente.
    """
    texto_consolidado = _consolidar_evidencias(evidencias)

    prompt = f"""
Eres un sistema de clasificación de emergencias vehiculares.
Analiza la siguiente información de un conductor en apuros y clasifica el incidente.

Evidencias recibidas:
{texto_consolidado}

Responde ÚNICAMENTE en JSON con este formato:
{{
  "tipo": "<una de: bateria | llanta | motor | choque | llave | otro | incierto>",
  "prioridad": <1=alta | 2=media | 3=baja>,
  "confianza": <0.0-1.0>,
  "razon": "<explicación breve>"
}}

Si la información es insuficiente o contradictoria, usa tipo "incierto".
"""

    response = await _client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=200
    )

    try:
        content = response.choices[0].message.content or ""
        resultado = _parse_json_safely(content)
    except json.JSONDecodeError:
        resultado = {"tipo": "incierto", "prioridad": 2, "confianza": 0.5, "razon": "Error de parsing"}
        logger.warning("IA clasificación devolvió JSON inválido")

    # Validar categoría
    if resultado.get("tipo") not in CATEGORIAS:
        resultado["tipo"] = "incierto"

    # Prioridad por defecto según tipo
    if "prioridad" not in resultado:
        resultado["prioridad"] = PRIORIDADES.get(resultado["tipo"], 2)

    return resultado


def _consolidar_evidencias(evidencias: List[Dict]) -> str:
    partes = []
    for ev in evidencias:
        if ev["tipo"] == "audio":
            partes.append(f"[AUDIO TRANSCRITO]: {ev.get('texto', '')}")
        elif ev["tipo"] == "imagen":
            datos = ev.get("datos", {})
            partes.append(f"[ANÁLISIS DE IMAGEN]: {json.dumps(datos, ensure_ascii=False)}")
        elif ev["tipo"] == "texto":
            partes.append(f"[DESCRIPCIÓN DEL USUARIO]: {ev.get('texto', '')}")
    return "\n".join(partes) if partes else "Sin evidencias disponibles."


# ───────────────────────────────────────────────────────────────
"""
ai_modules/audio.py
Transcripción de audio usando OpenAI Whisper.
"""
import openai
import tempfile


async def transcribir_audio(contenido: bytes, idioma: str = "es") -> str:
    """
    Convierte audio (bytes) a texto usando Whisper.
    """
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(contenido)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            transcripcion = await _client().audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language=idioma
            )
        return transcripcion.text
    finally:
        os.unlink(tmp_path)


# ───────────────────────────────────────────────────────────────
"""
ai_modules/vision.py
Análisis básico de imágenes vehiculares con GPT-4o Vision.
"""
import openai
import base64


async def analizar_imagen(contenido: bytes) -> dict:
    """
    Analiza una foto del vehículo e identifica daños visibles.
    """
    imagen_b64 = base64.b64encode(contenido).decode("utf-8")

    prompt = """Analiza esta imagen de un vehículo en emergencia.
Identifica daños o problemas visibles. Responde en JSON:
{
  "problema_detectado": "<descripción breve>",
  "categoria_probable": "<bateria|llanta|motor|choque|llave|otro>",
  "nivel_danio": "<leve|moderado|grave>",
  "confianza": <0.0-1.0>
}"""

    response = await _client().chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{imagen_b64}"}}
            ]
        }],
        max_tokens=300
    )

    import json
    try:
        content = response.choices[0].message.content or ""
        return _parse_json_safely(content)
    except Exception:
        logger.exception("IA visión: no se pudo parsear/analisar imagen")
        return {"problema_detectado": "No se pudo analizar", "confianza": 0.0}


# ───────────────────────────────────────────────────────────────
"""
ai_modules/resumen.py
Generación de ficha estructurada del incidente.
"""
import openai
import json


async def generar_resumen(clasificacion: dict, evidencias: list) -> str:
    """
    Genera una ficha estructurada legible del incidente para el taller.
    """
    prompt = f"""
Eres un asistente que genera fichas técnicas de emergencias vehiculares para talleres mecánicos.

Clasificación del incidente:
{json.dumps(clasificacion, ensure_ascii=False, indent=2)}

Evidencias disponibles:
{json.dumps(evidencias, ensure_ascii=False, indent=2)}

Genera una ficha estructurada en español con:
- Resumen del problema (2-3 oraciones)
- Tipo de problema detectado
- Nivel de prioridad y justificación
- Herramientas o servicios recomendados
- Notas adicionales para el técnico

Sé conciso y técnico.
"""

    response = await _client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400
    )

    return response.choices[0].message.content


def _client() -> openai.AsyncOpenAI:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY no está configurada")
    return openai.AsyncOpenAI(api_key=key)


def _parse_json_safely(raw: str) -> dict:
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:].strip()
    return json.loads(txt)
