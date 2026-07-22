<div align="center">

# Oha-Yachiyo

デスクトップファーストのローカルパーソナルエージェントアプリケーション

リポジトリ内の Native Agent runtime を中心に、八千代をデスクトップアシスタント、フローティングバブル、Live2D キャラクターとして常駐させます。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-pytest%20suite-brightgreen.svg)](#テスト)

**[English](README.en.md)** | **[中文](README.md)** | **日本語**

</div>

---

## はじめに

Oha-Yachiyo はまだソース開発形態です。すべての環境向けの通常のデスクトップインストーラーではありません。

ソースから実行するには次が必要です。

- Python 3.11 以上
- Node.js 20.19 以上
- npm
- Git

`oha-yachiyo` コマンドは Electron + React フロントエンドと Python バックエンドを起動します。フロントエンド依存がない場合、ランチャーは `apps/frontend/node_modules` をインストールできますが、Node.js 本体はインストールしません。

## できること

Oha-Yachiyo はホスト型チャットページではなく、ローカルデスクトップシェルです。

- ダッシュボード: Native Agent readiness、Model Profiles、会話、ツール、設定、バックアップ、アンインストール。
- Chat Window: ChatSession と TaskRunner に接続された完全な会話画面。
- Bubble モード: 共通 Chat Window を開く軽量デスクトップ入口。
- Live2D モード: ローカルリソースを取り込めるキャラクター型デスクトップ入口。
- Local Bridge: フロントエンドと任意の AstrBot 連携向けのループバック専用 HTTP API。

実行経路:

```text
Chat UI / Bridge
-> AppRuntime / AppState
-> TaskRunner
-> NativeAgentExecutor
-> NativeRunEngine
-> Model Profiles / ToolBroker / PolicyGate / ApprovalCoordinator / RunEvent
```

Task は製品レベルのタスク契約です。Run は Native Agent の実行記録です。NativeAgentExecutor が Task と Run の対応を管理します。

## クイックスタート

```bash
git clone <repo-url>
cd oha-yachiyo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

テストや開発ツールも入れる場合:

```bash
pip install -e ".[dev]"
```

デスクトップアプリを起動:

```bash
oha-yachiyo
```

バックエンドのみの開発:

```bash
oha-yachiyo-backend
```

## 初回起動

初回起動では、本機設定とモデル設定を完了してから主控台に入ります。

```text
モデルソース / デフォルト Chat モデルを設定
  -> Oha-Yachiyo ワークスペースを初期化
  -> 必要に応じて Live2D / TTS リソースを導入
  -> ダッシュボードへ
```

モデル未設定時、Chat と Agent Run は構造化された `native_agent_not_ready / model_profile_required` エラーを返します。外部実行カーネルは不要です。

よくある確認点:

- macOS で未知の開発元 / Gatekeeper により初回起動が止まる場合: Finder で `Oha-Yachiyo.app` を Control クリックして「開く」を選ぶか、システム設定の「プライバシーとセキュリティ」で許可します。
- モデル接続に失敗する: Base URL、モデル名、API Key を確認します。
- Bridge に接続できない: デスクトップバックエンドが起動しており、ローカルポートが空いているか確認します。
- macOS でスクリーンショットが使えない: Oha-Yachiyo に画面収録権限を付与します。

## ローカルデータ

主なユーザースコープのパス:

```text
~/.oha-yachiyo/
~/.oha-yachiyo-config/
```

ローカルデータをリセットする前に、これらのパスをバックアップしてください。

## Live2D リソース

Live2D アセットは任意で、メインリポジトリには含めません。

リソース release:

<https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases>

推奨パス:

```text
~/.oha-yachiyo/assets/live2d/
```

ダッシュボードからリソース ZIP を取り込むか、モデルディレクトリを選択できます。詳細は [docs/live2d-assets.md](docs/live2d-assets.md) を参照してください。

## 八千代 GPT-SoVITS 音色リソース

八千代 GPT-SoVITS 音色パッケージはアプリ DMG とは別に公開します。

<https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/tag/tts-assets-yachiyo-gpt-sovits-v4>

プロアクティブケア / デスクトップ観察ページから `Oha-Yachiyo-yachiyo-gpt-sovits-v4.zip` を取り込みます。このパッケージには音色重みと参考音声のみが含まれ、GPT-SoVITS API サービス本体はユーザーがローカルで起動します。詳細は [docs/tts-voice-assets.md](docs/tts-voice-assets.md) を参照してください。

## 任意の QQ / AstrBot ブリッジ

AstrBot プラグインは QQ コマンドをローカル Bridge に転送します。プラグイン自体はローカルマシン制御を実装しません。

| コマンド | 説明 |
|---------|------|
| `/y status` | 状態を表示 |
| `/y tasks` | タスク一覧 |
| `/y do <説明>` | タスクを作成 |
| `/y check <id>` | タスク詳細 |
| `/y cancel <id>` | タスクをキャンセル |
| `/y screen` | スクリーンショット情報 |
| `/y window` | アクティブウィンドウ情報 |
| `/y help` | ヘルプ |

## プロジェクト構成

```text
apps/
  frontend/           Electron + React/Vite/TypeScript フロントエンド
  desktop_backend/    ヘッドレス Python バックエンド入口
  desktop_launcher.py ソース開発ランチャー
  shell/              設定、Native runtime、デスクトップバックエンド UI アダプター
  core/               AppRuntime、タスク状態、チャット状態
  bridge/             ローカル FastAPI Bridge
  locald/             スクリーンショット、アクティブウィンドウアダプター
  installer/          ワークスペース初期化、バックアップ、復元、アンインストール
packages/
  protocol/           クロスレイヤーデータモデル
integrations/
  astrbot-plugin/     QQ ブリッジプラグイン
tests/                pytest スイート
docs/                 アーキテクチャとリソース文書
```

## 開発コマンド

```bash
source .venv/bin/activate
source ~/.nvm/nvm.sh
nvm use 20.19.0

npm --prefix apps/frontend run build
pytest -q
oha-yachiyo
```

## テスト

```bash
pip install -e ".[dev]"
pytest -q
```

主な対象は protocol model、AppState、TaskRunner、NativeAgentExecutor、NativeRunEngine、Chat API、Bridge routes、Model Profiles、approval flow、Workflow、release guard、frontend feature-preservation contract です。

## パッケージング方針

リリースパッケージは、グローバル Python、Node.js、編集可能な checkout に依存しない形にします。macOS では React renderer をビルドし、Python backend を `oha-yachiyo-backend` として凍結し、Electron に同梱し、リリース成果物を product identity と security regression の観点で検査します。

## ライセンス

MIT
