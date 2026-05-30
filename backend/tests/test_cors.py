from fastapi.testclient import TestClient

from app.main import create_app


def test_cors_allows_localhost_dev_ports():
    client = TestClient(create_app())

    response = client.options(
        "/api/analyze-pr",
        headers={
            "Origin": "http://127.0.0.1:61234",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:61234"


def test_cors_does_not_allow_non_localhost_origin():
    client = TestClient(create_app())

    response = client.options(
        "/api/analyze-pr",
        headers={
            "Origin": "http://example.com:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
