import os
import requests
import re
import uuid
from urllib.parse import urlparse, parse_qs
import tempfile

NOTION_API_KEY = os.environ.get('NOTION_API_KEY')
DATA_MANAGE_TABLEKEY = os.environ.get('DATA_MANAGE_TABLEKEY')
UPLOADFORM_TABLEKEY = os.environ.get('UPLOADFORM_TABLEKEY')

NOTION_API_URL = 'https://api.notion.com/v1/'
NOTION_VERSION = '2022-06-28'

headers = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Notion-Version': NOTION_VERSION,
    'Content-Type': 'application/json'
}

def get_new_uploads():
    # UPLOADFORM_TABLEKEYのテーブルからデータ取得（デバッグ用出力追加）
    url = f"{NOTION_API_URL}databases/{UPLOADFORM_TABLEKEY}/query"
    response = requests.post(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        # TODO: 新規データの判定ロジックを実装
        return data.get('results', [])
    else:
        print('Failed to fetch upload form data:', response.text)
        return []

def get_table_property_types(database_id):
    url = f"{NOTION_API_URL}databases/{database_id}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return {k: v.get('type') for k, v in data.get('properties', {}).items()}
    return {}

def download_and_upload_file(file_url, file_name):
    """NotionのファイルURLからファイルをダウンロードし、再アップロードして永続リンクを取得"""
    try:
        # ファイルをダウンロード
        print(f"ファイルのダウンロード中: {file_name}")
        file_response = requests.get(file_url, stream=True)
        if file_response.status_code != 200:
            print(f"ファイルのダウンロードに失敗: {file_response.status_code}")
            return None

        # Notionにファイルをアップロード（循環参照を避けるため外部URLとして保存）
        # 実運用ではこの部分を別のストレージサービス（S3、GCSなど）に置き換えることで永続化
        # このデモでは一時的なサードパーティアップロードサービスを使用（運用時は変更推奨）
        temp_file_url = f"https://example.com/storage/{uuid.uuid4()}/{file_name}"
        print(f"永続ファイルURLに変換: {temp_file_url}")

        # 実際の実装では、以下のようなコードでファイルを永続的なストレージに保存する
        # upload_to_storage(file_response.content, file_name)

        return temp_file_url
    except Exception as e:
        print(f"ファイル処理中にエラーが発生: {e}")
        return None

def download_and_upload_file_to_notion(file_url, file_name):
    """
    NotionのファイルURLからファイルをダウンロードし、再度Notionにアップロードして永続リンクを取得
    """
    try:
        # ファイルをダウンロード
        print(f"ファイルのダウンロード中: {file_name}")
        file_response = requests.get(file_url, stream=True)
        if file_response.status_code != 200:
            print(f"ファイルのダウンロードに失敗: {file_response.status_code}")
            return None

        # 一時ファイルとして保存
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as temp_file:
            temp_path = temp_file.name
            for chunk in file_response.iter_content(chunk_size=8192):
                if chunk:
                    temp_file.write(chunk)

        print(f"一時ファイルに保存: {temp_path}")

        # NotionにファイルをアップロードするAPI
        upload_url = "https://api.notion.com/v1/files"

        # ファイルアップロード用のヘッダー（Content-Typeを変更）
        upload_headers = headers.copy()
        upload_headers["Content-Type"] = "multipart/form-data"

        # ファイルをアップロード
        with open(temp_path, 'rb') as f:
            files = {
                'file': (file_name, f, 'application/octet-stream'),
                'type': (None, 'file'),
                'name': (None, file_name)
            }
            print(f"Notionにファイルをアップロード中: {file_name}")

            # Notionへのファイルアップロードリクエスト（S3へのプリサインドURL取得）
            presigned_response = requests.post(
                "https://api.notion.com/v1/files",
                headers=upload_headers,
                files=files
            )

            if presigned_response.status_code != 200:
                print(f"ファイルアップロードURLの取得に失敗: {presigned_response.text}")
                os.unlink(temp_path)
                return None

            presigned_data = presigned_response.json()
            presigned_url = presigned_data.get('url')

            if not presigned_url:
                print("プリサインドURLが見つかりません")
                os.unlink(temp_path)
                return None

            # S3にファイルをアップロード
            with open(temp_path, 'rb') as f:
                s3_upload = requests.put(
                    presigned_url,
                    data=f,
                    headers={"Content-Type": "application/octet-stream"}
                )

                if s3_upload.status_code not in [200, 201]:
                    print(f"S3へのファイルアップロードに失敗: {s3_upload.status_code}")
                    os.unlink(temp_path)
                    return None

        # 一時ファイル削除
        os.unlink(temp_path)

        # 永続的なNotionファイルURL
        permanent_file_url = presigned_data.get('url')
        print(f"永続ファイルURLを取得: {permanent_file_url}")

        return permanent_file_url
    except Exception as e:
        print(f"ファイル処理中にエラーが発生: {e}")
        # 一時ファイルがあれば削除
        try:
            if 'temp_path' in locals():
                os.unlink(temp_path)
        except:
            pass
        return None

def is_temporary_notion_url(url):
    """NotionのS3一時URLかどうか判定"""
    if 'prod-files-secure.s3' in url and ('X-Amz-Expires' in url or 'expiry_time' in url):
        return True
    return False

def extract_file_id_from_url(url):
    """NotionのURLからファイルIDを抽出"""
    try:
        # URLをパースしてクエリパラメータを取得
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.split('/')

        # パスの最後の部分がファイル名の場合が多い
        if len(path_parts) > 0:
            file_name = path_parts[-1]
            return file_name
        return None
    except:
        return None

def add_to_data_manage(page_data, page_id=None, created_time=None):
    url = f"{NOTION_API_URL}pages"
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
                    file_name = file_info.get('name', 'ファイル')

                    # Notion内部ファイルとExternal URLの両方に対応
                    file_url = None
                    file_type = None
                    expiry_time = None

                    # 内部ファイルチェック
                    if 'file' in file_info and isinstance(file_info['file'], dict) and 'url' in file_info['file']:
                        file_url = file_info['file']['url']
                        file_type = "file"
                        # 有効期限情報があれば取得
                        if 'expiry_time' in file_info['file']:
                            expiry_time = file_info['file']['expiry_time']
                            print(f"ファイル有効期限: {expiry_time}")
                    # 外部URLチェック
                    elif 'external' in file_info and isinstance(file_info['external'], dict) and 'url' in file_info['external']:
                        file_url = file_info['external']['url']
                        file_type = "external"

                    if not file_url:
                        print(f"ファイルURLが見つかりません: {file_info}")
                        continue

                    print(f"処理中のファイル: {file_name}, URL: {file_url}, タイプ: {file_type}")

                    # NotionのS3 URLかどうかを判定（一時的なURLの場合）
                    is_temp_url = is_temporary_notion_url(file_url)

                    # 一時URLの場合、Notionに再アップロードして永続的なURLを取得
                    if is_temp_url and file_type == "file":
                        print(f"一時的なURLを検出: {file_name} - 再アップロード処理を開始")
                        permanent_url = download_and_upload_file_to_notion(file_url, file_name)
                        if permanent_url:
                            file_url = permanent_url
                            file_type = "external"
                            print(f"永続URLに置換完了: {file_name}")

                    # ファイル列用のオブジェクト作成
                    # 重要: Notionホストのファイルは'file'タイプで、外部URLは'external'タイプで扱う
                    if file_type == "file":
                        file_obj = {
                            "name": file_name,
                            "type": "file",
                            "file": {"url": file_url}
                        }
                        if expiry_time:
                            file_obj["file"]["expiry_time"] = expiry_time
                    else:  # external
                        file_obj = {
                            "name": file_name,
                            "type": "external",
                            "external": {"url": file_url}
                        }
                    file_objs.append(file_obj)

                    # 拡張子でファイルタイプを判定 - ページ埋め込み用
                    file_lower = file_name.lower()

                    # 画像ファイル
                    if any(file_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]):
                        # 画像ブロックの作成 - external URLのみ対応
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
                        # 動画ブロックの作成
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
                        # 音声ブロックの作成
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

                    # その他のファイル（埋め込み不可）はファイルブロックとして追加
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
        # 問題のあるペイロードを表示
        print(f'Problem payload: {payload}')
        return None

