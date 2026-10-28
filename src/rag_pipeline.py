"""
Pipeline principal de Retrieval-Augmented Generation (RAG) con Gemini.
Orquesta la busqueda de similitud en ChromaDB, la consulta al endpoint externo y
la sintesis contextual mediante el LLM.
"""
import os
import sys

# Asegurar que el directorio raíz esté en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from src.config import GEMINI_API_KEY, CHROMA_PERSIST_DIRECTORY
from src.external_status import consultar_estado_proveedor_externo
from src.prompts import PROMPT_RAG

class AsistenteDevCloudRAG:
    def __init__(self):
        # 1. Cargar embeddings y base vectorial persistida
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=GEMINI_API_KEY
        )
        self.vector_db = Chroma(
            persist_directory=CHROMA_PERSIST_DIRECTORY,
            embedding_function=self.embeddings
        )
        # Recuperacion de los top-k fragmentos mas relevantes
        self.retriever = self.vector_db.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 3}
        )
        
        # 2. Configurar el LLM con baja temperatura para determinismo tecnico
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1,
            google_api_key=GEMINI_API_KEY
        )
        
        # 3. Cadena LCEL (LangChain Expression Language)
        self.chain = PROMPT_RAG | self.llm

    def responder_incidencia(self, consulta: str) -> str:
        # Paso 1: Recuperacion semantica de documentos internos
        docs_relevantes = self.retriever.invoke(consulta)
        contexto_interno = "\n\n".join([doc.page_content for doc in docs_relevantes])

        # Paso 2: Deteccion de contexto y consulta a la API de estado externa
        consulta_lower = consulta.lower()
        servicio_filtro = None
        if any(palabra in consulta_lower for palabra in ["sql", "base de datos", "postgres", "latencia"]):
            servicio_filtro = "Cloud SQL"
        elif any(palabra in consulta_lower for palabra in ["pod", "cluster", "kubernetes", "gke", "oomkilled"]):
            servicio_filtro = "Kubernetes"
            
        estado_externo = consultar_estado_proveedor_externo(servicio_filtro)

        # Paso 3: Generacion de respuesta aumentada
        respuesta = self.chain.invoke({
            "contexto_interno": contexto_interno,
            "estado_externo": estado_externo,
            "consulta_usuario": consulta
        })

        return respuesta.content

if __name__ == "__main__":
    print("[*] Conectando con Asistente DevCloud RAG...")
    asistente = AsistenteDevCloudRAG()
    
    caso_prueba = (
        "Se reporta lentitud critica en la base de datos PostgreSQL de produccion y "
        "los microservicios arrojaron fallas de conexion. ¿Cual es el procedimiento segun los manuales?"
    )
    print(f"\n[Consulta ingresada]:\n{caso_prueba}\n")
    salida = asistente.responder_incidencia(caso_prueba)
    print(f"[Respuesta generada por el pipeline]:\n{salida}")
