#!/usr/bin/env python3
import argparse
import base64
import mimetypes
import os
import re
import tempfile
import uuid
from pathlib import Path

import requests

# 設定
NOTION_API_KEY = os.environ.get('NOTION_API_KEY', '').strip()
DATA_MANAGE_TABLEKEY = os.environ.get('DATA_MANAGE_TABLEKEY', '').strip()
UPLOADFORM_TABLEKEY = os.environ.get('UPLOADFORM_TABLEKEY', '').strip()
TEMP_DIR = os.environ.get('TEMP_DIR', os.path.join(tempfile.gettempdir(), 'notion_temp'))

NOTION_API_URL = 'https://api.notion.com/v1'
NOTION_VERSION = '2022-06-28'

headers = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Notion-Version': NOTION_VERSION,
    'Content-Type': 'application/json'
}

# 一時ファイル用ディレクトリを作成
def ensure_temp_directory():
    """ファイル一時保存用のディレクトリ構造を作成"""
    temp_dir = Path(TEMP_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir

# ファイルのカテゴリを判定
def get_file_category(file_name):
    """ファイル名から適切なカテゴリを判定する"""
    file_lower = file_name.lower()

    # 画像ファイル
    if any(file_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tiff"]):
        return "images"

    # 動画ファイル
    elif any(file_lower.endswith(ext) for ext in [".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv", ".wmv", ".m4v"]):
        return "videos"

    # 音声ファイル
    elif any(file_lower.endswith(ext) for ext in [".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".wma"]):
        return "audio"

    # その他のファイル
    else:
        return "others"

# Notionのテーブルからデータをフェッチする
def get_new_uploads():
    """UPLOADFORM_TABLEKEYのテーブルからデータをフェッチ"""
    url = f"{NOTION_API_URL}/databases/{UPLOADFORM_TABLEKEY}/query"
    response = requests.post(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return data.get('results', [])
    else:
        print(f'Failed to fetch upload form data: {response.status_code} - {response.text}')
        return []

# テーブルのプロパティタイプを取得
def get_table_property_types(database_id):
    """テーブルの各列のプロパティタイプを取得"""
    url = f"{NOTION_API_URL}/databases/{database_id}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return {k: v.get('type') for k, v in data.get('properties', {}).items()}
    return {}

# Notionの一時URLからファイルをダウンロードして保存
def download_notion_file(file_url, file_name):
    """NotionのファイルURLからファイルをダウンロード"""
    try:
        print(f"ファイルのダウンロード開始: {file_name}")
        response = requests.get(file_url, stream=True)
        if response.status_code != 200:
            print(f"ダウンロード失敗: {response.status_code}")
            return None

        # 一時保存先の決定
        temp_dir = ensure_temp_directory()

        # 安全なファイル名に変換
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', file_name)
        file_path = temp_dir / f"{uuid.uuid4()}_{safe_filename}"

        # ファイルを一時的に保存
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print(f"ファイルを一時保存: {file_path}")
        return file_path
    except Exception as e:
        print(f"ファイルダウンロード中にエラー: {e}")
        return None

# NotionのS3一時URLかどうかを判定
def is_temporary_notion_url(url):
    """NotionのS3一時URLかどうか判定"""
    if url and 'prod-files-secure.s3' in url and ('X-Amz-Expires' in url or 'expiry_time' in url):
        return True
    return False

# Notionにファイルをアップロード
def upload_file_to_notion(file_path):
    """
    ファイルをNotionにアップロードするためのアップロードURLを取得し、
    ファイルをアップロードしてパーマネントURLを返す
    """
    try:
        print(f"Notionへのファイルアップロード準備: {file_path}")

        # ファイル名とコンテンツタイプを取得
        file_name = os.path.basename(file_path)
        content_type, _ = mimetypes.guess_type(file_name)
        if content_type is None:
            content_type = 'application/octet-stream'

        # アップロードURLを取得するためのペイロード
        get_upload_url_payload = {
            "name": file_name,
            "content_type": content_type
        }

        # アップロードURLリクエスト
        upload_endpoint = f"{NOTION_API_URL}/upload"
        upload_url_response = requests.post(
            upload_endpoint,
            headers=headers,
            json=get_upload_url_payload
        )

        if upload_url_response.status_code != 200:
            print(f"アップロードURLの取得に失敗: {upload_url_response.status_code} - {upload_url_response.text}")
            # 代替方法: Base64エンコードによる対応
            print("Base64エンコード方式に切り替えます")
            with open(file_path, 'rb') as file:
                file_data = file.read()
                encoded_file_data = base64.b64encode(file_data).decode('utf-8')
                data_url = f"data:{content_type};base64,{encoded_file_data}"
                return data_url

        # レスポンスからアップロードURLと永続URLを取得
        upload_data = upload_url_response.json()
        upload_url = upload_data.get("upload_url")
        permanent_notion_url = upload_data.get("file_url")

        if not upload_url or not permanent_notion_url:
            print("アップロードURLまたは永続URLが見つかりません")
            return None

        # ファイルをアップロード
        with open(file_path, 'rb') as file:
            upload_headers = {"Content-Type": content_type}
            upload_response = requests.put(
                upload_url,
                headers=upload_headers,
                data=file
            )

            if upload_response.status_code != 200:
                print(f"ファイルのアップロードに失敗: {upload_response.status_code}")
                return None

        print(f"Notionへのファイルアップロード成功: {file_name}")
        print(f"永続URL: {permanent_notion_url}")
        return permanent_notion_url

    except Exception as e:
        print(f"Notionへのファイルアップロード中にエラー: {e}")
        return None
    finally:
        # 一時ファイルを削除
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                print(f"一時ファイルを削除しました: {file_path}")
        except Exception as e:
            print(f"一時ファイルの削除に失敗: {e}")

# 一時ファイルを永続的なURLに変換
def convert_temporary_file_to_permanent(file_info):
    """一時ファイルURLを永続的なURLに変換"""
    file_name = file_info.get('name', 'unknown_file')
    file_url = None
    file_type = None

    # 内部ファイルチェック
    if 'file' in file_info and isinstance(file_info['file'], dict) and 'url' in file_info['file']:
        file_url = file_info['file']['url']
        file_type = "file"
    # 外部URLチェック
    elif 'external' in file_info and isinstance(file_info['external'], dict) and 'url' in file_info['external']:
        file_url = file_info['external']['url']
        file_type = "external"

    if not file_url:
        print(f"ファイルURLが見つかりません: {file_info}")
        return file_info  # 元のファイル情報をそのまま返す

    # 一時URLかどうかチェック
    if file_type == "file" and is_temporary_notion_url(file_url):
        print(f"一時URLを検出: {file_name}")

        # ファイルをダウンロードして一時保存
        local_file_path = download_notion_file(file_url, file_name)
        if local_file_path:
            # Notionに再アップロード
            permanent_url = upload_file_to_notion(local_file_path)
            if permanent_url:
                # 新しいファイル情報を作成
                return {
                    "name": file_name,
                    "type": "external",
                    "external": {"url": permanent_url}
                }

    # 変換不要または失敗した場合は元のファイル情報をそのまま返す
    return file_info

# Notionのページを更新してファイルの永続URLを設定
def update_notion_with_permanent_url(page_id, file_properties):
    """Notionページのファイルプロパティを永続URLで更新"""
    url = f"{NOTION_API_URL}/pages/{page_id}"

    properties = {
        "ファイル": {
            "files": file_properties
        }
    }

    payload = {
        "properties": properties
    }

    response = requests.patch(url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"Notionページを更新しました: {page_id}")
        return True
    else:
        print(f"Notionページの更新に失敗: {response.status_code} - {response.text}")
        return False

# アップロードフォームのデータを管理テーブルに追加
def add_to_data_manage(page_data, page_id=None, created_time=None):
    """アップロードフォームのデータを管理テーブルに追加"""
    url = f"{NOTION_API_URL}/pages"
    data_manage_types = get_table_property_types(DATA_MANAGE_TABLEKEY)
    properties = {}

    # DATA_MANAGE_TABLEKEYのすべての列に対応
    for key, typ in data_manage_types.items():
        # タイトル列（名前）の処理
        if key == "名前" and page_id:
            properties["名前"] = {
                "title": [
                    {"text": {"content": page_id}}
                ]
            }
        # 提出日時の処理
        elif key == "提出日時" and created_time:
            properties["提出日時"] = {
                "date": {
                    "start": created_time
                }
            }
        # プロジェクト管理テーブル (relation) の処理
        elif key == "プロジェクト管理テーブル" and "プロジェクト管理テーブル" in page_data:
            properties[key] = page_data["プロジェクト管理テーブル"]
        # カテゴリ (relation) の処理 - "アップロード予定のファイル"に相当
        elif key == "カテゴリ" and "アップロード予定のファイル" in page_data:
            properties[key] = page_data["アップロード予定のファイル"]
        # その他の列の情報をコピー
        elif key in page_data and key not in ["ファイル"]:
            properties[key] = page_data[key]

    # アップロード列のファイルをファイル列にコピー
    file_objs = []
    embed_blocks = []

    if 'アップロード' in page_data:
        upload_prop = page_data['アップロード']
        if 'files' in upload_prop:
            # 直接オブジェクトを取得
            files_array = upload_prop['files']
            # アップロードのプロパティ全体を詳細に出力（デバッグ用）
            print(f"アップロードのプロパティ: {upload_prop}")

            if isinstance(files_array, list) and files_array:
                for file_info in files_array:
                    # 一時ファイルを永続的なURLに変換
                    updated_file_info = convert_temporary_file_to_permanent(file_info)
                    file_name = updated_file_info.get('name', 'ファイル')

                    file_objs.append(updated_file_info)

                    # 埋め込みブロックを作成
                    file_url = None
                    if updated_file_info.get('type') == 'external' and 'external' in updated_file_info:
                        file_url = updated_file_info['external'].get('url')
                    elif updated_file_info.get('type') == 'file' and 'file' in updated_file_info:
                        file_url = updated_file_info['file'].get('url')

                    if file_url:
                        # 拡張子でファイルタイプを判定 - ページ埋め込み用
                        file_lower = file_name.lower()

                        # 画像ファイル
                        if any(file_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]):
                            block = {
                                "object": "block",
                                "type": "image",
                                "image": {
                                    "type": "external",
                                    "external": {"url": file_url}
                                }
                            }
                            print(f"画像ブロック作成: {block}")
                            embed_blocks.append(block)
                        # 動画ファイル
                        elif any(file_lower.endswith(ext) for ext in [".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv"]):
                            block = {
                                "object": "block",
                                "type": "video",
                                "video": {
                                    "type": "external",
                                    "external": {"url": file_url}
                                }
                            }
                            print(f"動画ブロック作成: {block}")
                            embed_blocks.append(block)
                        # 音声ファイル
                        elif any(file_lower.endswith(ext) for ext in [".mp3", ".wav", ".ogg", ".m4a", ".flac"]):
                            block = {
                                "object": "block",
                                "type": "audio",
                                "audio": {
                                    "type": "external",
                                    "external": {"url": file_url}
                                }
                            }
                            print(f"音声ブロック作成: {block}")
                            embed_blocks.append(block)
                        # その他のファイル
                        else:
                            block = {
                                "object": "block",
                                "type": "file",
                                "file": {
                                    "type": "external",
                                    "external": {"url": file_url}
                                }
                            }
                            print(f"ファイルブロック作成: {block}")
                            embed_blocks.append(block)

    # ファイル列の設定
    if file_objs:
        print(f"追加するファイルオブジェクト: {file_objs}")
        properties["ファイル"] = {"files": file_objs}

    payload = {
        "parent": {"database_id": DATA_MANAGE_TABLEKEY},
        "properties": properties,
    }

    # ブロック追加
    if embed_blocks:
        # Notion APIの仕様上、childrenは最大100件まで
        payload["children"] = embed_blocks[:100]

    print(f"送信するペイロード: {payload}")
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print('Page added to DATA_MANAGE_TABLEKEY')
        return response.json()
    else:
        print(f'Failed to add page: HTTP {response.status_code}')
        print(f'Response: {response.text}')
        return None

# アップロードテーブルの内容を管理テーブルに移動
def move_uploads_to_data_manage():
    """
    UPLOADFORM_TABLEKEYの全ページ内容をDATA_MANAGE_TABLEKEYに追加する（削除は行わない）
    """
    uploads = get_new_uploads()
    print(f"{len(uploads)}件のアップロードを検出")

    # まず全てのページをDATA_MANAGE_TABLEKEYに追加
    for upload in uploads:
        properties = upload.get('properties', {})
        page_id = upload.get('id')
        created_time = upload.get('created_time')
        add_to_data_manage(properties, page_id=page_id, created_time=created_time)

    # 処理完了後、一時ディレクトリをクリーンアップ
    try:
        temp_dir = Path(TEMP_DIR)
        if temp_dir.exists():
            for temp_file in temp_dir.glob("*"):
                if temp_file.is_file():
                    temp_file.unlink()
            print("一時ファイルをクリーンアップしました")
    except Exception as e:
        print(f"一時ファイルのクリーンアップに失敗: {e}")

# テーブル構造の情報を表示
def print_table_columns(database_id, label=None):
    """テーブル構造の情報を表示"""
    url = f"{NOTION_API_URL}/databases/{database_id}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        print(f"--- {label or database_id} columns ---")
        for k, v in data.get('properties', {}).items():
            print(f"{k}: {v.get('type')} -> {v}")
        print("-----------------------------")
    else:
        print(f"Failed to fetch columns for {label or database_id}: {response.text}")

def process_notion_files():
    """メイン処理: NotionファイルをダウンロードしてNotionに再アップロード"""
    # 初期設定の確認
    if not NOTION_API_KEY:
        print("エラー: NOTION_API_KEYが設定されていません")
        return
    if not DATA_MANAGE_TABLEKEY:
        print("エラー: DATA_MANAGE_TABLEKEYが設定されていません")
        return
    if not UPLOADFORM_TABLEKEY:
        print("エラー: UPLOADFORM_TABLEKEYが設定されていません")
        return

    print(f"NotionファイルマネージャーV1.0")
    print(f"NOTION_API_URL: {NOTION_API_URL}")
    print(f"UPLOADFORM_TABLEKEY: {UPLOADFORM_TABLEKEY}")
    print(f"DATA_MANAGE_TABLEKEY: {DATA_MANAGE_TABLEKEY}")

    # 一時ディレクトリを確保
    ensure_temp_directory()

    # テーブル情報を表示
    print_table_columns(UPLOADFORM_TABLEKEY, label="UPLOADFORM_TABLEKEY")
    print_table_columns(DATA_MANAGE_TABLEKEY, label="DATA_MANAGE_TABLEKEY")

    # メイン処理実行
    move_uploads_to_data_manage()

    print("処理が完了しました")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Notionファイルマネージャー')
    parser.add_argument('--debug', action='store_true', help='デバッグモードで実行')
    args = parser.parse_args()

    try:
        process_notion_files()
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
