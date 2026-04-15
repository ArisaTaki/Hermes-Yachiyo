<div align="center">

# 🌸 Hermes-Yachiyo

**デスクトップファーストのローカルパーソナルエージェントアプリケーション**

[Hermes Agent](https://github.com/NousResearch/hermes-agent) をベースに構築されたインテリジェントデスクトップアシスタント

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-105%20passed-brightgreen.svg)](#テスト)

**[English](README.en.md)** | **[中文](README.md)** | **日本語**

</div>

---

## ✨ 特長

- 🖥️ **デスクトップファースト** — ローカル実行のデスクトップアプリ、システムトレイ常駐、サーバー不要
- 🔄 **3つの表示モード** — ウィンドウ / フローティングバブル / Live2D キャラクター
- 🤖 **スマートタスクシステム** — プラガブルな実行戦略、シミュレーションと Hermes CLI 実行に対応
- 🎨 **Live2D 対応準備完了** — モデル設定・ディレクトリスキャン・バリデーション体系を完備
- ⚙️ **完全な設定システム** — 即時反映/再起動必要の段階的フィードバック
- 🔌 **QQ ブリッジ** — AstrBot プラグインによるリモート制御（`/y` コマンド群）
- 🏗️ **厳格なレイヤリング** — Shell / Core / Bridge / Locald / Protocol の明確な責務分離

## 📸 表示モード

| ウィンドウモード | バブルモード | Live2D モード |
|:---:|:---:|:---:|
| 560×520 フルダッシュボード | 320×280 フローティングステータス | 380×560 キャラクタースケルトン |
| タスク統計・設定パネル | 自動更新・ワンクリック展開 | モーション占位・設定入口 |

## 🏛️ アーキテクチャ

```
┌────────────────────────────────────────────────┐
│          Hermes-Yachiyo デスクトップアプリ        │
│                                                │
│  ┌── App Shell (apps/shell) ────────────────┐  │
│  │  エントリ・システムトレイ・ウィンドウ管理    │  │
│  │  表示モード: window / bubble / live2d     │  │
│  │  設定・効果ポリシー・統合ステータス         │  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Core Runtime (apps/core) ───────────────┐  │
│  │  Hermes Agent ラッパー・タスク状態管理      │  │
│  │  TaskRunner・実行戦略・HTTP 非公開         │  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Local (apps/locald) ────────────────────┐  │
│  │  スクリーンショット・アクティブウィンドウ    │  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Bridge (apps/bridge) ───────────────────┐  │
│  │  内部 FastAPI・UI と AstrBot 専用          │  │
│  │  再起動可能・設定ドリフト検出・状態機械     │  │
│  └───────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
           ↑ HTTP（ローカル、オプション）
  ┌────────┴───────┐        ┌───────────┐
  │  AstrBot Plugin │  ───→  │   Hapi    │
  │  (QQ ブリッジ)   │        │  (Codex)  │
  └────────────────┘        └───────────┘
```

## 🚀 クイックスタート

### 動作環境

- Python 3.11+
- macOS / Linux / Windows (WSL2)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)（アプリ内でインストールガイド提供）

### インストールと起動

```bash
# クローンしてインストール
git clone <repo-url>
cd Hermes-Yachiyo
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# デスクトップアプリを起動
hermes-yachiyo
# または
python -m apps.shell.app
```

### 初回起動フロー

アプリは Hermes Agent の状態を自動検出し、セットアップをガイドします：

```
Hermes 未インストール → インストールガイド UI（ワンクリックインストール）
    ↓
インストール済み・未初期化 → ワークスペース初期化ウィザード
    ↓
準備完了 → ノーマルモードへ → 現在の表示モード
```

## ⚙️ 設定システム

設定ファイルは `~/.hermes-yachiyo/config.json` に保存され、設定 UI から視覚的に編集できます。

