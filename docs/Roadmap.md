# SimpleEdgeGateway 実装ロードマップ

**Date:** 2026/01/16
**Author:** Pekokana
**Status:** Planning / Execution Starts
**Version:** 1.0

---

## 1. 実装の基本方針

* **共通基盤の先行構築**: YAML設定読み込みとSQLiteアクセス基盤を最優先で作成し、各モジュールで再利用する。
* **「動く最小構成」の早期実現**: Modbusの実機がなくても、ダミーデータでUI表示・判定までが貫通する状態をまず作る。
* **スレッドセーフな設計**: SQLiteのWALモードを活用し、収集・判定・WebUIが互いに干渉しない疎結合な実装を目指す。

---

## 2. フェーズ別実装ステップ

### フェーズ 1: 共通基盤とプロジェクト初期化

プロジェクトの土台となる部分です。

* [ ] **環境構築**: `requirements.txt` の作成（PyYAML, Flask/FastAPI, pymodbus等）。
* [ ] **ディレクトリ構成の作成**: `src/`, `config/`, `data/`, `logs/` の展開。
* [ ] **設定管理 (`config_loader.py`)**: `config.yaml` を読み込むシングルトンクラスの実装。
* [ ] **DBアクセス基盤 (`db_handler.py`)**: SQLiteの接続管理、WALモード設定、共通CRUD処理の実装。
* [ ] **DB初期化スクリプト (`db_initializer.py`)**: スキーマ定義SQLの実行とサンプルデータの投入。

### フェーズ 2: 収集・判定コアエンジン（モック）

外部機器なしで、内部ロジックを完成させます。

* [ ] **ダミー収集機 (`dummy_poller.py`)**: 乱数を用いて `items.last_value` を更新し、履歴に保存するループ。
* [ ] **判定エンジン (`evaluator.py`)**: DBの最新値を監視し、確信度判定ロジック（`problem_count` / `recovery_count`）の実装。
* [ ] **イベント記録**: 状態変化時に `events` テーブルへ書き込む機能の実装。

### フェーズ 3: Web UI 基礎

可視化と設定変更のUIを構築します。

* [ ] **Webサーバー基盤**: Flask/FastAPIによるサーバー起動。
* [ ] **ダッシュボード画面**: 最新値キャッシュの一覧表示（データリフレッシュ機能）。
* [ ] **設定変更画面**: ホストやアイテムの編集UIの実装。
* [ ] **動的リロード機能 (`config_watcher.py`)**: UIでの変更を検知し、エンジンに通知する仕組み。

### フェーズ 4: Modbus通信と実機テスト

実際の通信を実装し、製品レベルに引き上げます。

* [ ] **Modbusエンジン (`modbus_poller.py`)**: `pymodbus` を用いたTCP/RTU通信の実装。
* [ ] **Bulk Read実装**: 同一周期・近接アドレスを一括で読み出す最適化ロジック。
* [ ] **死活監視ロジック**: 通信エラー時のホストダウン判定。
* [ ] **ハウスキーパー**: `retention_days` に基づく古いデータの自動削除処理。

### フェーズ 5: 配布と安定化

* [ ] **エラーハンドリング**: 通信断、DBロック、ログローテーションの強化。
* [ ] **バイナリ化**: `PyInstaller` を用いた `.exe` および Linuxバイナリのビルド。
* [ ] **OSサービス化**: Windows Service / systemd 登録手順のドキュメント化。

---

## 3. ディレクトリツリー構造 (振り返り用)

```text
simple-edge-gateway/
├── config/              # 設定ファイル (config.yaml)
├── data/                # SQLite DB (gateway.db)
├── logs/                # アプリケーションログ (*.log)
├── src/
│   ├── common/          # config_loader, db_handler
│   ├── engine/          # poller, evaluator, housekeeper
│   ├── web/             # templates, static, routes
│   └── main.py          # 全スレッドの起動管理
├── ROADMAP.md           # 本ファイル
└── Architecture.md      # システム設計図

```

---

## 4. 開発における重要メモ (Tips)

* **SQLite WALモード**: 複数のスレッドから同時に読み書きする際は、必ず有効にすること。
* **パスの扱い**: プログラム内では `os.path.abspath(__file__)` 等を用いて、実行環境に依存しない相対パス解決を行う。
* **YAMLの活用**: 監視設定（Hosts/Items）はDBで行うが、DBパスやログレベルなどの「システム自身の動作設定」はYAMLで行う、という役割分担を徹底する。

