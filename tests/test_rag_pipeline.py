"""
Suite de pruebas automatizadas para validar la recuperacion, citacion de fuentes
y deteccion de incidentes externos por parte del pipeline RAG.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from src.rag_pipeline import AsistenteDevCloudRAG

@pytest.fixture(scope="module")
def asistente():
    return AsistenteDevCloudRAG()

def test_recuperacion_y_citacion_de_documentos(asistente):
    """Verifica que el agente consulte el contexto interno y cite el codigo SOP."""
    consulta = "Tengo un pod arrojando error OOMKilled con exit code 137. ¿Como debo proceder?"
    respuesta = asistente.responder_incidencia(consulta)
    
    assert len(respuesta) > 100
    assert "SOP-TI-2026-V1" in respuesta or "137" in respuesta
    assert "kubectl logs" in respuesta or "Prometheus" in respuesta or "recursos" in respuesta.lower()

def test_alerta_de_incidente_externo(asistente):
    """Verifica que el agente identifique la degradacion en la API externa de Cloud SQL."""
    consulta = "La base de datos PostgreSQL presenta elevada latencia en southamerica-west1."
    respuesta = asistente.responder_incidencia(consulta)
    
    assert "Cloud SQL" in respuesta
    assert ("DEGRADED" in respuesta or "degradacion" in respuesta.lower() or "mitigando" in respuesta.lower() or "latencia" in respuesta.lower())

def test_politica_seguridad_iam(asistente):
    """Verifica el cumplimiento de politicas de accesos y ventanas break-glass."""
    consulta = "¿Puedo descargar claves JSON permanentes de Service Accounts para desarrollo local?"
    respuesta = asistente.responder_incidencia(consulta)
    
    assert "SEC-POL-CLOUD-V2" in respuesta or "prohibid" in respuesta.lower()
    assert "Workload Identity" in respuesta or "menor privilegio" in respuesta.lower()
