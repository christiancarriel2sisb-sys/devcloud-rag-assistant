"""
Módulo de Herramientas del Agente (EP2 - Indicador IE1).
Integra herramientas de:
1. Consulta (RAG interno + Estado de API externa)
2. Razonamiento y Reglas de Negocio (Evaluador determinista de impacto y políticas)
3. Escritura y Acción (Creación/actualización de tickets en JSON y reinicio controlado)
"""
import os
import sys
import json
from datetime import datetime
from typing import Optional

# Asegurar ruta raíz en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from src.config import GEMINI_API_KEY, CHROMA_PERSIST_DIRECTORY
from src.external_status import consultar_estado_proveedor_externo

TICKETS_FILE = os.path.join("data", "tickets_db.json")

# =====================================================================
# 1. HERRAMIENTAS DE CONSULTA (READ)
# =====================================================================

class ConsultaKBInput(BaseModel):
    query: str = Field(description="Consulta técnica sobre errores, comandos, arquitectura o políticas IAM.")

@tool("consultar_manuales_internos", args_schema=ConsultaKBInput)
def consultar_manuales_internos(query: str) -> str:
    """
    Herramienta de CONSULTA. Busca en la base vectorial (RAG) los protocolos oficiales (SOP)
    y políticas de seguridad internas de DevCloud Solutions SpA. Úsala siempre para saber cómo proceder.
    """
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GEMINI_API_KEY
    )
    vector_db = Chroma(
        persist_directory=CHROMA_PERSIST_DIRECTORY,
        embedding_function=embeddings
    )
    docs = vector_db.similarity_search(query, k=3)
    if not docs:
        return "No se encontraron manuales internos relevantes para esta consulta."
    return "\n\n".join([f"[Fragmento Oficial]: {d.page_content}" for d in docs])


class ConsultaExternaInput(BaseModel):
    servicio: Optional[str] = Field(
        default=None,
        description="Nombre del servicio cloud a consultar (ej. 'Cloud SQL', 'Kubernetes', 'Compute Engine')."
    )

@tool("verificar_estado_cloud_externo", args_schema=ConsultaExternaInput)
def verificar_estado_cloud_externo(servicio: Optional[str] = None) -> str:
    """
    Herramienta de CONSULTA. Verifica en tiempo real si el proveedor Cloud externo (Google Cloud)
    presenta caídas o degradación regional antes de tomar decisiones locales.
    """
    return consultar_estado_proveedor_externo(servicio)


# =====================================================================
# 2. HERRAMIENTA DE RAZONAMIENTO Y CÁLCULO DE NEGOCIO (REASONING)
# =====================================================================

class EvaluarImpactoInput(BaseModel):
    ambiente: str = Field(description="Ambiente afectado: 'produccion', 'staging' o 'desarrollo'.")
    porcentaje_usuarios_afectados: int = Field(description="Porcentaje estimado de usuarios afectados (0 a 100).")
    accion_propuesta: str = Field(description="Acción técnica que se desea realizar (ej. 'reiniciar_pod', 'abrir_puerto', 'elevar_permisos').")

@tool("evaluar_politica_y_severidad", args_schema=EvaluarImpactoInput)
def evaluar_politica_y_severidad(ambiente: str, porcentaje_usuarios_afectados: int, accion_propuesta: str) -> str:
    """
    Herramienta de RAZONAMIENTO LÓGICO. Evalúa las reglas de negocio deterministas, calcula el nivel
    de severidad (P1, P2, P3) y dictamina si una acción está autorizada o bloqueada por seguridad.
    Obligatorio ejecutarla antes de cualquier herramienta de escritura o acción en infraestructura.
    """
    amb = ambiente.lower().strip()
    accion = accion_propuesta.lower().strip()

    # Cálculo determinista de severidad
    if amb == "produccion" and porcentaje_usuarios_afectados >= 20:
        severidad = "P1 (Crítica - SLA 15 min)"
    elif amb == "produccion" or porcentaje_usuarios_afectados >= 5:
        severidad = "P2 (Alta - SLA 1 hora)"
    else:
        severidad = "P3 (Media/Baja - SLA 8 horas)"

    # Reglas de bloqueo de seguridad adaptativas
    autorizado_ejecutar = True
    motivo_decision = "Acción permitida bajo parámetros estándar."

    if "puerto" in accion or "ssh" in accion or "0.0.0.0" in accion:
        autorizado_ejecutar = False
        motivo_decision = "BLOQUEO DE SEGURIDAD [SEC-POL-CLOUD-V2]: Prohibido abrir puertos de gestión a internet público."
    elif amb == "produccion" and ("reiniciar" in accion or "eliminar" in accion or "kill" in accion):
        autorizado_ejecutar = False
        motivo_decision = (
            "BLOQUEO OPERACIONAL [SOP-TI-2026-V1]: En ambiente de PRODUCCIÓN está prohibido reiniciar pods o "
            "servicios directamente sin autorización del Lead SRE y volcado previo de memoria."
        )

    resultado = {
        "severidad_calculada": severidad,
        "ambiente_evaluado": amb,
        "accion_solicitada": accion_propuesta,
        "autorizado_ejecucion_automatica": autorizado_ejecutar,
        "dictamen_regla_negocio": motivo_decision,
        "instruccion_para_agente": (
            "Proceder con la acción y registrar ticket." if autorizado_ejecutar
            else "NO ejecutar el cambio en infraestructura. Crear inmediatamente un ticket en estado 'ESCALADO_A_SRE' explicando el bloqueo."
        )
    }
    return json.dumps(resultado, ensure_ascii=False, indent=2)


