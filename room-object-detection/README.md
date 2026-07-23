# Room Object Detection

방 사진에서 가구를 인식해 위치를 JSON으로 출력합니다.
Florence-2의 phrase grounding을 사용합니다.

## 설치

```bash
conda create -n roomdet python=3.11 -y
conda activate roomdet
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

> `transformers==4.49.0` 고정 필수. 최신 버전은 Florence-2와 충돌합니다
> (`AttributeError: 'Florence2LanguageConfig' object has no attribute 'forced_bos_token_id'`).

## 사용법

```bash
python detect.py samples/room.jpg     # JSON 출력
python visualize.py                   # 박스 그린 이미지 저장
```

## 출력 형식

```json
{
  "image_size": { "width": 1080, "height": 1440 },
  "object_count": 8,
  "objects": [
    {
      "id": 0,
      "class": "bed",
      "bbox_pixel": { "x": 0, "y": 684, "w": 686, "h": 752 },
      "bbox_norm": { "x": 0.0, "y": 0.475, "w": 0.635, "h": 0.522 },
      "floor_contact": { "x": 0.317, "y": 0.997 }
    }
  ]
}
```

- `bbox_norm` — 이미지 크기로 나눈 0~1 좌표
- `floor_contact` — 가구가 바닥에 닿는 지점 (탑뷰 변환 시 활용)

## 인식 대상

bed, chair, table, nightstand, lamp, plant, shelf, picture, rug 등

## 알려진 한계

- 좌표는 카메라 시점 기준입니다. 탑뷰 변환은 포함하지 않습니다.
- 유사 가구가 하나의 클래스로 묶일 수 있습니다 (협탁/사이드테이블 등).