import os
import requests
from typing import Dict, Optional, List
import json

class NotionClient:
    """Notion APIクライアント"""

    def __init__(self, token: str = None):
        """
        Notion API クライアントの初期化

        Args:
            token: Notion API トークン (Noneの場合は環境変数から取得)
        """
        self.token = token or os.environ.get("NOTION_API_KEY")
        if not self.token:
            raise ValueError("Notion APIトークンが設定されていません。NOTION_API_KEY環境変数を設定してください。")

        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",  # 適切なAPIバージョンを指定
        }

    def query_database(self, database_id: str, filter_params: Optional[Dict] = None) -> Dict:
        """
        データベースのクエリを実行

        Args:
            database_id: Notionデータベースのid
            filter_params: フィルタパラメータ

        Returns:
            クエリ結果のJSON
        """
        url = f"{self.base_url}/databases/{database_id}/query"
        payload = {}
        if filter_params:
            payload.update(filter_params)

        response = requests.post(url, json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_page(self, page_id: str) -> Dict:
        """
        ページ情報を取得

        Args:
            page_id: ページID

        Returns:
            ページ情報
        """
        url = f"{self.base_url}/pages/{page_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_block_children(self, block_id: str, start_cursor: Optional[str] = None, page_size: int = 100) -> Dict:
        """
        ブロックの子要素を取得

        Args:
            block_id: ブロックID
            start_cursor: 開始カーソル
            page_size: 1ページあたりの最大結果数

        Returns:
            ブロックの子要素
        """
        url = f"{self.base_url}/blocks/{block_id}/children"
        params = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor

        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_all_block_children(self, block_id: str) -> List[Dict]:
        """
        ブロックの全ての子要素を取得（ページネーション対応）

        Args:
            block_id: ブロックID

        Returns:
            全ての子ブロックのリスト
        """
        all_blocks = []
        has_more = True
        start_cursor = None

        while has_more:
            response = self.get_block_children(block_id, start_cursor)
            all_blocks.extend(response.get("results", []))
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")
            if not has_more or not start_cursor:
                break

        return all_blocks

    def delete_block(self, block_id: str) -> Optional[Dict]:
        """
        ブロックを削除する

        Args:
            block_id: 削除するブロックのID

        Returns:
            APIレスポンスまたはNone（エラー時）
        """
        url = f"{self.base_url}/blocks/{block_id}"
        try:
            response = requests.delete(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return None

    def get_file_url(self, file_object: Dict) -> str:
        """
        NotionファイルオブジェクトからファイルのURLを取得

        Args:
            file_object: Notionのファイルオブジェクト

        Returns:
            ファイルのURL
        """
        if file_object.get("type") == "external":
            return file_object.get("external", {}).get("url", "")
        elif file_object.get("type") == "file":
            return file_object.get("file", {}).get("url", "")
        return ""

    def append_blocks(self, page_id: str, blocks: List[Dict]) -> Optional[Dict]:
        """
        ページにブロックを追加する

        Args:
            page_id: ブロックを追加するページのID
            blocks: 追加するブロックのリスト

        Returns:
            APIレスポンスまたはNone（エラー時）
        """
        url = f"{self.base_url}/blocks/{page_id}/children"
        payload = {
            "children": blocks
        }

        try:
            response = requests.patch(url, json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if e.response is not None:
                pass
            return None

    def retrieve_database(self, database_id: str) -> Dict:
        """
        データベースの詳細を取得

        Args:
            database_id: Notionデータベースのid

        Returns:
            データベースの詳細情報のJSON
        """
        url = f"{self.base_url}/databases/{database_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(f"Failed to retrieve database: {response.status_code}, {response.text}")
        return response.json()

    # --- ★ここからが追加するメソッド★ ---
    def create_page(self, parent_db_id: str, properties: dict) -> Dict:
        """指定されたデータベースに新しいページを作成する"""
        url = f"{self.base_url}/pages"
        payload = {
            "parent": {"database_id": parent_db_id},
            "properties": properties
        }
        response = requests.post(url, json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def archive_page(self, page_id: str) -> Dict:
        """ページをアーカイブする"""
        url = f"{self.base_url}/pages/{page_id}"
        payload = {"archived": True}
        response = requests.patch(url, json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()
    # --- ★ここまで★ ---