| 設定項目 | デフォルト | 効果ポリシー |
|---------|----------|------------|
| `display_mode` | `window` | モード再起動が必要 |
| `bridge_enabled` | `true` | Bridge 再起動が必要 |
| `bridge_host` | `127.0.0.1` | Bridge 再起動が必要 |
| `bridge_port` | `8420` | Bridge 再起動が必要 |
| `tray_enabled` | `true` | アプリ再起動が必要 |
| `live2d.model_name` | — | 即時反映 |
| `live2d.model_path` | — | 即時反映 |
| `live2d.enable_expressions` | `false` | 即時反映 |
| `live2d.enable_physics` | `false` | 即時反映 |
| `live2d.window_on_top` | `false` | モード再起動が必要 |

保存後、各設定の効果ステータスヒントが即座に表示されます。

## 🤖 タスクシステム

タスクライフサイクル：`PENDING → RUNNING → COMPLETED / CANCELLED / FAILED`

**実行戦略：**

- **SimulatedExecutor** — MVP テスト用のモック実行
- **HermesExecutor** — `hermes run --prompt` の実際の CLI 呼び出し（自動検出）

```bash
# Bridge API 経由
curl http://127.0.0.1:8420/tasks -X POST \
  -H "Content-Type: application/json" \
  -d '{"description": "現在のディレクトリ構造を分析"}'

# QQ 経由
/y do 現在のディレクトリ構造を分析
/y check abc123
/y cancel abc123
```

## 🔌 QQ ブリッジ（AstrBot プラグイン）

AstrBot プラグインを介して QQ と連携します。すべてのコマンドは `/y` で始まります：

| コマンド | 説明 |
|---------|------|
| `/y status` | システム状態を表示 |
| `/y tasks` | タスク一覧 |
| `/y do <説明>` | タスクを作成 |
| `/y check <id>` | タスク詳細を照会 |
| `/y cancel <id>` | タスクをキャンセル |
| `/y screen` | スクリーンショット情報 |
| `/y window` | 現在のアクティブウィンドウ |
| `/y codex <説明>` | Codex 実行（Hapi、近日公開） |
| `/y help` | コマンドヘルプ |

プラグインはコマンドルーティングのみを担当し、ローカルロジックは実装しません。エラーメッセージは接続失敗、タイムアウト、サービス利用不可などをカバーしています。

## 🎨 Live2D サポート

現段階では完全な設定・バリデーションフレームワークを提供しています（レンダラー SDK は未統合）：

- **5段階バリデーション**：未設定 → パス無効 → モデルディレクトリではない → パス有効 → ロード済み
- **ディレクトリ自動スキャン**：`.moc3` / `.model3.json` ファイルを検出（Cubism 3/4 対応）
- **モデルサマリー抽出**：主要候補ファイル、ソースディレクトリ、レンダラーエントリポイント
- **設定ページで編集可能**：モデル名、パス、アイドルモーショングループ、表情/物理トグル
- **即時更新**：保存後すぐに再バリデーションして表示を更新

## 🔗 Bridge API

UI と AstrBot 向けの内部 FastAPI サービス：

| エンドポイント | メソッド | 説明 |
|-------------|--------|------|
| `/status` | GET | 実行状態とタスク統計 |
| `/tasks` | GET | タスク一覧 |
| `/tasks` | POST | タスク作成 |
| `/tasks/{id}` | GET | タスク詳細 |
| `/tasks/{id}/cancel` | POST | タスクキャンセル |
| `/screen/current` | GET | スクリーンショット（base64） |
| `/system/active-window` | GET | アクティブウィンドウ情報 |
| `/hermes/status` | GET | Hermes インストール状態 |

Bridge はランタイム再起動、設定ドリフト検出、状態機械管理（disabled / enabled_not_started / running / failed）をサポートしています。

## 🧪 テスト

```bash
# すべてのテストを実行
.venv/bin/python -m pytest tests/ -v

# 105 テスト、すべてパス
```

