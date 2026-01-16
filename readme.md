# SimpleEdgeGateway

## 💡 背景とビジョン

「産業用PCや高価なSCADAライセンスがなくても、現場を良くするシステムは作れるはずだ」

このプロジェクトは、そんな思いからスタートしました。
実機PLCの代わりに自作の **PLCSim** を使い、そのデータをこの **SimpleEdgeGateway** で正規化し、最終的にはモダンなWeb技術を用いた **自作SCADA** へと繋げます。

お金をかけずに、オープンソースとエンジニアリングの力だけで「現場のDX」のプロトタイプを爆速で作り上げるためのエコシステムを目指しています。

---

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

---

## 📝 関連情報

* **Note**: [開発の背景と想い](https://note.com/pekokana/n/nefe8b2a7c538)
* **Qiita**: (今後、連載記事のリンクを追記予定)

