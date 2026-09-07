"""Pruebas funcionales de los endpoints de la API FastAPI.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class TestHealthAndProviders:

    def test_health_endpoint_returns_ok(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "platform" in data

    def test_providers_endpoint_returns_catalog(self):
        response = client.get("/api/config/providers")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert len(data["providers"]) >= 3
        provider_ids = [p["id"] for p in data["providers"]]
        assert "dmr" in provider_ids or "ollama" in str(provider_ids).lower()
        assert "vertex" in provider_ids

    def test_theme_tokens_returns_css_variables(self):
        response = client.get("/api/theme/tokens")
        assert response.status_code == 200
        data = response.json()
        assert "css_variables" in data
        css = data["css_variables"]
        assert "--color-primary" in css
        assert "--color-surface" in css
        assert "--color-state-cumple-bg" in css

    def test_postman_collection_endpoint_returns_valid_schema(self):
        response = client.get("/api/postman.json")
        assert response.status_code == 200
        data = response.json()
        assert "info" in data
        assert "schema" in data["info"]
        assert "collection.json" in data["info"]["schema"]
        assert "item" in data
        assert len(data["item"]) > 5

    def test_root_serves_spa_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Comparador de Normativas" in response.text


class TestDocumentEndpoints:

    def test_list_documents(self):
        response = client.get("/api/documents")
        assert response.status_code == 200
        data = response.json()
        assert "normativas" in data
        assert "manuales" in data

    def test_get_nonexistent_pdf_returns_404(self):
        response = client.get("/api/documents/normativa/archivo_inexistente_999.pdf/pdf")
        assert response.status_code == 404

    def test_get_existing_pdf_returns_application_pdf(self):
        # Tomar el primer documento disponible de la lista
        docs = client.get("/api/documents").json()
        if docs["normativas"]:
            primera_norma = docs["normativas"][0]["id"]
            response = client.get(f"/api/documents/normativa/{primera_norma}/pdf")
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
            assert response.headers.get("accept-ranges") == "bytes"


class TestIndexAndCompareGuards:

    def test_build_index_without_documents_returns_400(self):
        response = client.post("/api/index/build", json={"use_chunking": True})
        assert response.status_code == 400
        assert "No hay documentos" in response.json()["detail"]

    def test_search_without_index_returns_400(self):
        response = client.post("/api/index/search", json={"query": "test"})
        assert response.status_code == 400
        assert "no está construido" in response.json()["detail"]

    def test_start_compare_without_prep_returns_400(self):
        response = client.post("/api/compare/start", json={"dual_mode": True})
        assert response.status_code == 400

    def test_get_nonexistent_run_returns_404(self):
        response = client.get("/api/compare/runs/run_inexistente_12345")
        assert response.status_code == 404

    def test_export_invalid_format_returns_400(self):
        response = client.get("/api/compare/runs/cualquiera/export/formato_invalido")
        assert response.status_code == 400