| テストモジュール | 数 | カバレッジ |
|---------------|---|---------|
| `test_protocol` | 14 | 列挙型、データモデル、リクエスト/レスポンス |
| `test_state` | 11 | タスクライフサイクル、終端状態保護 |
| `test_executor` | 7 | エグゼキューターモデル、シミュレーション実行 |
| `test_effect_policy` | 9 | 設定効果ポリシー |
| `test_integration_status` | 11 | Bridge/AstrBot/Hapi ステータス |
| `test_astrbot_handlers` | 32 | 全ハンドラー出力とエラーフォーマット |
| `test_startup` | 6 | 起動デシジョンツリー |

## 📁 プロジェクト構成

```
apps/
  shell/              # デスクトップアプリケーションシェル
    app.py              # メインエントリポイント
    startup.py          # 起動判定ロジック
    window.py           # メインウィンドウ (pywebview)
    config.py           # 設定管理 + Live2D バリデーション
    effect_policy.py    # 設定効果ポリシー
    integration_status.py  # 統合ステータス統一ソース
    main_api.py         # ウィンドウ API
    settings.py         # 設定ページビルダー
    tray.py             # システムトレイ
    modes/              # 表示モード
      bubble.py           # フローティングバブルモード
      live2d.py           # Live2D キャラクターモード
  core/               # コアランタイム（HTTP 非公開）
    runtime.py          # Hermes ランタイムラッパー
    state.py            # タスク状態管理
    executor.py         # 実行戦略（シミュレーション / Hermes CLI）
    task_runner.py      # タスクスケジューリングポーラー
  bridge/             # 内部通信ブリッジ
    server.py           # FastAPI サーバー（再起動可能）
    deps.py             # 依存性注入
    routes/             # API ルート
  locald/             # ローカル機能アダプター
    screenshot.py       # スクリーンショット (macOS)
    active_window.py    # アクティブウィンドウ (macOS)
  installer/          # Hermes インストールガイド
    hermes_check.py     # インストール検出
    hermes_install.py   # インストール実行
    workspace_init.py   # ワークスペース初期化
packages/
  protocol/           # クロスレイヤーデータ定義
    enums.py            # 列挙型
    schemas.py          # リクエスト/レスポンスモデル
    install.py          # インストールモデル
integrations/
  astrbot-plugin/     # QQ ブリッジプラグイン
    main.py             # エントリポイントと ACL
    command_router.py   # コマンドルーティング
    api_client.py       # HTTP クライアント
    handlers/           # コマンドハンドラー
tests/                # テストスイート（105 テスト）
```

## 🔧 開発ガイド

### 厳格な境界

| モジュール | 許可 | 禁止 |
|----------|------|------|
| `apps/core` | ランタイム、状態、エグゼキューター | HTTP の公開 |
| `apps/bridge` | 内部 API、DI | ビジネスロジックの実装 |
| `apps/shell` | プロダクトエントリ、UI、設定 | Bridge 外の状態アクセス |
| `apps/locald` | プラットフォームアダプター | ビジネスロジック |
| `astrbot-plugin` | コマンドルーティング、フォーマット | ローカルマシン制御 |

### 新機能の追加

1. **新しいローカル機能** → `apps/locald/` にアダプター追加 → `apps/bridge/routes/` でエンドポイント公開
2. **新しいタスクタイプ** → `packages/protocol/enums.py` に列挙型追加 → `apps/core/state.py` で処理
3. **新しい表示モード** → `apps/shell/modes/` に実装 → `startup.py` で統合

## 📋 ロードマップ

- [ ] Live2D Cubism SDK レンダラー統合
- [ ] HermesExecutor 実機 CLI テスト
- [ ] Hapi Codex バックエンド連携
- [ ] タスク永続化（現在はメモリ内ストレージ）
- [ ] クロスプラットフォーム対応（Windows / Linux）
- [ ] AstrBot 実環境 QQ テスト
- [ ] Bridge HTTPS + 認証
- [ ] デスクトップシェル技術アップグレード（pywebview 置換）

## 📄 ライセンス

MIT
