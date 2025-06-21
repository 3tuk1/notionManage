import base64
import json
import mimetypes
import os
from typing import Dict, List, Optional, Any, Union, Tuple
from urllib.request import urlopen

from .notion_client import NotionClient


class NotionFileViewer:
    """Notionのファイル表示用クラス"""

    def __init__(self, token: str = None):
        """
        初期化

        Args:
            token: Notion API トークン (Noneの場合は環境変数から取得)
        """
        self.client = NotionClient(token)

        # repository secretsからテーブルキーを読み込み
        self.uploadform_tablekey = self._load_table_keys("UPLOADFORM_TABLEKEY")
        self.data_manage_tablekey = self._load_table_keys("DATA_MANAGE_TABLEKEY")

        # 埋め込みマーカーとなるヘッダーテキスト
        self.embed_marker = "アップロードファイル埋め込み"

    def _load_table_keys(self, env_var_name: str) -> Dict:
        """
        環境変数からテーブルキーを読み込む

        Args:
            env_var_name: 環境変数名

        Returns:
            テーブルキー辞書
        """
        table_key_json = os.environ.get(env_var_name)
        if not table_key_json:
            print(f"警告: {env_var_name}環境変数が設定されていません")
            return {}

        try:
            return json.loads(table_key_json)
        except json.JSONDecodeError:
            print(f"警告: {env_var_name}環境変数の形式が正しくありません")
            return {}

    def get_upload_files(self, database_id: str, page_id: Optional[str] = None) -> List[Dict]:
        """
        アップロードフォームテーブルからファイル情報を取得
        各ファイルデータには、そのファイルを持つNotionページのIDも含まれる

        Args:
            database_id: データベースID
            page_id: ページID (指定した場合はそのページのみ取得)

        Returns:
            ファイル情報のリスト。各要素は以下の形式:
            {
                "page_id": "ファイルが含まれるNotionページのID",
                "name": "ファイル名",
                "url": "ファイルのURL",
                "type": "ファイルのMIMEタイプ"
            }
        """
        filter_params = {}
        if page_id:
            # 特定のページIDが指定された場合は、そのページのみをフィルタ
            filter_params = {
                "filter": {
                    "property": "id",
                    "formula": {
                        "string": {
                            "equals": page_id
                        }
                    }
                }
            }

        results = self.client.query_database(database_id, filter_params)
        files_data = []

        # アップロードカラムのプロパティIDを取得
        upload_key = self.uploadform_tablekey.get("アップロード")
        if not upload_key:
            print("警告: アップロードカラムのIDが見つかりません")
            return []

        # 各ページ（テーブルの各行）を処理
        for page in results.get("results", []):
            # このページ（row）のID
            current_page_id = page.get("id")
            properties = page.get("properties", {})

            # このページの「アップロード」カラムの値を取得
            upload_files = properties.get(upload_key, {})

            # アップロードされたファイルを処理
            files = upload_files.get("files", [])
            for file_obj in files:
                file_url = self.client.get_file_url(file_obj)
                if file_url:
                    # ファイル情報と、それを持つページIDを関連付ける
                    file_data = {
                        "page_id": current_page_id,  # このファイルを持つページのID
                        "name": file_obj.get("name", "Unnamed"),
                        "url": file_url,
                        "type": self._guess_file_type(file_obj.get("name", ""), file_url)
                    }
                    files_data.append(file_data)

        return files_data

    def generate_embed_html(self, file_data: Dict) -> str:
        """
        ファイルをHTMLで埋め込み表示するためのコードを生成

        Args:
            file_data: ファイル情報

        Returns:
            HTML埋め込みコード
        """
        file_type = file_data.get("type", "")
        file_url = file_data.get("url", "")
        file_name = file_data.get("name", "Unnamed")

        if "image" in file_type:
            return f"""
            <div class="file-embed image-embed">
                <img src="{file_url}" alt="{file_name}" style="max-width: 100%;">
                <div class="file-name">{file_name}</div>
            </div>
            """
        elif "video" in file_type:
            return f"""
            <div class="file-embed video-embed">
                <video controls style="max-width: 100%;">
                    <source src="{file_url}" type="{file_type}">
                    Your browser does not support the video tag.
                </video>
                <div class="file-name">{file_name}</div>
            </div>
            """
        elif "audio" in file_type:
            return f"""
            <div class="file-embed audio-embed">
                <audio controls>
                    <source src="{file_url}" type="{file_type}">
                    Your browser does not support the audio tag.
                </audio>
                <div class="file-name">{file_name}</div>
            </div>
            """
        else:
            # その他のファイルタイプはダウンロードリンクを提供
            return f"""
            <div class="file-embed link-embed">
                <a href="{file_url}" target="_blank" download="{file_name}">
                    {file_name}
                </a>
            </div>
            """

    def generate_page_with_files(self, database_id: str, page_id: Optional[str] = None) -> str:
        """
        ページ内のファイルを埋め込んだHTMLページを生成

        Args:
            database_id: データベースID
            page_id: ページID (指定した場合はそのページのみ取得)

        Returns:
            HTML文字列
        """
        files = self.get_upload_files(database_id, page_id)
        embeds = [self.generate_embed_html(file) for file in files]

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Notion Files</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 20px; }}
                .file-embed {{ margin-bottom: 20px; border: 1px solid #eaeaea; border-radius: 5px; padding: 10px; }}
                .file-name {{ margin-top: 5px; font-size: 14px; color: #37352f; }}
                .image-embed img {{ max-width: 100%; height: auto; border-radius: 3px; }}
                .video-embed video {{ max-width: 100%; border-radius: 3px; }}
                .audio-embed {{ padding: 10px; }}
                .link-embed a {{ color: #0b6bcb; text-decoration: none; display: block; padding: 10px; }}
                .link-embed a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h2>アップロードファイル</h2>
            <div class="files-container">
                {"".join(embeds) if embeds else "<p>ファイルが見つかりませんでした</p>"}
            </div>
        </body>
        </html>
        """

        return html

    def _guess_file_type(self, file_name: str, file_url: str) -> str:
        """
        ファイル名とURLからファイルタイプを推測

        Args:
            file_name: ファイル名
            file_url: ファイルURL

        Returns:
            MIMEタイプ
        """
        # 拡張子からMIMEタイプを推測
        file_type, _ = mimetypes.guess_type(file_name)

        if not file_type:
            # ファイル名からわからない場合は拡張子から推測
            _, ext = os.path.splitext(file_name)
            if ext.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']:
                file_type = f'image/{ext.lower()[1:]}'
            elif ext.lower() in ['.mp4', '.webm', '.ogg', '.mov']:
                file_type = f'video/{ext.lower()[1:]}'
            elif ext.lower() in ['.mp3', '.wav', '.ogg', '.m4a']:
                file_type = f'audio/{ext.lower()[1:]}'
            else:
                file_type = 'application/octet-stream'

        return file_type

    def _check_existing_embed_blocks(self, page_id: str) -> Tuple[bool, List[str]]:
        """
        ページ内に既存の埋め込みブロックがあるか確認し、あれば削除用IDリストを返す

        Args:
            page_id: ページID

        Returns:
            (埋め込みブロックの有無, 削除すべきブロックIDのリスト)
        """
        existing_blocks = self.client.get_all_block_children(page_id)

        has_embed_content = False
        blocks_to_delete = []
        in_embed_section = False

        for block in existing_blocks:
            block_type = block.get("type")
            block_id = block.get("id")

            # 埋め込みマーカーヘッダーを見つけた場合
            if block_type == "heading_3":
                rich_text = block.get("heading_3", {}).get("rich_text", [])
                if rich_text and any(text.get("plain_text") == self.embed_marker for text in rich_text):
                    has_embed_content = True
                    in_embed_section = True
                    blocks_to_delete.append(block_id)
                    continue

            # マーカーの後のブロックは削除対象
            if in_embed_section:
                blocks_to_delete.append(block_id)

                # 別のヘッダーが出てきたら埋め込みセクション終了
                if block_type in ["heading_1", "heading_2", "heading_3"]:
                    rich_text = block.get(block_type, {}).get("rich_text", [])
                    if rich_text and all(text.get("plain_text") != self.embed_marker for text in rich_text):
                        in_embed_section = False

        return has_embed_content, blocks_to_delete

    def _remove_existing_embed_blocks(self, page_id: str) -> bool:
        """
        ページ内の既存の埋め込みブロックを削除

        Args:
            page_id: ページID

        Returns:
            削除が行われたかどうか
        """
        has_embed, blocks_to_delete = self._check_existing_embed_blocks(page_id)

        if has_embed and blocks_to_delete:
            print(f"ページ {page_id} から既存の埋め込みブロックを {len(blocks_to_delete)} 個削除します")
            for block_id in blocks_to_delete:
                try:
                    self.client.delete_block(block_id)
                except Exception as e:
                    print(f"ブロック {block_id} の削除に失敗しました: {e}")
            return True

        return False

    def create_file_blocks_for_notion(self, file_data: Dict) -> List[Dict]:
        """
        ファイル情報からNotionブロックを作成

        Args:
            file_data: ファイル情報

        Returns:
            Notionブロックのリスト
        """
        blocks = []
        file_type = file_data.get("type", "")
        file_url = file_data.get("url", "")
        file_name = file_data.get("name", "Unnamed")

        # ファイル種類によって異なるブロックを作成
        if "image" in file_type:
            # 画像ブロック
            image_block = {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {
                        "url": file_url
                    },
                    "caption": [{
                        "type": "text",
                        "text": {
                            "content": file_name
                        }
                    }]
                }
            }
            blocks.append(image_block)
        elif "video" in file_type:
            # 動画ブロック
            video_block = {
                "object": "block",
                "type": "video",
                "video": {
                    "type": "external",
                    "external": {
                        "url": file_url
                    },
                    "caption": [{
                        "type": "text",
                        "text": {
                            "content": file_name
                        }
                    }]
                }
            }
            blocks.append(video_block)
        elif "audio" in file_type:
            # 音声ファイルはEmbedブロックとして追加
            embed_block = {
                "object": "block",
                "type": "embed",
                "embed": {
                    "url": file_url
                }
            }
            blocks.append(embed_block)

            # 音声ファイルの場合はファイル名を別のブロックで表示
            caption_block = {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {
                            "content": f"ファイル名: {file_name}"
                        }
                    }]
                }
            }
            blocks.append(caption_block)
        else:
            # その他のファイルはファイルブロックとして追加
            file_block = {
                "object": "block",
                "type": "file",
                "file": {
                    "type": "external",
                    "external": {
                        "url": file_url
                    }
                }
            }
            blocks.append(file_block)

            # ファイル名を表示するパラグラフブロック
            caption_block = {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {
                            "content": f"ファイル名: {file_name}"
                        }
                    }]
                }
            }
            blocks.append(caption_block)

        return blocks

    def embed_files_to_notion_pages(self, database_id: str, page_id: Optional[str] = None, update_existing: bool = True) -> List[str]:
        """
        アップロードフォームテーブルの各ページにファイルを埋め込む

        Args:
            database_id: データベースID
            page_id: 特定のページID (指定した場合はそのページのみ処理)
            update_existing: 既存の埋め込みを上書きするかどうか

        Returns:
            処理されたページIDのリスト
        """
        # ファイル情報を取得
        files = self.get_upload_files(database_id, page_id)
        processed_pages = []

        # ページごとにグループ化
        page_files = {}
        for file_data in files:
            current_page_id = file_data.get("page_id")
            if current_page_id:
                if current_page_id not in page_files:
                    page_files[current_page_id] = []
                page_files[current_page_id].append(file_data)

        # 各ページにファイルを埋め込み
        for page_id, file_list in page_files.items():
            try:
                # 既存の埋め込みを確認・削除
                if update_existing:
                    self._remove_existing_embed_blocks(page_id)

                # ヘッダーブロックを追加(埋め込みマーカーとなる)
                header_block = {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{
                            "type": "text",
                            "text": {
                                "content": self.embed_marker
                            }
                        }]
                    }
                }

                all_blocks = [header_block]

                # ページ内の各ファイルに対応するブロックを作成
                for file_data in file_list:
                    blocks = self.create_file_blocks_for_notion(file_data)
                    all_blocks.extend(blocks)

                    # セパレータを追加（最後のファイル以外）
                    if file_data != file_list[-1]:
                        all_blocks.append({
                            "object": "block",
                            "type": "divider",
                            "divider": {}
                        })

                # ページにブロックを追加
                if all_blocks:
                    self.client.append_blocks(page_id, all_blocks)
                    processed_pages.append(page_id)
                    print(f"ページ {page_id} にファイルを埋め込みました。")
            except Exception as e:
                print(f"ページ {page_id} へのファイル埋め込みに失敗しました: {e}")

        return processed_pages
