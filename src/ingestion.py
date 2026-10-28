"""
Modulo de Ingesta y Vectorizacion con Gemini.
Carga documentos tecnicos internos en texto plano, aplica fragmentacion semantica
con RecursiveCharacterTextSplitter y genera persistencia local en ChromaDB.
"""
import os
import sys
import glob

# Asegurar que el directorio raíz esté en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from src.config import GEMINI_API_KEY, CHROMA_PERSIST_DIRECTORY

def construir_base_vectorial():
    # 1. Cargar documentos internos desde data_tets/internal y data/internal
    rutas = [
        os.path.join("data_tets", "internal", "*.txt"),
        os.path.join("data", "internal", "*.txt")
    ]
    archivos_encontrados = {}
    for r in rutas:
        for f in glob.glob(r):
            nombre = os.path.basename(f)
            if nombre not in archivos_encontrados:
                archivos_encontrados[nombre] = f
                
    archivos = list(archivos_encontrados.values())
    
    if not archivos:
        raise FileNotFoundError(
            "No se encontraron archivos .txt en las rutas especificadas. "
            "Asegurese de haber creado los archivos SOP_TI_Incidentes.txt y SEC_Politica_Accesos.txt."
        )
    
    todos_los_documentos = []
    for archivo in archivos:
        cargador = TextLoader(archivo, encoding="utf-8")
        todos_los_documentos.extend(cargador.load())
    
    print(f"[+] Documentos base cargados: {len(todos_los_documentos)}")

    # 2. Chunking semantico (chunk_size=500 caracteres, chunk_overlap=80 caracteres)
    divisor = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
        separators=["\n\n", "\n", "- ", ". ", " "]
    )
    fragmentos = divisor.split_documents(todos_los_documentos)
    print(f"[+] Total de fragmentos (chunks) generados: {len(fragmentos)}")

    # 3. Calculo de Embeddings e indexacion vectorial persistente
    modelo_embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GEMINI_API_KEY
    )

    vector_db = Chroma.from_documents(
        documents=fragmentos,
        embedding=modelo_embeddings,
        persist_directory=CHROMA_PERSIST_DIRECTORY
    )
    
    print(f"[OK] Base vectorial indexada exitosamente en el directorio: {CHROMA_PERSIST_DIRECTORY}")
    return vector_db

if __name__ == "__main__":
    construir_base_vectorial()
