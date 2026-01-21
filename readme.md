# SimpleEdgeGateway

## 💡 背景とビジョン

「産業用PCや高価なSCADAライセンスがなくても、現場を良くするシステムは作れるはずだ」

このプロジェクトは、そんな思いからスタートしました。
実機PLCの代わりに自作の **PLCSim** を使い、そのデータをこの **SimpleEdgeGateway** で正規化し、最終的にはモダンなWeb技術を用いた **自作SCADA** へと繋げます。

お金をかけずに、オープンソースとエンジニアリングの力だけで「現場のDX」のプロトタイプを爆速で作り上げるためのエコシステムを目指しています。



## 🗺️ プロジェクト・ロードマップ

現在は「フェーズ1：基盤設計」が完了し、実装を開始する段階にあります。開発の進捗や設計の詳細は、以下のドキュメントを参照してください。

### 1. 設計・仕様 (Design Docs)

* **[Architecture.md](docs/Architecture.md)** : 全体構造・プロセス間連携の図解
* **[DatabaseDesign.md](docs/DatabaseDesign.md)** : SQLiteテーブル定義・ER図
* **[CollectionLogic.md](docs/CollectionLogic.md)** : Modbus Bulk Readのアルゴリズム
* **[TriggerSpec.md](docs/TriggerSpec.md)** : 確信度判定・ヒステリシスのロジック
* **[APISpec.md](docs/APISpec.md)** : SCADA連携用API仕様

### 2. プロジェクト管理 (Management)

* **[ProjectManagement.md](docs/ProjectManagement.md)** : ドキュメントのステータス定義・運用ルール
* **[Roadmap.md](docs/Roadmap.md)** : 実装タスクの進捗状況

## 開発環境の構築

本プロジェクトは Python の高速パッケージマネージャー [uv](https://docs.astral.sh/uv/) を使用しています。

### 1. 前提条件

* Python 3.13 以上
* [uv](https://docs.astral.sh/uv/) がインストールされていること

### 2. セットアップ

リポジトリをクローンし、依存関係のインストールとパッケージの同期を行います。

```bash
git clone https://github.com/pekokana/SimpleEdgeGateway
cd SimpleEdgeGateway
uv sync
```

※ `uv sync` により、実行用のコマンド（`poller`, `web-gui`）が自動的に生成されます。

### 3. 設定ファイルの作成

プロジェクトのルート直下に `config` フォルダを作成し、`config.yaml` を配置してください。

**設定ファイルの設定値**は後述の`設定ファイルの詳細`を参照してください。

```構造イメージ:
SimpleEdgeGateway/
├── config/
│   └── config.yaml  <-- ここに配置
├── src/
├── pyproject.toml
└── ...
```

### 4. データベースの作成

本プロジェクトは、動作の中心にSQLiteを利用しています。
アプリケーション実行前にデータベースを作成します。

```bash
uv run dbinit
```

### 5. アプリケーションの実行

本プロジェクトは、データ収集エンジン（Poller）と Web UI の2つのプロセスで構成されます。それぞれのターミナルで実行してください。

#### データ収集エンジンの起動 (PLC定期データ参照)

```bash
uv run poller
```

#### Web UI / API サーバーの起動

```bash
uv run web-gui
```

起動後、ブラウザで `http://localhost:8000`（または config で指定したポート）にアクセスしてください。

#### SimplePLCSimを使った監視対象PLC稼働環境

`SimplePLCSim`は、[こちら](https://github.com/pekokana/SimplePLCSim/releases/tag/v0.1.0)から取得することができます。

* 4つのPLCと400個の監視対象を扱う、各種設定ファイルを生成するツールを用意しています。


1. ツール実行前に、`src/tools/gen_test_env.py`のコードを環境に合わせて変更してください。

```python
# 基本設定
BASE_DIR = "D:/dev/SimpleEdgeGateway/opttools/large"　# ←設定ファイルを生成するフォルダを指定する。
EXE_DIR = "D:/dev/SimpleEdgeGateway/opttools" # ←SimplePLCSimのexe格納先を指定する。
```

2. 設定ファイルを生成してください。

```bash
run run python -m src/tools/get_test_env.py
```

3. 生成ファイルに`edge_import_large.yaml`がありますので、SimpleEdgeGatewayのWeb UI機能の機能設定からインポートしてください。





## 設定ファイルの詳細 (`config/config.yaml`)

本システムの設定は `config/config.yaml` で行います。各項目の意味は以下の通りです。

### 設定例

```yaml
system:
  db_path: "data/gateway.sqlite" # データベースファイルの保存先
  retention_minutes: 180         # データ保持期間（分）。この時間を過ぎた古いデータは自動削除されます
  web_host: "127.0.0.1"          # Webサーバーの待受IP
  web_port: 8080                 # Webサーバーのポート番号
  web_reload: True               # 開発者モード（Trueの場合、コード変更時に自動再起動）
  log_level: "INFO"              # ログ出力レベル (DEBUG, INFO, WARNING, ERROR)

polling:
  interval_seconds: 1            # 収集サイクル（秒）。PLCへの読み取り間隔
  timeout: 2.0                   # Modbus通信のタイムアウト（秒）

```

### 各項目の説明

* **db_path**: SQLiteデータベースの保存場所です。実行前にフォルダ（例：`data/`）が存在することを確認してください。
* **retention_minutes**: DBの肥大化を防ぐための設定です。Pollerが動作するたびに、この時間を経過した過去データが自動的にクリーンアップされます。
* **web_host / web_port**: `uv run web-gui` で起動する管理画面のアドレスです。
* **interval_seconds**: PLCや機器からデータを取得する周期です。機器の負荷に応じて調整してください。

---

## 📝 関連情報

* **Note**: [開発の背景と想い](https://note.com/pekokana/n/nefe8b2a7c538)
* **Qiita**: (今後、連載記事のリンクを追記予定)

