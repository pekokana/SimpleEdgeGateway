# SimpleEdgeGateway 実装ロードマップ

**Date:** 2026/01/21
**Author:** Pekokana
**Status:** Planning / Execution Starts
**Version:** 1.1

---

## 1. 実装の基本方針

* **共通基盤の先行構築**: YAML設定読み込みとSQLiteアクセス基盤を最優先で作成し、各モジュールで再利用する。
* **「動く最小構成」の早期実現**: Modbusの実機がなくても、ダミーデータでUI表示・判定までが貫通する状態をまず作る。
* **スレッドセーフな設計**: SQLiteのWALモードを活用し、収集・判定・WebUIが互いに干渉しない疎結合な実装を目指す。

---

## 2. フェーズ別実装ステップ

### フェーズ 1: 共通基盤とプロジェクト初期化

プロジェクトの土台となる部分です。

* [x] **環境構築**: `requirements.txt` の作成（PyYAML, Flask/FastAPI, pymodbus等）。
* [x] **ディレクトリ構成の作成**: `src/`, `config/`, `data/`, `logs/` の展開。
* [x] **設定管理 (`config_loader.py`)**: `config.yaml` を読み込むシングルトンクラスの実装。
* [x] **DBアクセス基盤 (`db_handler.py`)**: SQLiteの接続管理、WALモード設定、共通CRUD処理の実装。
* [x] **DB初期化スクリプト (`db_initializer.py`)**: スキーマ定義SQLの実行とサンプルデータの投入。

### フェーズ 2: 収集・判定コアエンジン（モック）

外部機器なしで、内部ロジックを完成させます。

* [x] **ダミー収集機 (`dummy_poller.py`)**: 乱数を用いて `items.last_value` を更新し、履歴に保存するループ。
* [x] **判定エンジン (`evaluator.py`)**: DBの最新値を監視し、確信度判定ロジック（`problem_count` / `recovery_count`）の実装。
* [X] **イベント記録**: 状態変化時に `events` テーブルへ書き込む機能の実装。

### フェーズ 3: Web UI 基礎

可視化と設定変更のUIを構築します。

* [x] **Webサーバー基盤**: Flask/FastAPIによるサーバー起動。
* [x] **ダッシュボード画面**: 最新値キャッシュの一覧表示（データリフレッシュ機能）。
* [x] **設定変更画面**: ホストやアイテムの編集UIの実装。
* [ ] **動的リロード機能 (`config_watcher.py`)**: UIでの変更を検知し、エンジンに通知する仕組み。

### フェーズ 4: Modbus通信と実機テスト

実際の通信を実装し、製品レベルに引き上げます。

* [x] **Modbusエンジン (`modbus_poller.py`)**: `pymodbus` を用いたTCP/RTU通信の実装。
* [ ] **Bulk Read実装**: 同一周期・近接アドレスを一括で読み出す最適化ロジック。
* [x] **死活監視ロジック**: 通信エラー時のホストダウン判定。
* [x] **ハウスキーパー**: `retention_days` に基づく古いデータの自動削除処理。

### フェーズ 4.5: 運用の高度化（今回見えてきた課題）
* [ ] **閾値変更への即時追従**: 周期無視の判定ロジック。
* [ ] **Poller起動時のアラート状態復元**: `active` ログの辞書展開。

### フェーズ 4.6: Pollerの機能分割と機能追加基盤の整理

# ゴールを再定義（合意）

* PLC（Modbus等）から値を取得
* Edge Server 側で監視・判定・蓄積
* SCADA 学習用に **Zabbix に近い構成思想** を体験できる
* SQLite を中心に据える（軽量・自己完結）
* 将来 exe 化したい



# Zabbix をお手本にした全体像

まず **思想レベル** を揃えます。

```
        +------------+
        |  Web UI    |
        | (設定変更) |
        +------+-----+
               |
               v
+-----------------------------+
|          SQLite DB          |
|-----------------------------|
| hosts / items / triggers    |
| raw_values                  |
| history                     |
| events                      |
+-----------------------------+
   ^          ^          ^
   |          |          |
+--+--+   +---+----+  +--+--+
|poller| |preproc |  |house |
|      | |worker  |  |keeper|
+------+ +--------+  +------+
```

**SQLite = ハブ**
すべてのプロセスが「直接会話しない」のが重要です。


# 各コンポーネントの責務定義（超重要）

## ① Poller（あなたが今作っているもの）

### 責務

* PLC / Modbus に **周期的にアクセス**
* 値を「生で」取得
* **判定しない**
* **加工しない**
* DB に書くだけ

