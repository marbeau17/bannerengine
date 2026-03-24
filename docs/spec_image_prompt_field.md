# 仕様書: NanoBannaraPro2 画像生成プロンプトフィールド追加

## 概要
バナーエンジンの画像スロットに「プロンプトフィールド」を追加し、ユーザーがNanoBannaraPro2を使って
テキストプロンプトから画像を生成できるようにする。

## 変更範囲

### 1. モデル変更

#### 1.1 `app/models/slot.py` - ImageSlotValue
- `prompt: Optional[str] = None` フィールド追加
- `generation_model: str = "nano-bannara-pro-2"` フィールド追加

#### 1.2 `app/models/template.py` - Slot
- `prompt_placeholder: Optional[str] = None` フィールド追加（プロンプトのヒントテキスト）
- `allow_ai_generation: bool = True` フィールド追加

#### 1.3 `app/models/banner.py` - RenderInstruction
- プロンプト情報をレイヤーに含められるよう変更なし（既存のdict構造で対応可能）

### 2. クライアント変更

#### 2.1 `app/services/nano_banana_client.py`
- モデル名を `models/nano-bannara-pro-2` に更新
- `_build_prompt()` にユーザープロンプトを組み込むロジック追加
- `submit_render()` にプロンプトパラメータ対応

### 3. UI変更

#### 3.1 `app/templates/components/slot_types/image_slot.html`
- 画像アップロードエリアの下にプロンプト入力フィールドを追加
- 「AI画像生成」トグルボタン追加
- プロンプト入力テキストエリア
- 「画像を生成」ボタン（htmx経由でAPI呼び出し）
- 生成中のローディング表示

#### 3.2 `app/templates/components/slot_types/image_or_text_slot.html`
- 画像モード時にプロンプトフィールドを表示

#### 3.3 `app/templates/partials/slot_editor.html`
- 変更なし（既存のinclude構造で対応）

### 4. API変更

#### 4.1 `app/routers/slots.py`
- `update_slot()`: フォームデータから`prompt`フィールドを取得・保存
- セッションにプロンプト値を保持

#### 4.2 新規: `app/routers/image_generate.py`
- `POST /api/image-generate/{pattern_id}/{slot_id}` - スロット単位のAI画像生成
  - リクエスト: `prompt` (テキスト), `pattern_id`, `slot_id`
  - レスポンス: 生成された画像URL, ステータス
- `GET /api/image-generate/status/{job_id}` - 生成ステータス確認（SSE）

### 5. サービス変更

#### 5.1 `app/services/banner_service.py`
- `_image_layer()`: プロンプト情報をレイヤーに含める
- `_slot_to_layers()`: プロンプトベース画像の処理

#### 5.2 `app/services/image_generation_service.py` (新規)
- スロット単位の画像生成を管理
- NanoBananaClientを使用してプロンプトから画像を生成
- 生成された画像を`/static/generated/`に保存
- ジョブ管理（状態・進捗追跡）

### 6. SVGレンダラー変更

#### 6.1 `app/core/svg_renderer.py`
- プロンプトが設定されているが画像未生成の場合、プロンプトテキストをプレースホルダーとして表示

### 7. メインアプリ変更

#### 7.1 `app/main.py`
- 新規ルーター `image_generate` をインポート・登録

## テスト計画

### ユニットテスト
- `tests/unit/test_image_prompt_models.py` - プロンプトフィールドのモデルバリデーション
- `tests/unit/test_image_generation_service.py` - 画像生成サービスのロジック
- `tests/unit/test_nano_banana_client_v2.py` - NanoBannaraPro2クライアント
- `tests/unit/test_svg_renderer_prompt.py` - プロンプトプレースホルダーレンダリング
- `tests/unit/test_slot_prompt_persistence.py` - プロンプトのセッション保存

### 統合テスト
- `tests/integration/test_image_generate_api.py` - 画像生成APIエンドポイント

## 画面フロー

```
[画像スロット]
  ├── [画像アップロード] (既存)
  │     ドラッグ&ドロップ / クリック選択
  │
  └── [AI画像生成] (新規)
        ├── [プロンプト入力テキストエリア]
        │     placeholder: "例: 赤いスポーツカー、白い背景、プロフェッショナルな写真"
        ├── [生成ボタン] → POST /api/image-generate/{pattern_id}/{slot_id}
        └── [生成結果プレビュー] ← SSE /api/image-generate/status/{job_id}
```