def get_table_columns(database_id):
    """
    指定したNotionデータベースの列名一覧を取得
    """
    url = f"{NOTION_API_URL}databases/{database_id}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return list(data.get('properties', {}).keys())
    else:
        print('Failed to fetch columns:', response.text)
        return []

def move_uploads_to_data_manage():
    """
    UPLOADFORM_TABLEKEYの全ページ内容をDATA_MANAGE_TABLEKEYに追加する（削除は行わない）
    """
    uploads = get_new_uploads()
    # まず全てのページをDATA_MANAGE_TABLEKEYに追加
    for upload in uploads:
        properties = upload.get('properties', {})
        page_id = upload.get('id')
        created_time = upload.get('created_time')
        add_to_data_manage(properties, page_id=page_id, created_time=created_time)
    # 削除処理は一時的にオフ
    # for upload in uploads:
    #     page_id = upload.get('id')
    #     if page_id:
    #         delete_url = f"{NOTION_API_URL}pages/{page_id}"
    #         del_response = requests.patch(delete_url, headers=headers, json={"archived": True})
    #         if del_response.status_code == 200:
    #             print(f"Page {page_id} archived (deleted) from UPLOADFORM_TABLEKEY.")
    #         else:
    #             print(f"Failed to archive page {page_id}: {del_response.text}")

def print_table_columns(database_id, label=None):
    url = f"{NOTION_API_URL}databases/{database_id}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        print(f"--- {label or database_id} columns ---")
        for k, v in data.get('properties', {}).items():
            print(f"{k}: {v.get('type')} -> {v}")
        print("-----------------------------")
    else:
        print(f"Failed to fetch columns for {label or database_id}: {response.text}")

def main():
    print_table_columns(UPLOADFORM_TABLEKEY, label="UPLOADFORM_TABLEKEY")
    print_table_columns(DATA_MANAGE_TABLEKEY, label="DATA_MANAGE_TABLEKEY")
    move_uploads_to_data_manage()

if __name__ == '__main__':
    main()
