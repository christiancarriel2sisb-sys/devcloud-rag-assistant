"""
Módulo de Gestión de Memoria Híbrida para el Agente (EP2 - Indicadores IE3 e IE4).
1. Corto Plazo: Ventana de mensajes por sesión (continuidad de flujo).
2. Largo Plazo: Base vectorial episódica en ChromaDB (recuperación semántica histórica).
"""
import os
import sys
from datetime import datetime
from typing import Dict, List

# Asegurar ruta raíz en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from src.config import GEMINI_API_KEY

LONG_TERM_MEMORY_DIR = os.path.join("data", "long_term_memory_db")

class GestorMemoriaAgente:
    def __init__(self):
        # 1. Memoria de Corto Plazo (Diccionario de sesiones en RAM para continuidad de tareas)
        self.sesiones_corto_plazo: Dict[str, List[BaseMessage]] = {}

        # 2. Memoria Semántica de Largo Plazo (Vector Store persistente en ChromaDB)
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=GEMINI_API_KEY
        )
        self.memoria_largo_plazo = Chroma(
            collection_name="episodios_historicos_agentes",
            embedding_function=self.embeddings,
            persist_directory=LONG_TERM_MEMORY_DIR
        )

    # --- MÉTODOS DE CORTO PLAZO (IE3) ---
    def obtener_historial_sesion(self, session_id: str) -> List[BaseMessage]:
        """Recupera los mensajes previos de la conversación actual."""
        return self.sesiones_corto_plazo.get(session_id, [])

    def registrar_turno_corto_plazo(self, session_id: str, consulta_usuario: str, respuesta_agente: str):
        """Agrega la interacción actual al buffer de la sesión manteniendo continuidad."""
        if session_id not in self.sesiones_corto_plazo:
            self.sesiones_corto_plazo[session_id] = []
        self.sesiones_corto_plazo[session_id].append(HumanMessage(content=consulta_usuario))
        self.sesiones_corto_plazo[session_id].append(AIMessage(content=respuesta_agente))

    def limpiar_sesion(self, session_id: str):
        if session_id in self.sesiones_corto_plazo:
            del self.sesiones_corto_plazo[session_id]

    # --- MÉTODOS DE LARGO PLAZO SEMÁNTICO (IE4) ---
    def guardar_recuerdo_semantico(self, usuario_o_servicio: str, resumen_incidente: str, solucion_aplicada: str):
        """
        Almacena un evento o resolución importante en la base vectorial de largo plazo
        para que pueda ser recuperado en sesiones futuras.
        """
        contenido = (
            f"Servicio/Contexto: {usuario_o_servicio} | "
            f"Incidente: {resumen_incidente} | "
            f"Resolución Histórica: {solucion_aplicada}"
        )
        doc = Document(
            page_content=contenido,
            metadata={
                "entidad": usuario_o_servicio,
                "fecha": datetime.now().isoformat()
            }
        )
        self.memoria_largo_plazo.add_documents([doc])

    def recuperar_contexto_semantico_previo(self, consulta_actual: str, k: int = 2) -> str:
        """
        Busca por similitud semántica si existen casos históricos previos en la memoria de largo plazo
        que ayuden al agente a mantener continuidad entre distintas sesiones.
        """
        try:
            resultados = self.memoria_largo_plazo.similarity_search(consulta_actual, k=k)
            if not resultados:
                return "Sin antecedentes históricos previos en la memoria de largo plazo."
            return "\n".join([f"- [Recuerdo Episódico]: {doc.page_content}" for doc in resultados])
        except Exception:
            return "Sin antecedentes históricos previos en la memoria de largo plazo."

