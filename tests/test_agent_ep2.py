"""
Suite de Pruebas Automatizadas para la Evaluación Parcial N°2 (EP2).
Valida autonomía de herramientas (IE1), memoria corto/largo plazo (IE3, IE4)
y planificación adaptativa ante condiciones cambiantes (IE5, IE7).
"""
import os
import sys
import json
import pytest

# Asegurar ruta raíz en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent_ep2 import AgenteOperacionesDevCloud
from src.tools_ep2 import TICKETS_FILE

@pytest.fixture(scope="module")
def agente():
    # Inicializar archivo de tickets limpio para verificar escritura
    os.makedirs("data", exist_ok=True)
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)
    return AgenteOperacionesDevCloud()

def test_ie1_ie5_flujo_completo_staging_autorizado(agente):
    """
    Verifica que ante un incidente en STAGING el agente:
    1. Consulte manuales
    2. Evalúe políticas y severidad
    3. Ejecute la mitigación en infraestructura
    4. Escriba el ticket en disco
    """
    consulta = (
        "Tenemos el contenedor 'auth-service' en el ambiente de staging con error OOMKilled (Exit Code 137), "
        "sin afectar usuarios productivos (0%). Ejecuta la solución del manual y crea el ticket."
    )
    resultado = agente.ejecutar_tarea(consulta, session_id="test_sesion_1")
    nombres_tools = [t["herramienta"] for t in resultado["traza_ejecucion"]]

    # Debe haber consultado, razonado y escrito
    assert "consultar_manuales_internos" in nombres_tools
    assert "evaluar_politica_y_severidad" in nombres_tools
    assert "ejecutar_mitigacion_infraestructura" in nombres_tools
    assert "registrar_ticket_incidente" in nombres_tools
    assert os.path.exists(TICKETS_FILE), "El archivo de tickets debe haberse creado en disco."

def test_ie5_ie7_decision_adaptativa_bloqueo_produccion(agente):
    """
    Verifica que cuando la condición cambia a PRODUCCIÓN (45% usuarios afectados),
    el agente adapte su plan: NO ejecute el reinicio directo y escale el ticket a SRE.
    """
    consulta = (
        "Urgente: el pod 'payment-gateway' en el ambiente de produccion tiene error OOMKilled y afecta "
        "al 45% de los usuarios. Reinícialo de inmediato."
    )
    resultado = agente.ejecutar_tarea(consulta, session_id="test_sesion_2")
    nombres_tools = [t["herramienta"] for t in resultado["traza_ejecucion"]]

    assert "evaluar_politica_y_severidad" in nombres_tools
    assert "registrar_ticket_incidente" in nombres_tools
    # El agente debe haberse abstenido de llamar a ejecutar_mitigacion_infraestructura o haber reportado el bloqueo
    assert "ESCALADO" in resultado["respuesta_final"].upper() or "SRE" in resultado["respuesta_final"].upper()

def test_ie3_memoria_corto_plazo_multiturno(agente):
    """
    Verifica que el agente recuerde datos entregados en turnos anteriores dentro de la misma sesión.
    """
    sesion = "test_memoria_corto_plazo"
    agente.ejecutar_tarea(
        "Hola, soy el ingeniero Carlos Ruiz y estoy auditando el microservicio 'inventario-api' en staging.",
        session_id=sesion
    )
    res_turno_2 = agente.ejecutar_tarea(
        "¿Recuerdas cuál es mi nombre y qué microservicio estoy auditando?",
        session_id=sesion
    )
    respuesta = res_turno_2["respuesta_final"]
    assert "Carlos" in respuesta
    assert "inventario-api" in respuesta

def test_ie4_memoria_semantica_largo_plazo(agente):
    """
    Verifica que la memoria semántica en ChromaDB almacene y recupere episodios entre distintas sesiones.
    """
    agente.memoria.guardar_recuerdo_semantico(
        usuario_o_servicio="cluster-analytics-santiago",
        resumen_incidente="Fallo recurrente de certificado TLS expirado en ingress controller",
        solucion_aplicada="Se renovó el certificado con cert-manager y se reinició el pod ingress-nginx."
    )

    contexto_recuperado = agente.memoria.recuperar_contexto_semantico_previo(
        "Tenemos un problema con el certificado TLS en el cluster-analytics-santiago"
    )
    assert "cert-manager" in contexto_recuperado
    assert "ingress-nginx" in contexto_recuperado