# =====================================================================
# 3. HERRAMIENTAS DE ESCRITURA Y ACCIÓN (WRITE)
# =====================================================================

class CrearTicketInput(BaseModel):
    titulo: str = Field(description="Título técnico resumido del incidente.")
    severidad: str = Field(description="Nivel de severidad calculado (P1, P2, P3).")
    estado: str = Field(description="Estado inicial: 'ABIERTO', 'RESUELTO_AUTOMATICO' o 'ESCALADO_A_SRE'.")
    diagnostico_y_acciones: str = Field(description="Detalle técnico del diagnóstico, fuentes citadas y acciones tomadas.")

@tool("registrar_ticket_incidente", args_schema=CrearTicketInput)
def registrar_ticket_incidente(titulo: str, severidad: str, estado: str, diagnostico_y_acciones: str) -> str:
    """
    Herramienta de ESCRITURA. Crea y persiste un ticket oficial de soporte en la base de datos de
    la organización (data/tickets_db.json) para dejar trazabilidad auditable del flujo de trabajo.
    """
    os.makedirs("data", exist_ok=True)
    tickets = []
    if os.path.exists(TICKETS_FILE):
        try:
            with open(TICKETS_FILE, "r", encoding="utf-8") as f:
                tickets = json.load(f)
        except json.JSONDecodeError:
            tickets = []

    nuevo_ticket = {
        "ticket_id": f"INC-{1000 + len(tickets) + 1}",
        "fecha_creacion": datetime.now().isoformat(),
        "titulo": titulo,
        "severidad": severidad,
        "estado": estado,
        "diagnostico_y_acciones": diagnostico_y_acciones
    }
    tickets.append(nuevo_ticket)

    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)

    return json.dumps({
        "confirmacion": "Ticket registrado exitosamente en base de datos.",
        "ticket": nuevo_ticket
    }, ensure_ascii=False, indent=2)


class MitigacionInfraInput(BaseModel):
    nombre_recurso: str = Field(description="Nombre del pod, contenedor o servicio donde aplicar la acción.")
    ambiente: str = Field(description="Ambiente objetivo: 'staging' o 'desarrollo' (Prohibido en 'produccion').")
    comando_accion: str = Field(description="Acción autorizada a aplicar (ej. 'incrementar_memoria_25%', 'reiniciar_pod').")

@tool("ejecutar_mitigacion_infraestructura", args_schema=MitigacionInfraInput)
def ejecutar_mitigacion_infraestructura(nombre_recurso: str, ambiente: str, comando_accion: str) -> str:
    """
    Herramienta de ESCRITURA/ACCIÓN. Ejecuta un cambio de mitigación sobre un recurso de infraestructura.
    SOLO puede invocarse si 'evaluar_politica_y_severidad' devolvió autorizado_ejecucion_automatica = true.
    """
    if ambiente.lower().strip() == "produccion":
        return json.dumps({
            "exito": False,
            "error": "OPERACIÓN RECHAZADA POR EL CLUSTER: No se permiten ejecuciones automáticas directas en producción sin token Break-Glass."
        }, ensure_ascii=False)

    return json.dumps({
        "exito": True,
        "recurso_modificado": nombre_recurso,
        "ambiente": ambiente,
        "accion_aplicada": comando_accion,
        "timestamp": datetime.now().isoformat(),
        "mensaje": f"Se aplicó '{comando_accion}' sobre '{nombre_recurso}' en '{ambiente}' sin errores."
    }, ensure_ascii=False, indent=2)


def obtener_herramientas_ep2():
    """Retorna la lista completa de herramientas para el agente."""
    return [
        consultar_manuales_internos,
        verificar_estado_cloud_externo,
        evaluar_politica_y_severidad,
        registrar_ticket_incidente,
        ejecutar_mitigacion_infraestructura
    ]