### 書き込み先

```text
raw_values
```

### 擬似イメージ

```python
while True:
    val = read_plc()
    insert raw_values(item_id, value, timestamp)
    sleep(interval)
```

> **Zabbix poller に似せたい**

## ② Preprocessing Worker（新設）

### 責務

* raw_values を読む
* 型変換（int / float / scaling）
* ノイズ除去
* トリガー条件評価（閾値、式）
* event 発火
* history に保存

### 読み書き

| 操作     | テーブル             |
| ------ | ---------------- |
| read   | raw_values       |
| read   | items / triggers |
| write  | history          |
| write  | events           |
| update | items.last_value |

> **poller と絶対に役割を混ぜない**


## ③ History Writer（分離するなら）

SQLite なら **preproc と統合**してもOKですが、
Zabbix 的に言うと：

* bulk insert
* 圧縮
* retention

を担当。


## ④ Housekeeper（あなたの疑問の答え）

> raw_values が増え続けるのでは？

**YES。だから必要です。**

### 役割

* raw_values の削除
* history の保持期間制御
* event のクリーンアップ

### 例

```sql
DELETE FROM raw_values
WHERE created_at < DATETIME('now', '-1 day');
```

> **これが Zabbix の housekeeper**


# データの流れ（超重要）

## 全体フロー

```
PLC
 ↓
poller
 ↓
raw_values  ← キュー
 ↓
preprocessing
 ↓
history / events
```

### ポイント
* poller は速く・軽く
* 判定は後段
* どこか止まっても他は動く


# SQLite はジョブキューになるのか？

## 結論

> **YES。ただし “簡易キュー” と割り切る**

### raw_values テーブル例

```sql
CREATE TABLE raw_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER,
    value REAL,
    created_at DATETIME,
    processed INTEGER DEFAULT 0
);
```

### Preprocessing 側

```sql
SELECT * FROM raw_values
WHERE processed = 0
ORDER BY created_at
LIMIT 100;
```

→ 処理後

```sql
UPDATE raw_values SET processed = 1 WHERE id = ?;
```

> **これで十分 Zabbix 的**


# 「Web UI で設定変えたら poller はどう知る？」

ここも重要。

## 結論

> **poller は定期的に DB を再読込するだけ**

### なぜ？

* DB が唯一の真実
* Pub/Sub は不要
* Edge用途なら十分高速

### 実装イメージ

```python
if time_to_reload_config:
    items = fetch_items()
```

> Zabbix も同じ思想のようである。


# 1プロセス asyncio で足りる？

## 結論

* **今の学習用途なら YES**
* でも構造は **プロセス分離前提** にする

### 実践案

| 段階 | 構成                               |
| -- | -------------------------------- |
| 今  | poller / preproc を別 asyncio task |
| 次  | multiprocessing                  |
| 最終 | exe + 複数 worker                  |

# 起動方法（exe を見据えた設計）

## 理想形

```bat
edgeserver.exe poller
edgeserver.exe preproc
edgeserver.exe housekeeper
```

内部で：

```python
if role == "poller":
    run_poller()
```

> **Zabbix server -c 的**


# ここまでのまとめ

* SQLite = 中央ハブ
* poller / preproc / housekeeper を分離
* raw_values はキュー
* housekeeper は必須
* trigger expression = 条件式エンジン
* asyncio でも設計思想は再現できる



### フェーズ 5: 配布と安定化

* [ ] **エラーハンドリング**: 通信断、DBロック、ログローテーションの強化。
* [ ] **バイナリ化**: `PyInstaller` を用いた `.exe` および Linuxバイナリのビルド。
* [ ] **OSサービス化**: Windows Service / systemd 登録手順のドキュメント化。

* [ ] **DBロック（Database is locked）対策**: 現在 update_item_value 等で個別に接続していますが、書き込みが重なった際の busy_timeout 設定の追加。

* [ ] **Modbus通信リトライ**: 通信が1回失敗しただけでOfflineにせず、3回連続失敗でOfflineとする「遊び」の実装。

---


## 4. 開発における重要メモ (Tips)

* **SQLite WALモード**: 複数のスレッドから同時に読み書きする際は、必ず有効にすること。
* **パスの扱い**: プログラム内では `os.path.abspath(__file__)` 等を用いて、実行環境に依存しない相対パス解決を行う。
* **YAMLの活用**: 監視設定（Hosts/Items）はDBで行うが、DBパスやログレベルなどの「システム自身の動作設定」はYAMLで行う、という役割分担を徹底する。

