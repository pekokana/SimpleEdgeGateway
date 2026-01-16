# SimpleEdgeGateway API 仕様書 (Draft)

**Date:** 2026/01/16
**Author:** Pekokana
**Status:** In Review
**Version:** 1.0
**Base URL:** `http://<gateway-ip>:8080/api/v1`

## 1. 概要

本APIは、SCADAシステムや外部ダッシュボードが、エッジサーバー内の最新値、履歴、アラーム状態を取得するためのインターフェースです。

---

## 2. エンドポイント一覧

### 2.1. 最新値一括取得 (Bulk Latest Data)

SCADAのリアルタイム監視画面を更新するために使用します。

* **URL**: `/latest`
* **Method**: `GET`
* **Response**:

```json
{
  "timestamp": "2026-01-16T15:04:05Z",
  "data": [
    {
      "tag": "TANK_LEVEL_01",
      "value": 85.5,
      "status": "OK",
      "unit": "L"
    },
    {
      "tag": "HEATER_TEMP_01",
      "value": 62.3,
      "status": "PROBLEM",
      "unit": "degC"
    }
  ]
}

```

### 2.2. 特定アイテムの履歴取得 (Item History)

SCADAのトレンドグラフ（折れ線グラフ）を描画するために使用します。

* **URL**: `/history/{tag_name}?hours=24`
* **Method**: `GET`
* **Response**:

```json
{
  "tag": "TANK_LEVEL_01",
  "values": [
    ["2026-01-16T14:00:00Z", 84.1],
    ["2026-01-16T14:10:00Z", 84.5],
    ["2026-01-16T14:20:00Z", 85.5]
  ]
}

```

### 2.3. アラームサマリ (Active Alerts)

現在発生している障害のみを取得します。

* **URL**: `/alerts`
* **Method**: `GET`
* **Response**:

```json
[
  {
    "trigger_id": 105,
    "name": "高温度異常",
    "tag": "HEATER_TEMP_01",
    "priority": "Critical",
    "since": "2026-01-16T13:00:00Z"
  }
]

```

---

## 3. Zabbix API 互換メソッド (JSON-RPC)

学習用として、Zabbix等の既存監視ツールと同じ作法でデータを取得できるよう、以下のエンドポイントも準備します。

* **URL**: `/rpc`
* **Method**: `POST`
* **Payload例**:

```json
{
    "jsonrpc": "2.0",
    "method": "item.get",
    "params": {
        "output": "extend",
        "filter": { "name": "TANK_LEVEL_01" }
    },
    "id": 1
}

```

---

## 4. エラーレスポンス

APIリクエストに失敗した場合の共通フォーマットです。

```json
{
  "error": {
    "code": 404,
    "message": "Item 'INVALID_TAG' not found."
  }
}

```

---

## SCADA実装時の学習ポイント（勉強用メモ）

この `api_spec.md` があることで、あなたはSCADA側を実装する際、以下のコードを書くだけで良くなります。

1. **Python(requests)** や **JavaScript(fetch)** で `/api/v1/latest` を叩く。
2. 返ってきたJSONから `value` を取り出し、画面のメーターを動かす。
3. `status` が `PROBLEM` なら、画面の背景を赤く光らせる。

これが「SCADAの基本」の入り口です！
