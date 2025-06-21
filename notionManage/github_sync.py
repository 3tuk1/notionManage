#!/usr/bin/env python3
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
    if 'prod-files-secure.s3' in url and ('X-Amz-Expires' in url or 'expiry_time' in url):
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
        # これはNotionの現在のAPIバージョンで使用
        # 注意: APIの仕様変更がある可能性があります
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
            return None

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

        # Notion APIが変更されている場合やアップロードURLの方式が異なる場合にプラン B を実行
        # これは代替方法として、Base64エンコードして外部URLとして保存する方法
        if not permanent_notion_url.startswith(("http://", "https://")):
            print("永続URLが有効でないため、Base64エンコード方式に切り替えます")
            with open(file_path, 'rb') as file:
                file_data = file.read()
                encoded_file_data = base64.b64encode(file_data).decode('utf-8')
                permanent_notion_url = f"data:{content_type};base64,{encoded_file_data}"

        print(f"Notionへのファイルアップロード成功: {file_name}")
        # 一時ファイルを削除
        os.unlink(file_path)
        return permanent_notion_url

    except Exception as e:
        print(f"Notionへのファイルアップロード中にエラー: {e}")
        # 一時ファイルを削除
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except:
            pass
        return None

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

def process_notion_files():
    """Notionファイルをダウンロードして再アップロードし、永続的なURLで更新する"""
    # 一時ディレクトリを確保
    ensure_temp_directory()

    # アップロードフォームのデータを取得
    uploads = get_new_uploads()
    print(f"{len(uploads)}件のアップロードを検出")

    for page in uploads:
        page_id = page.get('id')
        properties = page.get('properties', {})

        # ファイルを含むプロパティを探す
        for prop_name, prop_data in properties.items():
            if prop_data.get('type') == 'files' and 'files' in prop_data:
                files_array = prop_data['files']

                updated_files = []  # 更新後のファイルプロパティリスト
                for file_info in files_array:
                    file_name = file_info.get('name', 'unknown_file')

                    # 内部ファイルチェック
                    if 'file' in file_info and isinstance(file_info['file'], dict) and 'url' in file_info['file']:
                        file_url = file_info['file']['url']

                        # 一時URLかどうかチェック
                        if is_temporary_notion_url(file_url):
                            print(f"一時URLを検出: {file_name}")

                            # ファイルをダウンロードして一時保存
                            local_file_path = download_notion_file(file_url, file_name)
                            if local_file_path:
                                # Notionに再アップロード
                                permanent_url = upload_file_to_notion(local_file_path)
                                if permanent_url:
                                    # 更新されたファイルプロパティを追加
                                    updated_files.append({
                                        "name": file_name,
                                        "type": "external",
                                        "external": {"url": permanent_url}
                                    })
                                    print(f"永続URL変換完了: {file_name}")
                                else:
                                    # アップロード失敗時は元のプロパティを維持
                                    print(f"再アップロード失敗: {file_name}")
                                    updated_files.append(file_info)
                            else:
                                # ダウンロード失敗時は元のプロパティを維持
                                updated_files.append(file_info)
                        else:
                            # 一時URLでない場合はそのまま追加
                            updated_files.append(file_info)
                    else:
                        # 外部URLの場合はそのまま追加
                        updated_files.append(file_info)

                # Notionページを更新
                if updated_files:
                    update_notion_with_permanent_url(page_id, updated_files)

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

if __name__ == "__main__":
    process_notion_files()
