from fastapi.testclient import TestClient

from app import main
from app.http import UpstreamError
from app.services import live_layers as L

client = TestClient(main.app)


def test_nifc_status_mapping():
    assert L.nifc_status({"IncidentTypeCategory": "RX"}) == "prescribed"
    assert L.nifc_status({"IncidentTypeCategory": "WF", "FireOutDateTime": 1}) == "out"
    assert L.nifc_status({"IncidentTypeCategory": "WF", "ContainmentDateTime": 1}) == "held"
    assert L.nifc_status({"IncidentTypeCategory": "WF"}) == "uncontained"


def test_wind_payload_layout():
    import numpy as np
    lat = np.array([90.0, 89.0, 88.0])
    lon = np.array([0.0, 1.0])
    u = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.25]])
    w = L._wind_payload(u, -u, lat, lon, "2026-10-23T06:00", "2026-10-23T06:00")
    assert (w["ny"], w["nx"], w["dlat"], w["dlon"]) == (3, 2, -1.0, 1.0)
    assert w["u"] == [10, 20, 30, 40, 50, 62] and w["v"][0] == -10   # tenths of m/s, row-major from north


def test_decode_wind_rejects_garbage():
    import pytest
    with pytest.raises(UpstreamError):
        L.decode_wind(b"not a grib file")


def test_layer_endpoint_reports_upstream_failure(monkeypatch):
    def boom():
        raise UpstreamError("down")
    monkeypatch.setattr(L, "canada_incidents", boom)
    r = client.get("/api/layers/incidents?region=canada")
    assert r.status_code == 502 and "unavailable" in r.json()["detail"]


def test_incidents_region_validated():
    assert client.get("/api/layers/incidents?region=mars").status_code == 422
