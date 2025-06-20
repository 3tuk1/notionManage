import os
import requests

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
        if 'files' in upload_prop and upload_prop['files']:
            for file_info in upload_prop['files']:
                file_name = file_info.get('name', 'ファイル')
                notion_file_url = file_info.get('file', {}).get('url')
                external_url = file_info.get('external', {}).get('url')

                # ファイル列用
                if notion_file_url:
                    file_objs.append({
                        "type": "file",
                        "name": file_name,
                        "file": {"url": notion_file_url}
                    })
                elif external_url:
                    file_objs.append({
                        "type": "external",
                        "name": file_name,
                        "external": {"url": external_url}
                    })

                file_url = notion_file_url or external_url
                if not file_url:
                    continue

                # 動画ファイル
                if file_name.lower().endswith((".mp4", ".mov", ".avi", ".webm")):
                    block = {
                        "object": "block",
                        "type": "video",
                        "video": {
                            "type": "external",
                            "external": {"url": file_url}
                        }
                    }
                    embed_blocks.append(block)

                # 画像ファイル
                elif file_name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")):
                    block = {
                        "object": "block",
                        "type": "image",
                        "image": {
                            "type": "external",
                            "external": {"url": file_url}
                        }
                    }
                    embed_blocks.append(block)

                # 音声ファイル
                elif file_name.lower().endswith((".mp3", ".wav", ".ogg", ".m4a")):
                    block = {
                        "object": "block",
                        "type": "audio",
                        "audio": {
                            "type": "external",
                            "external": {"url": file_url}
                        }
                    }
                    embed_blocks.append(block)

    if file_objs:
        properties["ファイル"] = {"files": file_objs}

    payload = {
        "parent": {"database_id": DATA_MANAGE_TABLEKEY},
        "properties": properties,
    }

    if embed_blocks:
        # Notion APIの仕様上、childrenは最大100件まで
        payload["children"] = embed_blocks[:100]

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print('Page added to DATA_MANAGE_TABLEKEY')
        return response.json()
    else:
        print('Failed to add page:', response.text)
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
