# Banner Engine - ソフトウェア開発仕様書

**バージョン:** 1.0.0
**最終更新:** 2026-03-11
**技術スタック:** FastAPI + htmx + Jinja2 + Nano Banana Pro
**デプロイ:** Vercel
**AI連携:** Gemini API

---

## 目次

1. [システム概要](#1-システム概要)
2. [システムアーキテクチャ](#2-システムアーキテクチャ)
3. [XMLテンプレート仕様](#3-xmlテンプレート仕様)
4. [UI/UX設計](#4-uiux設計)
5. [Nano Banana Pro連携仕様](#5-nano-banana-pro連携仕様)
6. [データモデル・API設計](#6-データモデルapi設計)
7. [スロットエディタ・コンポーネント設計](#7-スロットエディタコンポーネント設計)
8. [FastAPI + htmx アーキテクチャ詳細設計](#8-fastapi--htmx-アーキテクチャ詳細設計)
9. [テスト・品質保証計画](#9-テスト品質保証計画)
10. [セキュリティ・デプロイメント計画](#10-セキュリティデプロイメント計画)
11. [開発ロードマップ・運用計画](#11-開発ロードマップ運用計画)
12. [Gemini API連携仕様](#12-gemini-api連携仕様)
13. [対応カテゴリ仕様](#13-対応カテゴリ仕様)
14. [CI/CD パイプライン設計](#14-cicd-パイプライン設計)

---

## 1. システム概要

### 1.1 目的

本システムは、画像生成エンジン **Nano Banana Pro** を活用し、XMLテンプレートに基づいてバナー画像を動的に生成するWebアプリケーションである。デザインの専門知識を持たないユーザーでも、あらかじめ用意されたテンプレートを選択・編集するだけで、品質の均一なバナー画像を短時間で作成・出力できる環境を提供することを目的とする。

### 1.2 対象ユーザー

| ユーザー区分 | 説明 |
|---|---|
| コンテンツクリエイター | マーケティング担当者・EC運営担当者など、デザインツールの専門知識を持たずにバナーを量産したいユーザー |
| デザイン監修者 | テンプレートXMLを管理・追加するデザイナーやシステム管理者 |
| 開発・運用担当者 | システムの構成管理・テンプレートのメンテナンスを行うエンジニア |

### 1.3 主要機能

#### 1.3.1 テンプレート選択機能
- カテゴリ一覧からバナーカテゴリを選択する（中古自動車、ドレッシング、文房具、アパレル、動物支援ファンディング、ラーメン屋等）
- カテゴリ内の複数パターン（XMLで定義済み）をサムネイル形式で一覧表示する
- パターンのメタ情報（サイズ、アスペクト比、レイアウトタイプ、推奨用途）を確認できる
- テンプレートは管理画面から追加・更新・削除が可能

#### 1.3.2 バナー編集機能
- 選択したテンプレートのスロット（テキスト・画像・ボタン）をUI上で編集する
- 各スロットに対して以下のパラメータを設定可能
  - テキストスロット：文字列、フォントサイズ、文字色、配置位置（x/y/width/height）
  - 画像スロット：画像ファイルのアップロード、トリミング・フィット設定
  - ボタンスロット：ラベルテキスト、背景色、文字色、リンクURL
- テンプレートの `rules` セクションに基づくバリデーションをリアルタイムで実施する

#### 1.3.3 Gemini API連携（ログイン時UIデータ設定）
- ユーザーログイン時にGemini APIを呼び出し、UIデータを動的に設定する
- テンプレート推薦、テキストコピー提案、配色最適化をAIが支援する

#### 1.3.4 プレビュー機能
- 編集内容をサーバーサイドSVGレンダリングでリアルタイムプレビュー表示する
- htmxによる部分更新（300msデバウンス）で即時フィードバックを実現

#### 1.3.5 バナー生成・出力機能
- Nano Banana Proエンジンに対して生成リクエストを送信する
- 生成完了後、指定フォーマット（PNG / JPEG / WebP）でダウンロード可能とする

#### 1.3.6 テンプレート管理機能（管理者向け）
- XMLテンプレートのアップロード・更新・削除を行う管理画面を提供する
- テンプレートのバリデーション（XMLスキーマチェック）を実施する
- 新カテゴリ・新パターンの追加が随時可能

---

## 2. システムアーキテクチャ

### 2.1 全体構成概要

```
┌─────────────────────────────────────────────────────────────┐
│                     クライアント層                            │
│            ブラウザ (htmx + Jinja2テンプレート)               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ テンプレート  │  │  バナー編集  │  │  SVGプレビュー   │  │
│  │ 選択UI       │  │  フォームUI  │  │  キャンバス      │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTPS (htmx部分更新)
                            │
┌───────────────────────────▼─────────────────────────────────┐
│              Vercel Serverless Functions                      │
│                   FastAPI (Python)                            │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ テンプレート │  │  バナー生成  │  │  認証・認可      │   │
│  │ API         │  │  オーケスト  │  │  ミドルウェア    │   │
│  │             │  │  レーター    │  │                  │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ XMLパーサー │  │  SVGレンダラ │  │  Gemini API      │   │
│  │ (defusedxml)│  │  (プレビュー)│  │  クライアント    │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
└──────────┬────────────────┬──────────────┬──────────────────┘
           │                │              │
           ▼                ▼              ▼
    ┌──────────┐  ┌─────────────┐  ┌──────────────┐
    │PostgreSQL│  │Nano Banana  │  │ Gemini API   │
    │(Vercel   │  │Pro          │  │ (Google)     │
    │ Postgres)│  │(画像生成)   │  │              │
    └──────────┘  └─────────────┘  └──────────────┘
           │
    ┌──────┴──────┐
    │ Vercel Blob │
    │ Storage     │
    │ (画像保存)  │
    └─────────────┘
```

### 2.2 技術スタック

| レイヤー | 技術 | 選定理由 |
|---|---|---|
| バックエンド | FastAPI (Python 3.12+) | 高速・型安全・非同期対応 |
| フロントエンド | htmx 2.x + Jinja2 | SPAなしでリアルタイム部分更新、シンプルな構成 |
| スタイリング | Tailwind CSS | ユーティリティクラスによる迅速なUI構築 |
| XMLパース | defusedxml | XXE攻撃対策済みの安全なXMLパーサー |
| プレビュー | サーバーサイドSVG生成 | htmxとの高い親和性、フォント描画精度 |
| データベース | PostgreSQL (Vercel Postgres) | Vercelネイティブ統合 |
| ファイルストレージ | Vercel Blob Storage | サーバーレス環境でのファイル管理 |
| 画像生成エンジン | Nano Banana Pro | バナー画像合成のコアエンジン |
| AI連携 | Gemini API | ログイン時UIデータ設定・コピー提案 |
| デプロイ | Vercel | GitHub連携自動デプロイ・エッジネットワーク |
| CI/CD | GitHub Actions + Vercel | 自動テスト・リント・デプロイ |

### 2.3 データフロー概要

```
[1] ユーザーログイン
    → Gemini API呼び出し → UIデータ設定（テンプレート推薦・パーソナライズ）

[2] テンプレート選択
    → hx-get でテンプレート詳細をパーシャルHTML取得
    → エディタ画面を部分更新

[3] バナー編集
    → hx-patch でスロット値をサーバーに送信（300msデバウンス）
    → サーバーサイドSVG生成 → プレビューキャンバスを部分更新

[4] バナー生成
    → hx-post でNano Banana Pro生成リクエスト
    → SSEで進捗表示 → 完了後ダウンロードリンク表示
```

---

## 3. XMLテンプレート仕様

### 3.1 概要

バナー作成アプリケーションのテンプレートは、XMLフォーマットで定義される。各テンプレートはカテゴリ・パターン単位で管理され、バナーのレイアウト・デザイン・スロット構成・バリデーションルールを一元的に記述する。テンプレートは随時追加可能。

### 3.2 ファイル構成とルートエレメント

```
/templates/
  {category}/
    {category}_{pattern_id}.xml
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<banner_templates category="{カテゴリ名}">
  <banner_template>
    <meta>...</meta>
    <design>...</design>
    <slots>...</slots>
    <rules>...</rules>
  </banner_template>
</banner_templates>
```

### 3.3 `<meta>` エレメント仕様

| 要素 | 必須 | 型 | 説明 |
|---|---|---|---|
| `category` | 必須 | string | カテゴリ識別子 |
| `pattern_id` | 必須 | string | パターン一意識別子 |
| `pattern_name` | 必須 | string | パターン名（日本語可、最大50文字） |
| `size` | 必須 | 要素 | width, height, unit を含む |
| `aspect_ratio` | 必須 | string | アスペクト比 |
| `layout_type` | 必須 | enum | `full_background`, `grid`, `copy_focused`, `brand_message` |
| `recommended_use` | 任意 | string | 推奨ユースケース |

### 3.4 `<design>` エレメント仕様

| 要素 | 必須 | 説明 |
|---|---|---|
| `background` | 必須 | type属性: `image`, `color`, `gradient` |
| `overlay` | 任意 | opacity (0.0-1.0), color (#RRGGBB) |
| `primary_color` | 必須 | メインテキスト色 (#RRGGBB) |
| `accent_color` | 任意 | 強調色 (#RRGGBB) |
| `font_style` | 必須 | フォント系統 |
| `highlight_panel` | 任意 | テキスト背景パネル設定 |
| `illustration_style` | 任意 | イラスト装飾スタイル |

### 3.5 `<slots>` エレメント仕様

#### スロットタイプ定義

| タイプ | 説明 | 固有属性 |
|---|---|---|
| `image` | 画像配置領域 | format |
| `text` | テキスト入力領域 | max_chars, font_size_guideline, font_weight, color |
| `button` | ボタン要素 | default_label, bg_color, text_color |
| `image_or_text` | 画像/テキスト選択型 | image + text の両属性セット |

#### 共通属性

| 属性 | 必須 | 型 | 説明 |
|---|---|---|---|
| `id` | 必須 | string | スロット識別子（テンプレート内一意） |
| `type` | 必須 | enum | スロット種別 |
| `x` | 必須 | float | 左端位置（%） |
| `y` | 必須 | float | 上端位置（%） |
| `width` | 必須 | float | 幅（%） |
| `height` | 必須 | float | 高さ（%） |
| `description` | 任意 | string | 用途説明 |
| `required` | 必須 | boolean | 入力必須フラグ |

### 3.6 座標・サイズ指定ルール（%指定方式）

```
実際のX (px) = slot/@x     / 100 * banner_width  (px)
実際のY (px) = slot/@y     / 100 * banner_height (px)
実際の幅 (px) = slot/@width  / 100 * banner_width  (px)
実際の高 (px) = slot/@height / 100 * banner_height (px)
```

- 原点 `(0, 0)` はバナー左上
- `x + width <= 100.0` かつ `y + height <= 100.0`
- スロット重複は許容（XMLドキュメント順で後出が前面）

### 3.7 `<rules>` エレメント仕様

| ルールタイプ | 説明 |
|---|---|
| `required_slot` | 対象スロットへの入力必須 |
| `max_chars` | テキストの最大文字数 |
| `min_chars` | テキストの最小文字数 |
| `image_aspect_ratio` | 画像アスペクト比推奨 |
| `image_min_resolution` | 画像の最小解像度 |
| `color_contrast` | WCAG準拠コントラスト比 |
| `slot_dependency` | スロット間の依存関係 |
| `exclusive_slots` | 排他スロット指定 |

### 3.8 テンプレート拡張ルール

- **新カテゴリ追加**: `/templates/` 配下に新ディレクトリを作成
- **新パターン追加**: 既存カテゴリに `{category}_{連番}.xml` を追加
- **改版**: 非互換変更は新 `pattern_id` で追加、旧パターンに `deprecated="true"` をマーク
- **管理画面**: XMLアップロード + スキーマバリデーション + プレビュー確認

### 3.9 バリデーションルール

- **スキーマバリデーション**: XSDに対するXMLスキーマ検証（CI/CD + アプリ起動時）
- **構造バリデーション**: 要素一意性、座標範囲、カラーコード形式
- **コンテンツバリデーション**: 文字数制限、必須チェック、画像形式チェック
- **ERROR**: 書き出しブロック / **WARNING**: 警告表示のみ

---

## 4. UI/UX設計

### 4.1 画面一覧と遷移図

```
[アプリ起動・ログイン]
     │ Gemini API → UIデータ設定
     ▼
┌─────────────────────────┐
│  テンプレート選択画面    │  カテゴリフィルタ + サムネイル一覧
└────────────┬────────────┘
             │ テンプレート選択 (hx-get)
             ▼
┌─────────────────────────┐
│  バナーエディタ画面      │  キャンバス + スロット編集パネル
│  (3ペイン構成)          │  ドラッグ&ドロップ対応
└────────────┬────────────┘
             │ 「プレビュー・出力」ボタン
             ▼
┌─────────────────────────┐
│  プレビュー・出力画面    │  フルサイズプレビュー + ダウンロード
└─────────────────────────┘
```

### 4.2 テンプレート選択画面

| 項目 | 仕様 |
|---|---|
| カテゴリフィルタ | 左サイドバー（200px）、シングルセレクト |
| キーワード検索 | インクリメンタルサーチ（300msデバウンス） |
| サムネイルカード | 240x200px、ホバーで拡大 + オーバーレイ |
| グリッドレイアウト | 4カラム(1600px+) / 3カラム(1200px+) / 2カラム(768px+) / 1カラム |
| 選択時 | htmx部分更新でエディタ画面へ遷移 |

### 4.3 バナーエディタ画面（3ペイン構成）

```
┌──────────────────────┬─────────────────────────┬────────────────────┐
│  左パネル (240px)    │   キャンバスエリア       │  右サイドバー(320px)│
│  スロット一覧        │   SVGプレビュー          │  スロット編集パネル │
│  ・表示/非表示       │   ズーム: 25%-400%      │  ・テキスト編集     │
│  ・Z-index変更       │   スナップガイド        │  ・画像アップロード │
│  ・ロック機能        │   ドラッグ&ドロップ     │  ・色/フォント設定  │
└──────────────────────┴─────────────────────────┴────────────────────┘
```

#### スロットタイプ別編集UI

- **テキスト**: テキスト入力、フォントサイズスライダー、色ピッカー、太字切替、文字数カウンタ
- **画像**: ドラッグ&ドロップアップロード、フィット方法選択（cover/contain/fill）
- **ボタン**: ラベル編集、背景色/文字色ピッカー、角丸設定
- **image_or_text**: タイプ切替トグル + 対応エディタ表示

#### ドラッグ&ドロップ仕様

| 項目 | 仕様 |
|---|---|
| 移動 | スロット枠内をドラッグ、キーボード矢印キー対応 |
| スナップ | グリッド（5%単位）+ 他スロット端/中央ガイドライン |
| リサイズ | 8点ハンドル、Shift押下でアスペクト比固定 |
| Undo/Redo | Ctrl+Z / Ctrl+Y（最大50件） |

### 4.4 レスポンシブ対応

| 画面幅 | エディタ対応 |
|---|---|
| lg (1200px+) | 3ペイン通常レイアウト |
| md (768px+) | 左パネル折りたたみ、右サイドバーはボトムシート |
| sm/xs (~767px) | キャンバス全幅 + 下部タブパネル（機能制限モード） |

### 4.5 アクセシビリティ

- **WCAG 2.1 レベル AA** 準拠目標
- コントラスト比 4.5:1 以上
- 全操作のキーボード対応
- `aria-live` によるスクリーンリーダー通知
- フォーカストラップ（モーダル内）

---

## 5. Nano Banana Pro連携仕様

### 5.1 連携アーキテクチャ

```
クライアント → FastAPI → Nano Banana Pro API → 画像ストレージ
                  │
                  ├─ POST /v1/render（ジョブ投入）
                  ├─ GET  /v1/render/{job_id}（ステータス確認）
                  └─ GET  /v1/render/{job_id}/result（画像取得）
```

### 5.2 レンダリング指示JSONフォーマット

```json
{
  "schema_version": "1.0",
  "canvas": {
    "width": 1200,
    "height": 630,
    "background_color": "#FFFFFF",
    "format": "png",
    "quality": 95,
    "dpi": 144
  },
  "layers": [
    {
      "layer_id": "slot_bg_image",
      "type": "image",
      "z_index": 0,
      "position": { "x": 0, "y": 0 },
      "size": { "width": 1200, "height": 630 },
      "image": {
        "source_url": "https://...",
        "fit": "cover",
        "opacity": 1.0
      }
    },
    {
      "layer_id": "slot_headline",
      "type": "text",
      "z_index": 20,
      "position": { "x": 60, "y": 200 },
      "size": { "width": 700, "height": 100 },
      "text": {
        "content": "キャッチコピー",
        "font_family": "NotoSansJP",
        "font_size": 56,
        "font_weight": "bold",
        "color": "#1A1A1A"
      }
    }
  ]
}
```

### 5.3 画像出力仕様

| フォーマット | 用途 | 品質 |
|---|---|---|
| PNG | Web・透過あり | 非可逆圧縮なし（デフォルト推奨） |
| JPG | SNS広告・ファイルサイズ優先 | quality: 85-95 |
| WebP | 次世代Web配信 | quality: 85-95 |

推奨DPI: **144**（@2x HiDPI対応）

### 5.4 二段階レンダリング

| 項目 | フロントエンドSVGプレビュー | Nano Banana Pro最終レンダリング |
|---|---|---|
| 目的 | 編集中の即時フィードバック | 高品質出力 |
| 遅延 | ~50ms（サーバーSVG生成） | 2-15秒 |
| トリガー | スロット編集（300msデバウンス） | 「書き出し」ボタン押下 |

### 5.5 エラーハンドリング・リトライ

- 指数バックオフ: 1s → 2s → 4s（最大3回、ジッター±20%）
- サーキットブレーカー: 60秒間5回エラーで遮断、30秒後に試行
- ファイルサイズ超過時: quality自動引き下げ（-5ずつ、最小60）

---

## 6. データモデル・API設計

### 6.1 データベーススキーマ

#### users テーブル
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) NOT NULL UNIQUE,
  display_name VARCHAR(100) NOT NULL,
  avatar_url TEXT,
  role VARCHAR(20) NOT NULL DEFAULT 'user',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);
```

#### templates テーブル
```sql
CREATE TABLE templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pattern_id VARCHAR(100) NOT NULL UNIQUE,
  pattern_name VARCHAR(255) NOT NULL,
  category VARCHAR(100) NOT NULL,
  size_width INTEGER NOT NULL,
  size_height INTEGER NOT NULL,
  thumbnail_url TEXT,
  xml_content TEXT NOT NULL,
  design_meta JSONB NOT NULL DEFAULT '{}',
  slot_summary JSONB NOT NULL DEFAULT '[]',
  is_published BOOLEAN NOT NULL DEFAULT false,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);
```

#### projects テーブル
```sql
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  template_id UUID NOT NULL REFERENCES templates(id),
  title VARCHAR(255) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 1,
  last_edited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);
```

#### slot_edits テーブル
```sql
CREATE TABLE slot_edits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  slot_id VARCHAR(100) NOT NULL,
  slot_type VARCHAR(20) NOT NULL,
  content JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (project_id, slot_id)
);
```

#### generated_images テーブル
```sql
CREATE TABLE generated_images (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  format VARCHAR(10) NOT NULL DEFAULT 'png',
  width INTEGER,
  height INTEGER,
  file_url TEXT,
  file_size_bytes BIGINT,
  error_message TEXT,
  generated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### assets テーブル
```sql
CREATE TABLE assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  original_filename VARCHAR(255) NOT NULL,
  mime_type VARCHAR(100) NOT NULL,
  file_url TEXT NOT NULL,
  thumbnail_url TEXT,
  width INTEGER,
  height INTEGER,
  file_size_bytes BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);
```

### 6.2 REST API設計

#### テンプレート系
| メソッド | エンドポイント | 説明 |
|---|---|---|
| GET | `/api/templates` | テンプレート一覧（カテゴリ・サイズフィルタ） |
| GET | `/api/templates/{id}` | テンプレート詳細 |
| GET | `/api/templates/{id}/xml` | XML本体取得 |
| GET | `/api/templates/categories` | カテゴリ一覧 |

#### プロジェクト系
| メソッド | エンドポイント | 説明 |
|---|---|---|
| GET | `/api/projects` | プロジェクト一覧 |
| POST | `/api/projects` | 新規作成 |
| GET | `/api/projects/{id}` | 詳細取得 |
| PATCH | `/api/projects/{id}` | 更新 |
| DELETE | `/api/projects/{id}` | 削除（論理） |
| PUT | `/api/projects/{id}/slots` | 全スロット一括保存 |
| PATCH | `/api/projects/{id}/slots/{slotId}` | 個別スロット更新 |

#### アセット系
| メソッド | エンドポイント | 説明 |
|---|---|---|
| POST | `/api/assets/upload` | 画像アップロード |
| GET | `/api/assets` | アセット一覧 |
| DELETE | `/api/assets/{id}` | 削除 |

#### バナー生成系
| メソッド | エンドポイント | 説明 |
|---|---|---|
| POST | `/api/projects/{id}/generate` | 生成ジョブ起動 |
| GET | `/api/generate/progress/{jobId}` | SSE進捗ストリーム |
| GET | `/api/generated-images/{id}` | 生成画像詳細 |

### 6.3 認証・認可

- セッションベース認証（ブラウザ向け）
- JWT Bearer認証（API連携向け、RS256）
- ロール: `user`（自分のリソースCRUD）/ `admin`（全リソース管理）
- リソースオーナーシップによるアクセス制御

---

## 7. スロットエディタ・コンポーネント設計

### 7.1 コンポーネントツリー

```
<BannerEditorPage>
├── <BannerCanvas>                    # SVGプレビュー領域
│   ├── <CanvasBackground>
│   └── <SlotLayer>
│       └── <SlotOverlay>             # 各スロットのオーバーレイ
│           ├── <ResizeHandle />      # 8方向リサイズ
│           ├── <DragHandle />        # ドラッグ移動
│           └── <SlotHighlight />     # 選択/ホバー強調
│
└── <EditorSidePanel>
    ├── <SlotList>                    # スロット一覧
    └── <SlotEditor>                  # 選択中スロット編集
        ├── <TextSlotEditor />
        ├── <ImageSlotEditor />
        ├── <ButtonSlotEditor />
        └── <ImageOrTextSlotEditor />
```

### 7.2 状態管理（セッションベース）

FastAPI + htmxアーキテクチャでは、スロット編集状態はサーバーサイドセッションで管理する：

```python
session["slots_{template_id}"] = {
  "slot_id": "value",
  ...
}
session["svg_cache_{template_id}"] = {
  "key": "hash",
  "svg": "svg_string"
}
```

### 7.3 バリデーション

| ルール | 対象 | エラー種別 |
|---|---|---|
| `REQUIRED_EMPTY` | 全タイプ | ERROR |
| `MAX_CHARS_EXCEEDED` | text | ERROR |
| `IMAGE_REQUIRED` | image | ERROR |
| `LOW_CONTRAST` | button | WARNING |
| `OUT_OF_BOUNDS` | 全タイプ | ERROR |

---

## 8. FastAPI + htmx アーキテクチャ詳細設計

### 8.1 ディレクトリ構造

```
bannerengine/
├── api/
│   └── index.py                       # Vercel Serverless Functions エントリポイント
├── app/
│   ├── main.py                        # FastAPIアプリケーション
│   ├── config.py                      # 設定管理
│   ├── routers/
│   │   ├── pages.py                   # ページ全体レンダリング
│   │   ├── templates.py               # テンプレート一覧・詳細
│   │   ├── slots.py                   # スロット編集・更新
│   │   ├── preview.py                 # プレビュー生成
│   │   ├── generate.py                # バナー画像生成
│   │   └── assets.py                  # 画像アップロード
│   ├── services/
│   │   ├── template_service.py
│   │   ├── slot_service.py
│   │   ├── preview_service.py
│   │   ├── banner_service.py
│   │   └── gemini_service.py          # Gemini API連携
│   ├── core/
│   │   ├── xml_parser.py              # defusedxml使用
│   │   ├── svg_renderer.py            # サーバーサイドSVG生成
│   │   └── exceptions.py
│   ├── models/
│   │   ├── template.py
│   │   ├── slot.py
│   │   └── banner.py
│   └── templates/                     # Jinja2テンプレート
│       ├── base.html
│       ├── pages/
│       │   ├── index.html
│       │   └── editor.html
│       ├── partials/                  # htmx swap用
│       │   ├── template_card.html
│       │   ├── slot_editor.html
│       │   ├── preview_canvas.html
│       │   └── generate_result.html
│       └── components/
│           └── slot_types/
│               ├── text_slot.html
│               ├── image_slot.html
│               ├── button_slot.html
│               └── image_or_text_slot.html
├── static/
│   ├── css/
│   ├── js/
│   │   ├── htmx.min.js
│   │   └── htmx-ext-sse.js
│   └── uploads/
├── xml_templates/                     # バナーXMLテンプレート
├── tests/
├── vercel.json
├── requirements.txt
└── pyproject.toml
```

### 8.2 Vercelデプロイ設定

```json
// vercel.json
{
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/static/(.*)",
      "dest": "/static/$1"
    },
    {
      "src": "/(.*)",
      "dest": "/api/index.py"
    }
  ]
}
```

```python
# api/index.py - Vercel Serverless Functions エントリポイント
from app.main import app
```

### 8.3 htmxインタラクション設計

#### テンプレート選択
```html
<div class="template-card"
  hx-get="/api/templates/{{ template.id }}"
  hx-target="#template-detail-panel"
  hx-swap="innerHTML"
  hx-push-url="/editor/{{ template.id }}">
</div>
```

#### スロット編集（リアルタイムプレビュー）
```html
<input type="text" name="{{ slot.id }}"
  hx-patch="/api/slots/{{ template_id }}/{{ slot.id }}"
  hx-target="#preview-canvas"
  hx-swap="outerHTML"
  hx-trigger="input changed delay:300ms">
```

#### 画像生成（SSE進捗表示）
```html
<div hx-ext="sse"
  sse-connect="/api/generate/progress/{{ job_id }}"
  sse-swap="message">
</div>
```

#### OOB swap（複数領域同時更新）
- プレビュー更新 + バリデーションエラー表示 + トースト通知を1レスポンスで同時更新

### 8.4 サーバーサイドSVG生成

```python
# app/core/svg_renderer.py
from xml.etree import ElementTree as ET

class SvgRenderer:
    def render(self, template, slot_values: dict) -> str:
        svg = ET.Element("svg", {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": str(template.meta.width),
            "height": str(template.meta.height),
            "viewBox": f"0 0 {template.meta.width} {template.meta.height}",
        })
        # 背景描画
        ET.SubElement(svg, "rect", {
            "width": "100%", "height": "100%",
            "fill": template.design.background_color,
        })
        # 各スロット描画
        for slot in template.slots:
            value = slot_values.get(slot.id, slot.default_value)
            self._render_slot(svg, slot, value, template)
        return ET.tostring(svg, encoding="unicode")
```

---

## 9. テスト・品質保証計画

### 9.1 テスト戦略

| テストレイヤー | 目的 | 主要ツール | カバレッジ目標 |
|---|---|---|---|
| ユニットテスト | 個々の関数・クラスの正確性検証 | pytest | 85%以上 |
| 統合テスト | モジュール間連携・外部サービス連携 | pytest + httpx | 主要フロー100% |
| E2Eテスト | ブラウザ上での実操作シナリオ検証 | Playwright | クリティカルパス100% |
| パフォーマンステスト | 応答速度・スループットの検証 | Locust | SLA基準値充足 |
| セキュリティテスト | 脆弱性・不正入力への耐性検証 | Bandit + OWASP ZAP | 重大・高リスク0件 |

**テスト方針:**
- テストファースト原則（実装前にテストケース定義）
- CI/CD統合（PRごとに自動テスト実行）
- テストデータは `tests/fixtures/` で一元管理
- Nano Banana Pro / Gemini APIはモックで代替

### 9.2 ユニットテスト

#### 9.2.1 XMLパーサーテスト（12件）

| テストID | テストケース | 期待結果 |
|---|---|---|
| UT-XML-001 | 正常なXMLテンプレートのパース | スロットオブジェクトリストが正しく生成 |
| UT-XML-002 | `image`スロットの属性取得 | 幅・高さ・座標が正確に取得 |
| UT-XML-003 | `text`スロットの属性取得 | フォント・文字数上限が正確に取得 |
| UT-XML-004 | `button`スロットの属性取得 | URL・ラベルデフォルト値が正確に取得 |
| UT-XML-005 | `image_or_text`スロットの属性取得 | サブタイプとして適切に分類 |
| UT-XML-006 | 必須属性の欠落 | `XMLParseError`がraise |
| UT-XML-007 | 未知のスロットタイプ | `UnknownSlotTypeError`がraise |
| UT-XML-008 | 不正なXML形式 | `XMLParseError`がraise |
| UT-XML-009 | 空のXMLファイル | `XMLParseError`がraise |
| UT-XML-010 | スロットが0件のXML | 空リストが返される |
| UT-XML-011 | スロット順序の保持 | XML定義順でリスト生成 |
| UT-XML-012 | Unicode文字列の扱い | 文字化けなくパース |

#### 9.2.2 スロットバリデーションテスト（14件）

| テストID | テストケース | 期待結果 |
|---|---|---|
| UT-VAL-001 | テキスト: 正常な文字列 | バリデーション通過 |
| UT-VAL-002 | テキスト: 文字数超過 | `ValidationError` |
| UT-VAL-003 | テキスト: 空文字列（必須） | `ValidationError` |
| UT-VAL-004 | テキスト: 空文字列（任意） | バリデーション通過 |
| UT-VAL-005 | 画像: 許可形式（JPEG） | バリデーション通過 |
| UT-VAL-006 | 画像: 許可形式（PNG） | バリデーション通過 |
| UT-VAL-007 | 画像: 不許可形式（GIF） | `ValidationError` |
| UT-VAL-008 | 画像: ファイルサイズ超過 | `ValidationError` |
| UT-VAL-009 | ボタン: 有効URL | バリデーション通過 |
| UT-VAL-010 | ボタン: `javascript:`スキーム | `ValidationError` |
| UT-VAL-011 | ボタン: ラベル文字数超過 | `ValidationError` |
| UT-VAL-012 | image_or_text: 画像選択時 | バリデーション通過 |
| UT-VAL-013 | image_or_text: テキスト選択時 | バリデーション通過 |
| UT-VAL-014 | image_or_text: 両方未入力 | `ValidationError` |

#### 9.2.3 APIエンドポイントテスト（12件）

| テストID | エンドポイント | シナリオ | 期待レスポンス |
|---|---|---|---|
| UT-API-001 | `GET /templates` | 正常取得 | 200 |
| UT-API-002 | `GET /templates/{id}` | 存在するID | 200 |
| UT-API-003 | `GET /templates/{id}` | 存在しないID | 404 |
| UT-API-004 | `PATCH /slots/{id}` | 有効なテキスト入力 | 200 + HTML断片 |
| UT-API-005 | `PATCH /slots/{id}` | バリデーションエラー | 422 |
| UT-API-006 | `GET /preview/{id}` | 有効なバナーID | 200 + HTML断片 |
| UT-API-007 | `POST /generate` | 有効なバナー | 202 |
| UT-API-008 | `POST /generate` | 未入力スロットあり | 422 |
| UT-API-009 | `POST /upload/image` | 有効なJPEG | 200 |
| UT-API-010 | `POST /upload/image` | 不正形式ファイル | 400 |
| UT-API-011 | `POST /upload/image` | 10MB超過 | 413 |
| UT-API-012 | `GET /preview/{id}` | 存在しないID | 404 |

#### 9.2.4 レンダリング指示データ生成テスト（8件）

| テストID | テストケース | 期待結果 |
|---|---|---|
| UT-RND-001 | 全スロット入力済み | 完全なレンダリング指示JSONが生成 |
| UT-RND-002 | テキストスロットの反映 | 文字列・座標が含まれる |
| UT-RND-003 | 画像スロットの反映 | 画像URL・リサイズ指定が含まれる |
| UT-RND-004 | ボタンスロットの反映 | リンク先URL・ラベルが含まれる |
| UT-RND-005 | image_or_text: 画像優先 | 画像が優先されたデータ生成 |
| UT-RND-006 | 任意スロット未入力 | スキップされた指示データ生成 |
| UT-RND-007 | 出力JSONスキーマ準拠 | Nano Banana Pro APIスキーマ適合 |
| UT-RND-008 | 座標・サイズの数値型 | 座標が整数型 |

### 9.3 統合テスト

#### 9.3.1 一連フローテスト（6件）

| テストID | テストケース | 検証内容 |
|---|---|---|
| IT-FLOW-001 | テンプレート選択→作成開始 | テンプレート取得→セッション作成→編集画面表示 |
| IT-FLOW-002 | テキスト編集→プレビュー反映 | PATCH→DB更新→プレビューHTML再生成 |
| IT-FLOW-003 | 画像アップロード→スロット割当 | ファイル保存→スロット更新→プレビュー反映 |
| IT-FLOW-004 | 全スロット入力→生成リクエスト | バリデーション→レンダリング指示データ→API送信 |
| IT-FLOW-005 | 複数スロット連続編集 | プレビューデータ整合性確認 |
| IT-FLOW-006 | セッション継続性 | リロード後も編集内容保持 |

#### 9.3.2 Nano Banana Pro連携テスト（7件）

| テストID | テストケース | 環境 |
|---|---|---|
| IT-NBP-001 | 正常なレンダリング指示の送信 | モック |
| IT-NBP-002 | 生成成功レスポンスの処理 | モック |
| IT-NBP-003 | APIタイムアウト時のエラーハンドリング | モック |
| IT-NBP-004 | API認証エラー（401）の処理 | モック |
| IT-NBP-005 | リトライ動作（503→503→成功） | モック |
| IT-NBP-006 | サンドボックス実リクエスト送信 | サンドボックス |
| IT-NBP-007 | 大容量画像データの送信 | サンドボックス |

### 9.4 E2Eテスト（Playwright）

#### 9.4.1 テンプレート選択フロー（5件）

| テストID | テストケース | 合格基準 |
|---|---|---|
| E2E-SEL-001 | テンプレート一覧の表示 | カードが1件以上表示 |
| E2E-SEL-002 | サムネイル表示 | 各テンプレートにサムネイル画像 |
| E2E-SEL-003 | 選択→編集画面遷移 | スロット入力フォームが表示 |
| E2E-SEL-004 | スロット構成確認 | XML定義と一致するフォーム |
| E2E-SEL-005 | テンプレート再選択 | リセット確認ダイアログ表示 |

#### 9.4.2 スロット編集操作（12件）

| テストID | テストケース | 合格基準 |
|---|---|---|
| E2E-EDIT-001 | テキスト入力 | フォームに反映 |
| E2E-EDIT-002 | 入力後プレビュー自動更新 | プレビューに入力テキスト反映 |
| E2E-EDIT-003 | 文字数カウンター更新 | リアルタイムに変化 |
| E2E-EDIT-004 | 文字数上限警告 | 警告メッセージ表示 |
| E2E-EDIT-005 | 必須スロット未入力エラー | 生成がブロック |
| E2E-EDIT-010 | JPEG画像アップロード | プレビューに画像表示 |
| E2E-EDIT-011 | PNG画像アップロード | プレビューに画像表示 |
| E2E-EDIT-012 | 不正形式ファイル拒否 | エラーメッセージ表示 |
| E2E-EDIT-013 | アップロード中ローディング | インジケーター表示 |
| E2E-EDIT-014 | ドラッグ&ドロップアップロード | アップロード完了→プレビュー更新 |
| E2E-EDIT-020 | 位置オフセット入力 | プレビュー上で位置変化 |
| E2E-EDIT-021 | ドラッグによる位置変更 | 座標入力欄が連動更新 |

#### 9.4.3 htmx部分更新テスト（6件）

| テストID | テストケース | 合格基準 |
|---|---|---|
| E2E-HTMX-001 | 部分レスポンス適用 | 対象スロット部分のみDOM更新 |
| E2E-HTMX-002 | ページ遷移なし確認 | navigationイベント未発火 |
| E2E-HTMX-003 | HX-Triggerイベント連鎖 | プレビュー自動再取得 |
| E2E-HTMX-004 | エラー時hx-swap動作 | エラーが指定ターゲットに表示 |
| E2E-HTMX-005 | hx-indicatorローディング | リクエスト中表示→完了後非表示 |
| E2E-HTMX-006 | 複数スロット同時更新の競合防止 | 各更新が独立して正しく適用 |

### 9.5 パフォーマンステスト

#### SLA目標値

| 指標 | 目標値 | 測定条件 |
|---|---|---|
| プレビュー更新（平均） | 500ms以内 | 同時10ユーザー |
| プレビュー更新（p95） | 1,000ms以内 | 同時10ユーザー |
| 画像アップロード（5MB JPEG） | 3,000ms以内 | 同時5ユーザー |
| バナー生成リクエスト受付 | 2,000ms以内 | 同時5ユーザー |
| テンプレート一覧取得 | 300ms以内 | 同時20ユーザー |
| 最大同時編集ユーザー数 | 50ユーザー | エラー率1%未満 |

### 9.6 セキュリティテスト

#### 9.6.1 XSS対策テスト（7件）

| テストID | 入力値 | 期待結果 |
|---|---|---|
| SEC-XSS-001 | `<script>alert('XSS')</script>` | HTMLエスケープ、スクリプト未実行 |
| SEC-XSS-002 | `<img src=x onerror=alert(1)>` | HTMLエスケープ、onerror未実行 |
| SEC-XSS-003 | `javascript:alert(1)` | 文字列表示、未実行 |
| SEC-XSS-004 | ボタンURLに`javascript:` | バリデーションエラー |
| SEC-XSS-005 | `{{ 7*7 }}` (Jinja2インジェクション) | テンプレート構文として未解釈 |
| SEC-XSS-006 | htmxレスポンスへのXSS埋め込み | 自動エスケープにより無害化 |
| SEC-XSS-007 | Unicodeエンコードによる回避 | 適切にエスケープ |

#### 9.6.2 ファイルアップロードテスト（9件）

| テストID | テストケース | 期待結果 |
|---|---|---|
| SEC-UPL-001 | PHPスクリプト偽装 | マジックバイト検証で拒否 |
| SEC-UPL-002 | HTMLファイル偽装 | 拒否 |
| SEC-UPL-003 | ダブル拡張子`image.jpg.php` | 拒否 |
| SEC-UPL-004 | ZIP爆弾偽装 | サイズ/コンテンツ検証で拒否 |
| SEC-UPL-005 | パストラバーサル`../` | ファイル名サニタイズ |
| SEC-UPL-006 | アップロードファイル直接実行 | ダウンロードとして返却 |
| SEC-UPL-007 | 同一名ファイル上書き攻撃 | UUIDリネームで保護 |
| SEC-UPL-008 | 10MBちょうど（境界値） | アップロード成功 |
| SEC-UPL-009 | 10MB+1byte超過 | 413エラーで拒否 |

### 9.7 受入テスト基準・リリース判定

#### リリース判定基準（全て満たすこと）

1. ユニットテスト全PASS、カバレッジ85%以上
2. 統合テスト全フローPASS
3. E2Eクリティカルパス全PASS
4. パフォーマンスSLA達成（プレビュー平均500ms以内、エラー率1%未満）
5. OWASP ZAPスキャン重大・高リスク0件
6. Critical/Highバグ0件

---

## 10. セキュリティ・デプロイメント計画

### 10.1 セキュリティ設計

#### 認証方式
- セッションベース認証（Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`）
- JWT補助認証（API連携用、RS256、有効期限15分）

#### 主要対策
| 脅威 | 対策 |
|---|---|
| XXE | defusedxml使用（標準xml.etree禁止） |
| XSS | Jinja2自動エスケープ + bleachサニタイズ |
| CSRF | 二重送信トークン方式 |
| ファイルアップロード | MIMEタイプ検証 + マジックバイト確認 + Pillow再エンコード + 10MB制限 |
| XMLインジェクション | ホワイトリスト検証 + DOM操作によるマージ |
| レート制限 | 画像生成: 10req/min/user、アップロード: 20req/h/user |
| CORS | 環境別許可リスト管理（ワイルドカード禁止） |

### 10.2 Vercelデプロイメント

#### デプロイ構成
| 項目 | 設定 |
|---|---|
| プラットフォーム | Vercel (Serverless Functions - Python Runtime) |
| フレームワーク | FastAPI |
| 静的ファイル | Vercel Edge Network |
| ファイルストレージ | Vercel Blob Storage |
| データベース | Vercel Postgres |
| 環境変数 | Vercel Environment Variables（環境別分離） |

#### 環境分離
| 環境 | ブランチ | URL |
|---|---|---|
| 開発 | feature/* | localhost:8000 |
| プレビュー | PR作成時 | 自動生成Preview URL |
| 本番 | main | bannerengine.vercel.app |

### 10.3 監視・ロギング

- 構造化JSONログ（リクエストID付与）
- セキュリティ監査ログ（認証イベント、CSRF違反等）
- Vercel Analytics統合

---

## 11. 開発ロードマップ・運用計画

### 11.1 フェーズ分け

#### Phase 1: MVP（8週間）
- テンプレート表示・選択
- スロット編集（テキスト/画像/ボタン）
- htmxリアルタイムプレビュー
- Nano Banana Pro画像生成
- 基本認証
- Gemini APIログイン時UIデータ設定

#### Phase 2: エディタ強化（12週間）
- ドラッグ&ドロップ
- アンドゥ/リドゥ
- 編集履歴・バージョン管理
- マイテンプレート保存
- 複数サイズ一括エクスポート

#### Phase 3: コラボレーション（10週間）
- 共有リンク生成
- チームワークスペース
- コメント・承認ワークフロー

#### Phase 4: AI支援強化（10週間）
- コピーライティング提案
- 配色自動提案
- テンプレート推薦エンジン

### 11.2 KPI

| KPI | Phase 1目標 | Phase 4目標 |
|---|---|---|
| MAU | 200 | 8,000 |
| バナー作成数/月 | 500 | 30,000 |
| ユーザー継続率 | 40% | 70% |
| 画像生成成功率 | 95% | 98% |
| 平均編集完了時間 | 15分以内 | 5分以内 |

---

## 12. Gemini API連携仕様

### 12.1 概要

ユーザーログイン時にGemini APIを呼び出し、UIデータを動的に設定する。ユーザーの利用履歴・業種・目的に基づいてパーソナライズされた編集体験を提供する。

### 12.2 ログイン時のUIデータ設定フロー

```
ユーザーログイン
      │
      ▼
Gemini API呼び出し
  ├─ ユーザープロファイル
  ├─ 過去の利用履歴
  └─ 現在のトレンドデータ
      │
      ▼
UIデータ生成
  ├─ おすすめテンプレート（カテゴリ・パターン順序）
  ├─ テキストコピー候補（業種別キャッチコピー）
  ├─ 配色提案（トレンド・ブランドカラー連動）
  └─ レイアウト推薦（目的別）
      │
      ▼
セッションに保存 → UI反映
```

### 12.3 API呼び出し仕様

```python
# app/services/gemini_service.py
import google.generativeai as genai

class GeminiService:
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-pro')

    async def generate_ui_data(self, user_profile: dict) -> dict:
        prompt = f"""
        ユーザープロファイル: {user_profile}
        以下のJSON形式でUIデータを生成してください:
        - recommended_templates: おすすめテンプレートID一覧
        - copy_suggestions: 業種別キャッチコピー候補（3-5個）
        - color_palette: 推奨配色（primary, accent, background）
        - layout_tips: レイアウトのアドバイス
        """
        response = await self.model.generate_content_async(prompt)
        return self._parse_response(response)
```

### 12.4 利用シーン

| シーン | Gemini APIの役割 |
|---|---|
| ログイン直後 | おすすめテンプレートの優先表示 |
| テキスト編集時 | キャッチコピー候補の提案 |
| 配色変更時 | 調和する配色の自動提案 |
| テンプレート選択時 | 業種・目的に基づく推薦 |

---

## 13. 対応カテゴリ仕様

### 13.1 カテゴリ一覧

| カテゴリID | カテゴリ名 | 主なユースケース | 特有スロット |
|---|---|---|---|
| `used_car` | 中古自動車 | 在庫訴求・価格比較・フェア告知 | 価格、走行距離、年式、車検期限 |
| `dressing` | ドレッシング | 新商品発売・レシピ訴求・キャンペーン | 容量、原材料ハイライト、レシピ写真 |
| `stationery` | 文房具 | 新学期セール・新商品・ギフト提案 | 商品群画像、価格帯、対象年齢 |
| `apparel` | アパレル | シーズンコレクション・セール・コーデ | モデル写真、割引率、サイズ展開 |
| `animal_funding` | 動物支援ファンディング | 保護活動支援・寄付募集・里親募集 | 目標金額、達成率、動物写真、支援ボタン |
| `ramen` | ラーメン屋 | 新メニュー告知・店舗宣伝・クーポン | メニュー写真、価格、営業時間、地図QR |

### 13.2 カテゴリ別テンプレートパターン

#### 13.2.1 中古自動車（used_car）

| パターンID | パターン名 | サイズ | 特徴 |
|---|---|---|---|
| `used_car_01` | 単品車両訴求型 | 380x380 | 車両写真フル + 価格・走行距離 |
| `used_car_02` | 複数在庫グリッド型 | 600x254 | 3-4台のサムネイル + 価格一覧 |
| `used_car_03` | フェア告知型 | 1200x630 | イベント情報 + 目玉車両 |
| `used_car_04` | 価格訴求型 | 996x998 | 大きな価格表示 + 車両写真 |

```xml
<!-- used_car_01 サンプルスロット定義 -->
<slots>
  <slot id="car_photo" type="image" x="0" y="0" width="100" height="65" required="true"
        description="車両正面・斜め前方写真"/>
  <slot id="car_name" type="text" x="3" y="67" width="60" height="8"
        max_chars="20" font_size_guideline="16px" font_weight="bold" color="#000000"
        description="車種名（例：トヨタ プリウス 2022年式）" required="true"/>
  <slot id="price" type="text" x="3" y="76" width="50" height="12"
        max_chars="12" font_size_guideline="28px" font_weight="bold" color="#E60012"
        description="販売価格（例：198万円）" required="true"/>
  <slot id="mileage" type="text" x="55" y="76" width="42" height="6"
        max_chars="12" font_size_guideline="12px" color="#666666"
        description="走行距離（例：3.2万km）" required="false"/>
  <slot id="inspection" type="text" x="55" y="82" width="42" height="6"
        max_chars="12" font_size_guideline="12px" color="#666666"
        description="車検期限（例：2027年3月）" required="false"/>
  <slot id="cta_button" type="button" x="0" y="88" width="100" height="12"
        default_label="詳細を見る" bg_color="#E60012" text_color="#FFFFFF" required="true"/>
</slots>
```

#### 13.2.2 ドレッシング（dressing）

| パターンID | パターン名 | サイズ | 特徴 |
|---|---|---|---|
| `dressing_01` | 商品単品訴求型 | 380x380 | ボトル写真 + キャッチコピー |
| `dressing_02` | レシピ連動型 | 1200x630 | 料理写真 + 商品 + レシピ提案 |
| `dressing_03` | 新商品発売型 | 996x998 | NEW!バッジ + 大きなコピー |
| `dressing_04` | キャンペーン型 | 600x254 | 割引情報 + 複数商品 |

#### 13.2.3 文房具（stationery）

| パターンID | パターン名 | サイズ | 特徴 |
|---|---|---|---|
| `stationery_01` | 新学期セール型 | 1200x630 | 商品群写真 + 割引率 |
| `stationery_02` | 単品商品訴求型 | 380x380 | 商品クローズアップ + 機能説明 |
| `stationery_03` | ギフト提案型 | 996x998 | ギフトボックス風レイアウト |
| `stationery_04` | 新商品一覧型 | 600x254 | 複数商品グリッド |

#### 13.2.4 アパレル（apparel）

| パターンID | パターン名 | サイズ | 特徴 |
|---|---|---|---|
| `apparel_01` | シーズンビジュアル型 | 1200x630 | モデル写真フル + ブランドロゴ |
| `apparel_02` | セール告知型 | 996x998 | 大きな割引率 + 商品写真 |
| `apparel_03` | コーディネート提案型 | 380x380 | コーデ写真 + アイテム価格 |
| `apparel_04` | 複数アイテム型 | 600x254 | アイテムグリッド + SHOP NOW |

#### 13.2.5 動物支援ファンディング（animal_funding）

| パターンID | パターン名 | サイズ | 特徴 |
|---|---|---|---|
| `animal_funding_01` | 支援呼びかけ型 | 1200x630 | 動物写真 + 感情的コピー + 支援ボタン |
| `animal_funding_02` | 達成率表示型 | 996x998 | プログレスバー + 目標金額 + 動物写真 |
| `animal_funding_03` | 里親募集型 | 380x380 | 動物プロフィール + 性格・年齢 |
| `animal_funding_04` | 活動報告型 | 600x254 | 活動写真 + 実績数字 + 支援リンク |

```xml
<!-- animal_funding_01 サンプルスロット定義 -->
<slots>
  <slot id="animal_photo" type="image" x="0" y="0" width="100" height="55"
        description="保護動物の写真（感情に訴える構図）" required="true"/>
  <slot id="main_copy" type="text" x="5" y="57" width="90" height="15"
        max_chars="20" font_size_guideline="32px" font_weight="bold" color="#333333"
        description="感情に訴えるキャッチコピー（例：この子に、あたたかい家を。）" required="true"/>
  <slot id="sub_copy" type="text" x="5" y="72" width="90" height="8"
        max_chars="40" font_size_guideline="14px" color="#666666"
        description="活動説明文" required="false"/>
  <slot id="goal_amount" type="text" x="5" y="81" width="45" height="7"
        max_chars="15" font_size_guideline="16px" font_weight="bold" color="#E67E22"
        description="目標金額（例：目標: 500万円）" required="true"/>
  <slot id="progress" type="text" x="52" y="81" width="43" height="7"
        max_chars="10" font_size_guideline="16px" font_weight="bold" color="#27AE60"
        description="達成率（例：72%達成）" required="false"/>
  <slot id="support_button" type="button" x="10" y="89" width="80" height="10"
        default_label="この活動を支援する" bg_color="#E67E22" text_color="#FFFFFF" required="true"/>
</slots>
```

#### 13.2.6 ラーメン屋（ramen）

| パターンID | パターン名 | サイズ | 特徴 |
|---|---|---|---|
| `ramen_01` | メニュー訴求型 | 380x380 | ラーメン写真フル + 商品名・価格 |
| `ramen_02` | 新メニュー告知型 | 1200x630 | NEW!バッジ + 大きなメニュー写真 |
| `ramen_03` | 店舗宣伝型 | 996x998 | 店舗外観/内観 + 営業時間 + 地図 |
| `ramen_04` | クーポン型 | 600x254 | 割引情報 + メニュー写真 + 有効期限 |

```xml
<!-- ramen_01 サンプルスロット定義 -->
<slots>
  <slot id="menu_photo" type="image" x="0" y="0" width="100" height="70"
        description="ラーメンの写真（湯気・トッピングが見える構図推奨）" required="true"/>
  <slot id="menu_name" type="text" x="3" y="71" width="65" height="10"
        max_chars="15" font_size_guideline="22px" font_weight="bold" color="#000000"
        description="メニュー名（例：特製味噌ラーメン）" required="true"/>
  <slot id="price" type="text" x="68" y="71" width="29" height="10"
        max_chars="8" font_size_guideline="24px" font_weight="bold" color="#CC0000"
        description="価格（例：¥980）" required="true"/>
  <slot id="shop_name" type="text" x="3" y="82" width="50" height="6"
        max_chars="20" font_size_guideline="12px" color="#333333"
        description="店名" required="true"/>
  <slot id="cta_button" type="button" x="0" y="88" width="100" height="12"
        default_label="場所を確認する" bg_color="#CC0000" text_color="#FFFFFF" required="true"/>
</slots>
```

### 13.3 カテゴリ追加手順

1. `/xml_templates/{category}/` ディレクトリを作成
2. XMLテンプレートファイルを作成（XSDバリデーション実施）
3. `templates` テーブルにレコード追加（管理画面またはAPI経由）
4. サムネイル画像を生成・登録
5. ステージング環境で動作確認
6. 本番デプロイ

---

## 14. CI/CD パイプライン設計

### 14.1 概要

GitHub + Vercelによる自動CI/CDパイプラインを構築する。PRごとにプレビューデプロイ、mainマージで本番デプロイを実現する。

### 14.2 パイプライン全体像

```
[feature/* ブランチにプッシュ]
        │
        ▼
┌─────────────────────────────────────────┐
│  Stage 1: Lint & 静的解析               │
│  ├─ Ruff (Python linter)                │
│  ├─ mypy (型チェック)                   │
│  ├─ Bandit (セキュリティ静的解析)       │
│  └─ Safety (依存関係脆弱性チェック)     │
└─────────────┬───────────────────────────┘
              │ 成功
              ▼
┌─────────────────────────────────────────┐
│  Stage 2: テスト                        │
│  ├─ pytest (ユニット・統合テスト)       │
│  ├─ カバレッジ計測 (目標: 80%以上)      │
│  └─ XMLテンプレートバリデーション       │
└─────────────┬───────────────────────────┘
              │ 成功
              ▼
┌─────────────────────────────────────────┐
│  Stage 3: Vercel Preview Deploy         │
│  ├─ PRごとにプレビューURL自動生成      │
│  ├─ Playwright E2Eテスト実行           │
│  └─ Lighthouse パフォーマンス計測       │
└─────────────┬───────────────────────────┘
              │ PR承認 + mainマージ
              ▼
┌─────────────────────────────────────────┐
│  Stage 4: Vercel Production Deploy      │
│  ├─ 自動本番デプロイ                    │
│  ├─ ヘルスチェック検証                  │
│  ├─ スモークテスト                      │
│  └─ 問題発生時: 前バージョンへロールバック│
└─────────────────────────────────────────┘
```

### 14.3 GitHub Actions ワークフロー

```yaml
# .github/workflows/ci.yml
name: CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install ruff mypy bandit safety
      - name: Ruff Lint
        run: ruff check .
      - name: Mypy Type Check
        run: mypy app/
      - name: Bandit Security Scan
        run: bandit -r app/ -ll
      - name: Safety Dependency Check
        run: safety check

  test:
    needs: lint
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: testpass
          POSTGRES_DB: bannerengine_test
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Run Tests
        run: pytest tests/ -v --cov=app --cov-report=xml --cov-fail-under=80
      - name: Validate XML Templates
        run: python -m app.core.xml_validator xml_templates/

  e2e:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Playwright
        run: npx playwright install --with-deps
      - name: Run E2E Tests against Preview
        run: npx playwright test
        env:
          BASE_URL: ${{ env.VERCEL_PREVIEW_URL }}
```

### 14.4 Vercel連携設定

| 設定項目 | 値 |
|---|---|
| Framework Preset | Other (Python) |
| Build Command | pip install -r requirements.txt |
| Output Directory | (default) |
| Root Directory | ./ |
| Node.js Version | 20.x |
| Python Version | 3.12 |

#### 環境変数（Vercel Dashboard設定）

| 変数名 | 環境 | 説明 |
|---|---|---|
| `DATABASE_URL` | Preview/Production | Vercel Postgres接続URL |
| `NANO_BANANA_API_KEY` | Preview/Production | Nano Banana Pro APIキー |
| `GEMINI_API_KEY` | Preview/Production | Gemini APIキー |
| `SESSION_SECRET_KEY` | Preview/Production | セッション暗号化キー |
| `BLOB_READ_WRITE_TOKEN` | Preview/Production | Vercel Blob Storageトークン |

### 14.5 デプロイ戦略

| 項目 | 方針 |
|---|---|
| PRプレビュー | 自動（Vercel Preview Deployments） |
| ステージング | mainブランチへのマージで自動デプロイ |
| 本番 | mainブランチ = 本番（Vercelのデフォルト） |
| ロールバック | Vercel Dashboardから即座に前バージョンへ |
| ドメイン | カスタムドメイン設定（Vercel DNS or 外部DNS） |

---

*本仕様書は開発の進捗に応じて随時更新される。各フェーズ開始前に詳細な実装計画を策定し、チームと合意の上で進める。*
