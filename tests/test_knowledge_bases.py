from httpx import AsyncClient

from tests.helpers import create_authenticated_user

KNOWLEDGE_BASES_URL = "/api/v1/knowledge-bases"


async def create_knowledge_base(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Engineering Handbook",
    description: str | None = "Internal engineering knowledge",
) -> dict[str, object]:
    response = await client.post(
        KNOWLEDGE_BASES_URL,
        headers=headers,
        json={"name": name, "description": description},
    )
    assert response.status_code == 201
    return response.json()["data"]


async def test_knowledge_base_crud(client: AsyncClient) -> None:
    _, headers = await create_authenticated_user(client, email="owner@example.com")
    created = await create_knowledge_base(client, headers)

    get_response = await client.get(f"{KNOWLEDGE_BASES_URL}/{created['id']}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["data"]["name"] == "Engineering Handbook"

    update_response = await client.patch(
        f"{KNOWLEDGE_BASES_URL}/{created['id']}",
        headers=headers,
        json={"name": "Updated Handbook", "description": None},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["name"] == "Updated Handbook"
    assert update_response.json()["data"]["description"] is None

    delete_response = await client.delete(
        f"{KNOWLEDGE_BASES_URL}/{created['id']}",
        headers=headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True

    missing_response = await client.get(
        f"{KNOWLEDGE_BASES_URL}/{created['id']}",
        headers=headers,
    )
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "knowledge_base_not_found"


async def test_list_is_paginated_and_scoped_to_current_user(client: AsyncClient) -> None:
    _, owner_headers = await create_authenticated_user(client, email="owner@example.com")
    _, other_headers = await create_authenticated_user(client, email="other@example.com")

    for index in range(3):
        await create_knowledge_base(client, owner_headers, name=f"Owner KB {index}")
    await create_knowledge_base(client, other_headers, name="Other User KB")

    first_page = await client.get(
        KNOWLEDGE_BASES_URL,
        headers=owner_headers,
        params={"page": 1, "page_size": 2},
    )
    second_page = await client.get(
        KNOWLEDGE_BASES_URL,
        headers=owner_headers,
        params={"page": 2, "page_size": 2},
    )

    assert first_page.status_code == 200
    assert len(first_page.json()["data"]["items"]) == 2
    assert first_page.json()["data"]["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 3,
        "pages": 2,
    }
    assert len(second_page.json()["data"]["items"]) == 1
    names = {
        item["name"]
        for response in (first_page, second_page)
        for item in response.json()["data"]["items"]
    }
    assert names == {"Owner KB 0", "Owner KB 1", "Owner KB 2"}


async def test_other_user_cannot_read_update_or_delete_knowledge_base(
    client: AsyncClient,
) -> None:
    _, owner_headers = await create_authenticated_user(client, email="owner@example.com")
    _, attacker_headers = await create_authenticated_user(client, email="attacker@example.com")
    knowledge_base = await create_knowledge_base(client, owner_headers)
    url = f"{KNOWLEDGE_BASES_URL}/{knowledge_base['id']}"

    get_response = await client.get(url, headers=attacker_headers)
    update_response = await client.patch(
        url,
        headers=attacker_headers,
        json={"name": "Stolen"},
    )
    delete_response = await client.delete(url, headers=attacker_headers)

    for response in (get_response, update_response, delete_response):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "knowledge_base_not_found"

    owner_response = await client.get(url, headers=owner_headers)
    assert owner_response.status_code == 200
    assert owner_response.json()["data"]["name"] == "Engineering Handbook"


async def test_knowledge_base_endpoints_require_authentication(client: AsyncClient) -> None:
    response = await client.get(KNOWLEDGE_BASES_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_knowledge_base_input_validation(client: AsyncClient) -> None:
    _, headers = await create_authenticated_user(client, email="owner@example.com")

    blank_name = await client.post(
        KNOWLEDGE_BASES_URL,
        headers=headers,
        json={"name": "   "},
    )
    empty_patch_target = await create_knowledge_base(client, headers)
    empty_patch = await client.patch(
        f"{KNOWLEDGE_BASES_URL}/{empty_patch_target['id']}",
        headers=headers,
        json={},
    )
    invalid_page_size = await client.get(
        KNOWLEDGE_BASES_URL,
        headers=headers,
        params={"page_size": 101},
    )

    assert blank_name.status_code == 422
    assert empty_patch.status_code == 422
    assert invalid_page_size.status_code == 422
