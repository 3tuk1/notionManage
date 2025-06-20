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
    # UPLOADFORM_TABLEKEYのテーブルからデータ取得（仮実装）
    url = f"{NOTION_API_URL}databases/{UPLOADFORM_TABLEKEY}/query"
    response = requests.post(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        # TODO: 新規データの判定ロジックを実装
        return data.get('results', [])
    else:
        print('Failed to fetch upload form data:', response.text)
        return []

def add_to_data_manage(page_data):
    # DATA_MANAGE_TABLEKEYにページ追加（アップロード列の埋め込み対応）
    url = f"{NOTION_API_URL}pages"
    properties = dict(page_data)  # コピー
    # アップロード列の処理
    upload_files = []
    if 'アップロード' in properties:
        upload_prop = properties['アップロード']
        if 'files' in upload_prop and upload_prop['files']:
            for file_info in upload_prop['files']:
                file_url = file_info.get('file', {}).get('url') or file_info.get('external', {}).get('url')
                if file_url:
                    # 拡張子で判定
                    if file_url.lower().endswith(('.mp4', '.mov', '.avi', '.webm')):
                        embed_type = 'movie'
                    elif file_url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                        embed_type = 'photo'
                    elif file_url.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a')):
                        embed_type = 'sound'
                    else:
                        embed_type = None
                    if embed_type:
                        upload_files.append({'type': embed_type, 'url': file_url})
    # ページ本文の埋め込みブロックを作成
    children = []
    for f in upload_files:
        if f['type'] == 'movie':
            children.append({"object": "block", "type": "video", "video": {"type": "external", "external": {"url": f['url']}}})
        elif f['type'] == 'photo':
            children.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": f['url']}}})
        elif f['type'] == 'sound':
            children.append({"object": "block", "type": "audio", "audio": {"type": "external", "external": {"url": f['url']}}})
    # アップロード列は空にする（またはそのまま）
    payload = {
        "parent": {"database_id": DATA_MANAGE_TABLEKEY},
        "properties": properties,
    }
    if children:
        payload["children"] = children
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print('Page added to DATA_MANAGE_TABLEKEY')
    else:
        print('Failed to add page:', response.text)

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
    UPLOADFORM_TABLEKEYの全ページ内容をDATA_MANAGE_TABLEKEYに追加し、元ページを削除する
    """
    uploads = get_new_uploads()
    # まず全てのページをDATA_MANAGE_TABLEKEYに追加
    for upload in uploads:
        properties = upload.get('properties', {})
        add_to_data_manage(properties)
    # その後、元ページを削除
    for upload in uploads:
        page_id = upload.get('id')
        if page_id:
            delete_url = f"{NOTION_API_URL}pages/{page_id}"
            del_response = requests.patch(delete_url, headers=headers, json={"archived": True})
            if del_response.status_code == 200:
                print(f"Page {page_id} archived (deleted) from UPLOADFORM_TABLEKEY.")
            else:
                print(f"Failed to archive page {page_id}: {del_response.text}")

def main():
    move_uploads_to_data_manage()

if __name__ == '__main__':
    main()
