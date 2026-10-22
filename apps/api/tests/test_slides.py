import io
import uuid

from pypdf import PdfWriter


def pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=640, height=480)
    writer.add_blank_page(width=640, height=480)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def create(client):
    return client.post(
        "/v1/meetings",
        json={
            "title": "Slides class",
            "consent_confirmed": True,
            "consent_policy_version": "v1",
        },
    ).json()["meeting"]["id"]


def test_optional_slides_and_references(api_client):
    client, identity = api_client
    meeting = create(client)
    base = f"/v1/meetings/{meeting}/slides"
    assert client.get(base).json() is None
    result = client.post(base, files={"file": ("lecture.pdf", pdf_bytes(), "application/pdf")})
    assert result.status_code == 201
    assert result.json()["page_count"] == 2
    assert client.post(base, files={"file": ("other.pdf", pdf_bytes())}).status_code == 409
    result = client.patch(base + "/references", json={"topic": "Cells", "pages": [2, 1, 2]})
    assert result.json()["references"] == {"Cells": [1, 2]}
    assert (
        client.patch(base + "/references", json={"topic": "Cells", "pages": [3]}).status_code == 422
    )
    response = client.get(base + "/pdf")
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    owner = identity["owner"]
    identity["owner"] = uuid.uuid4()
    assert client.get(base + "/pdf").status_code == 404
    assert client.delete(base).status_code == 404
    identity["owner"] = owner
    assert client.delete(base).status_code == 204
    assert client.get(base).json() is None
    assert client.get(base + "/pdf").status_code == 404
    assert client.get(f"/v1/meetings/{meeting}").status_code == 200


def test_invalid_slides(api_client):
    client, _ = api_client
    base = f"/v1/meetings/{create(client)}/slides"
    assert client.post(base, files={"file": ("fake.pdf", b"not a pdf")}).status_code == 422
    assert client.get(base).json() is None
    writer = PdfWriter()
    writer.add_blank_page(width=640, height=480)
    writer.encrypt("secret")
    output = io.BytesIO()
    writer.write(output)
    assert client.post(base, files={"file": ("locked.pdf", output.getvalue())}).status_code == 422
    assert (
        client.post(base, files={"file": ("big.pdf", b"x" * (20 * 1024 * 1024 + 1))}).status_code
        == 413
    )
