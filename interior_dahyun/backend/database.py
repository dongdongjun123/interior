# database.py
# 실제 서비스에서는 SQLite/PostgreSQL로 교체될 부분.
# Phase 4에서는 구조를 보여주기 위한 Mock DB (dict 기반).

FURNITURE_DB = {
    "chair-001": {
        "id": "chair-001",
        "name": "Wood Chair",
        "rating": 5.0,
        "price": 179000,
        "similar": [
            {"shop": "오늘의집", "price": 179000},
            {"shop": "IKEA", "price": 169000},
            {"shop": "쿠팡", "price": 165000},
            {"shop": "11번가", "price": 162000},
        ],
    },
    "table-001": {
        "id": "table-001",
        "name": "Oak Dining Table",
        "rating": 4.8,
        "price": 320000,
        "similar": [
            {"shop": "오늘의집", "price": 320000},
            {"shop": "IKEA", "price": 298000},
            {"shop": "쿠팡", "price": 289000},
        ],
    },
    "lamp-001": {
        "id": "lamp-001",
        "name": "Warm Floor Lamp",
        "rating": 4.6,
        "price": 89000,
        "similar": [
            {"shop": "오늘의집", "price": 89000},
            {"shop": "쿠팡", "price": 79000},
        ],
    },
}


def get_furniture(item_id: str):
    """가구 ID로 상품 정보 + 비슷한 상품 목록 조회"""
    return FURNITURE_DB.get(item_id)


def get_floorplan_mock():
    """AI 평면도 분석 결과 mock (실제로는 이미지 분석 모델 결과가 들어올 자리)"""
    return {
        "area_sqm": 14.2,
        "area_pyeong": 4.3,
        "width_m": 3.6,
        "depth_m": 3.9,
        "ceiling_m": 2.4,
        "rooms": "침실/화장실",
    }
