from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from stac_pydantic.item import Item


@pytest.mark.parametrize(
    "payload",
    [
        {
            "package_name": "stactools-glad-glclu2020",
            "group_name": "gladglclu2020",
            "create_item_args": [
                "https://storage.googleapis.com/earthenginepartners-hansen/GLCLU2000-2020/v2/2000/50N_090W.tif"
            ],
        },
        {
            "package_name": "stactools-glad-global-forest-change==0.1.2",
            "group_name": "gladglobalforestchange",
            "create_item_args": [
                "https://storage.googleapis.com/earthenginepartners-hansen/GFC-2023-v1.11/Hansen_GFC-2023-v1.11_gain_40N_080W.tif",
                "https://storage.googleapis.com/earthenginepartners-hansen/GFC-2023-v1.11/Hansen_GFC-2023-v1.11_treecover2000_40N_080W.tif",
                "https://storage.googleapis.com/earthenginepartners-hansen/GFC-2023-v1.11/Hansen_GFC-2023-v1.11_lossyear_40N_080W.tif",
                "https://storage.googleapis.com/earthenginepartners-hansen/GFC-2023-v1.11/Hansen_GFC-2023-v1.11_datamask_40N_080W.tif",
            ],
        },
    ],
)
def test_item(payload: Dict[str, Any], app: TestClient) -> None:
    response = app.post(
        "/item",
        json=payload,
    )

    assert response.status_code == 200
    Item(**response.json())


def test_item_with_collection(app: TestClient) -> None:
    test_collection_id = "test"
    payload = {
        "package_name": "stactools-glad-glclu2020",
        "group_name": "gladglclu2020",
        "create_item_args": [
            "https://storage.googleapis.com/earthenginepartners-hansen/GLCLU2000-2020/v2/2000/50N_090W.tif"
        ],
        "collection_id": test_collection_id,
    }

    response = app.post(
        "/item",
        json=payload,
    )

    assert response.status_code == 200
    item = Item(**response.json())
    assert item.collection == test_collection_id
