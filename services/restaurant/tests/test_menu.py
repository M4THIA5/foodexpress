"""Consultation : liste des restaurants et menu."""
API = "/api/v1"


def test_list_restaurants(client):
    r = client.get(f"{API}/restaurants")
    assert r.status_code == 200
    noms = {resto["nom"] for resto in r.json()}
    assert {"Chez Luigi", "Sushi Zen", "Le Bistrot Fermé"} <= noms


def test_get_menu(client):
    r = client.get(f"{API}/restaurants/1/menu")
    assert r.status_code == 200
    body = r.json()
    assert body["restaurant"]["nom"] == "Chez Luigi"
    plats = {p["nom"]: p for p in body["plats"]}
    assert plats["Pizza Margherita"]["prix"] == 11.50
    assert plats["Tiramisu"]["disponible"] is False


def test_get_menu_unknown_restaurant(client):
    r = client.get(f"{API}/restaurants/999/menu")
    assert r.status_code == 404
