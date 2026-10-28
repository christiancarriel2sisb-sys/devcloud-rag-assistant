import sys
import os

# Add current dir to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.external_status import consultar_estado_proveedor_externo
from src.rag_pipeline import DevCloudRAGPipeline

def test_verification():
    print("Probando estado externo de Cloud SQL...")
    status = consultar_estado_proveedor_externo("Cloud SQL")
    print(status)
    assert "Cloud SQL" in status
    assert "DEGRADED_PERFORMANCE" in status

    print("Probando inicialización y consulta offline del Pipeline RAG...")
    pipeline = DevCloudRAGPipeline()
    resp = pipeline.consultar("¿Qué hacer ante un error OOMKilled?", servicio_externo="GKE")
    print("Respuesta:", resp)
    assert resp is not None
    print("¡Verificación exitosa!")

if __name__ == "__main__":
    test_verification()
