# SimpleEdgeGateway プロジェクト管理定義

**Date:** 2026/01/16
**Author:** Pekokana
**Status:** Stable
**Version:** 1.0

このドキュメントは、本プロジェクトにおけるドキュメントのステータス定義、およびフェーズ管理の基準を定めたものです。

---

## 1. ドキュメント・ステータス定義

各マークダウンファイルの冒頭に記載する `Status` の定義です。

| ステータス | 意味 | 振る舞いのルール |
| --- | --- | --- |
| **Draft** | 下書き・構想中 | アイデア段階であり、大幅な変更が頻繁に発生する。 |
| **In Review** | レビュー・検証中 | 基本方針は固まったが、細部の矛盾や実現可能性を確認中。 |
| **Design Freeze** | **設計凍結 (確定)** | **原則として変更禁止。** 実装の「正」となる。変更には再検討が必要。 |
| **Active / Execution** | **実行・実装中** | ロードマップ等で使用。現在進行形でタスクを消化している状態。 |
| **Stable** | 安定・完成 | 実装とテストが完了し、ドキュメントと実態が一致している。 |
| **Deprecated** | 廃止・旧版 | 新しい設計や機能に置き換わり、参照すべきでない情報。 |

---

## 2. フェーズ管理定義

ロードマップにおけるフェーズ（段階）の移行基準です。

### Phase 1: Foundation (基盤構築)

* **Status:** `Active`
* **目標**: 開発環境の整備と、共通ライブラリ（DB/Config）の完成。
* **完了条件**: `gateway.db` が自動生成され、Pythonから読み書きできること。

### Phase 2: Core Logic (核心実装)

* **Status:** `Planning`
* **目標**: 外部機器なしで「収集・判定・保存」のロジックを完成させる。
* **完了条件**: ダミーデータを用いて、確信度判定に基づき `events` が生成されること。

### Phase 3: Interface & Integration (接続と可視化)

* **Status:** `Waiting`
* **目標**: Modbus実機通信の実装と、Web UIでのモニタリング。
* **完了条件**: ブラウザ上でPLCのリアルタイムデータが確認できること。

---

## 3. 変更管理フロー (Change Management)

一度 **Design Freeze** した内容を変更する場合のフローです。

1. **Issue提起**: なぜ変更が必要か（現場の制約、バグ、仕様漏れ等）を明確にする。
2. **Impact調査**: その変更が他のモジュール（DBスキーマやWeb UI）にどう影響するかを確認する。
3. **Freeze解除**: ステータスを一時的に `In Review` に戻し、修正案を確定させる。
4. **再Freeze**: 修正完了後、再度 `Design Freeze` を宣言して実装を再開する。

---

## 4. プロジェクト資料一覧

現在の各資料の信頼度と進捗状況です。

| 資料名 | ステータス | 役割 / 内容 |
| --- | --- | --- |
| `Architecture.md` | **Design Freeze** | システム全体構造、Windows/Linux連携、プロセス図。 |
| `collection_logic.md` | **Design Freeze** | Bulk Read（一括読出し）の優先順位とグループ化ロジック。 |
| `DatabaseDesign.md` | **Design Freeze** | SQLiteテーブル定義、ER図、WALモード等の最適化。 |
| `TriggerSpec.md` | **Design Freeze** | 確信度判定（カウント）、ヒステリシス、復旧ロジック。 |
| `ProjectManagement.md` | **Stable** | ドキュメント管理ルール、フェーズ移行基準。 |
| `Roadmap.md` | **Execution Starts** | フェーズ1（基盤構築）の開始、実装手順。 |

