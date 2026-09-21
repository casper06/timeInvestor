import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database.connection import init_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_thesis_crud_workflow():
    # 1. Create a thesis
    create_payload = {
        "title": "Tesis de Infraestructura IA y Energía",
        "prompt": "Demanda eléctrica por datacenters de IA",
        "summary": "Tesis centrada en el cuello de botella de energía",
        "status": "Activa",
        "tickers": [
            {
                "symbol": "NVDA",
                "name": "NVIDIA",
                "sector": "Semiconductors",
                "weight": 0.5,
                "thesis_role": "Compute"
            },
            {
                "symbol": "CEG",
                "name": "Constellation Energy",
                "sector": "Utilities",
                "weight": 0.5,
                "thesis_role": "Nuclear Power"
            }
        ],
        "macro_series": [
            {
                "series_id": "IPG2211A2N",
                "name": "Electric Power",
                "category": "Energy",
                "expected_correlation": "Positive"
            }
        ],
        "rationales": {"NVDA": "Cómputo", "CEG": "Energía"}
    }

    resp = client.post("/api/theses", json=create_payload)
    assert resp.status_code == 200
    data = resp.json()
    thesis_id = data["id"]
    assert data["title"] == create_payload["title"]
    assert len(data["tickers"]) == 2

    # 2. List theses
    list_resp = client.get("/api/theses")
    assert list_resp.status_code == 200
    theses = list_resp.json()
    assert any(t["id"] == thesis_id for t in theses)

    # 3. Add a snapshot
    snap_payload = {
        "series_id": "NVDA",
        "cutoff_date": "2024-06-01",
        "horizon": 30,
        "confidence": 0.95,
        "timestamps": ["2024-06-02", "2024-06-03"],
        "projected_values": [125.0, 126.5],
        "lower_bound": [120.0, 121.0],
        "upper_bound": [130.0, 132.0],
        "model_name": "timesfm"
    }
    snap_resp = client.post(f"/api/theses/{thesis_id}/snapshots", json=snap_payload)
    assert snap_resp.status_code == 200
    snap_data = snap_resp.json()
    assert snap_data["series_id"] == "NVDA"

    # 4. Add a research note
    note_payload = {
        "note_text": "Revisar acuerdos PPA anunciados en el trimestre.",
        "author": "Analista Senior"
    }
    note_resp = client.post(f"/api/theses/{thesis_id}/notes", json=note_payload)
    assert note_resp.status_code == 200
    note_data = note_resp.json()
    assert note_data["author"] == "Analista Senior"

    # 5. Retrieve full detail
    detail_resp = client.get(f"/api/theses/{thesis_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert len(detail["snapshots"]) >= 1
    assert len(detail["notes"]) >= 1

    # 6. Update status to "Bajo estrés"
    update_resp = client.put(f"/api/theses/{thesis_id}", json={"status": "Bajo estrés"})
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "Bajo estrés"

    # 7. Delete thesis
    del_resp = client.delete(f"/api/theses/{thesis_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"
