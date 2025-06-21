import json
import mimetypes
import os
from typing import Dict, List, Optional, Tuple
import requests

from .notion_client import NotionClient
from .google_drive import GoogleDriveClient


class NotionFileViewer:
    """Notionのファイル表示用クラス"""

    def __init__(self, token: str = None, google_service_account_key: str = None):
        """
        初期化

        Args:
            token: Notion API トークン (Noneの場合は環境変数から取得)
            google_service_account_key: Google Driveサービスアカウントのキー
        """
        # ハードコードされたカラムIDを設定（環境変数から取得できない場合のフォールバック）
        self.upload_column_id = "Sb%3Au"  # アップロードカラムのID

        self.client = NotionClient(token)

        # Google Driveクライアントを初期化（サービスアカウントキーが指定されている場合）
        self.google_drive_client = None
        try:
            self.google_drive_client = GoogleDriveClient(google_service_account_key)
            print("Google Driveへのアップロード機能が有効です")
        except Exception as e:
            print(f"Google Drive機能は無効です: {e}")
            print("注意: Google Drive機能がない場合、ファイルの埋め込みが正しく表示されない可能性があります")

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

        # テーブルキーが単純な文字列の場合
        if (len(table_key_json) > 30 and
            not table_key_json.startswith('{') and
            not table_key_json.startswith('[') and
            not table_key_json.startswith('"')):
            print(f"単一の文字列IDとしてテーブルキーを処理: {env_var_name}")
            # アップロードフォームテーブルの場合は特別な処理
            if env_var_name == "UPLOADFORM_TABLEKEY":
                # アップロードカラムのIDを返す
                return {"アップロード": self.upload_column_id}
            return {}

        try:
            return json.loads(table_key_json)
        except json.JSONDecodeError:
            print(f"警告: {env_var_name}環境変数の形式が正しくありません")
            # アップロードフォームテーブルの場合は特別な処理
            if env_var_name == "UPLOADFORM_TABLEKEY":
                # アップロードカラムのIDを返す
                return {"アップロード": self.upload_column_id}
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
            print(f"警告: アップロードカラムのIDが見つかりません。ハードコードされたIDを使用: {self.upload_column_id}")
            upload_key = self.upload_column_id

        # 各ページ（テーブルの各行）を処理
        for page in results.get("results", []):
            # このページ（row）のID
            current_page_id = page.get("id")
            properties = page.get("properties", {})

            print(f"ページ {current_page_id} のプロパティを処理中...")
            print(f"利用可能なプロパティ: {', '.join(properties.keys())}")

            # このページの「アップロード」カラムの値を取得
            upload_files = properties.get(upload_key, {})

            if not upload_files:
                print(f"警告: ページ {current_page_id} でアップロードカラム({upload_key})が見つかりません")
                # IDでも名前でも見つからない場合はfiles型のプロパティを探す
                for prop_name, prop_value in properties.items():
                    prop_type = prop_value.get("type")
                    if prop_type == "files":
                        print(f"代替: '{prop_name}' (type: {prop_type})を使用")
                        upload_files = prop_value
                        break

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
                    print(f"ファイル追加: {file_data['name']}")

        print(f"合計 {len(files_data)} 個のファイルを見つけました")
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

    def _upload_to_drive(self, file_data: Dict) -> Dict:
        """
        ファイルをGoogle Driveにアップロード

        Args:
            file_data: ファイル情報

        Returns:
            更新されたファイル情報（Google DriveのURL付き）
        """
        # Google Driveクライアントが利用可能かチェック
        if not self.google_drive_client:
            print("警告: Google Driveクライアントが初期化されていません。元のURLを使用します。")
            return file_data

        try:
            file_url = file_data.get("url", "")
            file_name = file_data.get("name", "Unnamed")
            file_type = file_data.get("type", "")

            print(f"ファイル '{file_name}' をGoogle Driveにアップロード中...")

            # Google Driveにアップロード
            file_id, embed_url = self.google_drive_client.upload_file_from_url(file_url, file_name, file_type)

            # 更新したURLをファイルデータに追加
            updated_file_data = dict(file_data)
            updated_file_data["original_url"] = file_url
            updated_file_data["url"] = embed_url
            updated_file_data["google_drive_id"] = file_id

            print(f"Google Driveへのアップロード成功: {embed_url}")

            return updated_file_data
        except Exception as e:
            print(f"Google Driveへのアップロードに失敗しました: {e}")
            print("元のURLを使用します。")
            return file_data

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

        # Google Driveが利用可能な場合は、ファイルをアップロードしてURLを置き換え
        if self.google_drive_client:
            drive_file_data = self._upload_to_drive(file_data)
            file_url = drive_file_data.get("url")
            original_url = drive_file_data.get("original_url", "")
            file_id = drive_file_data.get("google_drive_id", "")

        print(f"ファイル '{file_name}' のブロック作成 (タイプ: {file_type})")

        # ファイル種類によって異なるブロックを作成
        if "image" in file_type:
            print(f"画像ファイルとして処理: {file_url}")
            preview_type = is_previewable_url(file_url)
            if preview_type == 'image':
                image_block = {
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "external",
                        "external": {
                            "url": file_url
                        }
                    }
                }
                blocks.append(image_block)
            elif preview_type == 'embed':
                embed_block = {
                    "object": "block",
                    "type": "embed",
                    "embed": {
                        "url": file_url
                    }
                }
                blocks.append(embed_block)
            else:
                # Google Driveや未サポートURLはリンクのみ
                link_block = {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "type": "text",
                            "text": {
                                "content": f"画像: {file_name}",
                                "link": {"url": file_url}
                            }
                        }]
                    }
                }
                blocks.append(link_block)

        elif "video" in file_type:
            print(f"動画ファイルとして処理: {file_url}")
            preview_type = is_previewable_url(file_url)
            if preview_type == 'video':
                video_block = {
                    "object": "block",
                    "type": "video",
                    "video": {
                        "type": "external",
                        "external": {
                            "url": file_url
                        }
                    }
                }
                blocks.append(video_block)
            elif preview_type == 'embed':
                embed_block = {
                    "object": "block",
                    "type": "embed",
                    "embed": {
                        "url": file_url
                    }
                }
                blocks.append(embed_block)
            else:
                # Google Driveや未サポートURLはリンクのみ
                link_block = {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "type": "text",
                            "text": {
                                "content": f"動画を開く: {file_name}",
                                "link": {"url": file_url}
                            }
                        }]
                    }
                }
                blocks.append(link_block)

        elif "audio" in file_type:
            print(f"音声ファイルとして処理: {file_url}")

            # 音声ファイル用のブロック (Notionは専用のaudioブロックをサポートしていない)
            # リンクとして表示
            audio_link_block = {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {
                            "content": f"🔊 音声を再生: {file_name}",
                            "link": {"url": file_url}
                        }
                    }]
                }
            }
            blocks.append(audio_link_block)

            # 埋め込みも試みる
            embed_block = {
                "object": "block",
                "type": "embed",
                "embed": {
                    "url": file_url
                }
            }
            blocks.append(embed_block)

        else:
            print(f"一般ファイルとして処理: {file_url}")
            # その他のファイルはリンクブロックとして追加
            link_block = {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {
                            "content": f"📄 {file_name} をダウンロード",
                            "link": {"url": file_url}
                        }
                    }]
                }
            }
            blocks.append(link_block)


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

    def migrate_nonfile_properties(self, uploadform_db_id: str, data_manage_db_id: str) -> int:
        """
        UPLOADFORM_TABLEからファイル以外の要素をDATA_MANAGE_TABLEに移動し、元データを削除する

        Args:
            uploadform_db_id: アップロードフォームテーブルのDB ID
            data_manage_db_id: データ管理テーブルのDB ID
        Returns:
            移動した件数
        """
        # 全ページ取得
        results = self.client.query_database(uploadform_db_id)
        moved_count = 0
        upload_key = self.uploadform_tablekey.get("アップロード")
        for page in results.get("results", []):
            properties = page.get("properties", {})
            # ファイル以外のプロパティのみ抽出
            new_props = {}
            for k, v in properties.items():
                if k == upload_key:
                    continue
                # "提出日時"という名前のプロパティは必ず除外
                if k == "提出日時":
                    continue
                prop_type = v.get("type")
                # created_time/last_edited_time型も除外
                if prop_type in ("created_time", "last_edited_time"):
                    continue
                if prop_type == "date":
                    date_val = v.get("date")
                    if date_val and date_val.get("start"):
                        new_props[k] = {"date": {"start": date_val["start"]}}
                elif prop_type == "title":
                    title_val = v.get("title")
                    if title_val:
                        new_props[k] = {"title": title_val}
                elif prop_type == "rich_text":
                    rich_val = v.get("rich_text")
                    if rich_val:
                        new_props[k] = {"rich_text": rich_val}
                elif prop_type == "select":
                    select_val = v.get("select")
                    if select_val:
                        new_props[k] = {"select": select_val}
                elif prop_type == "multi_select":
                    multi_val = v.get("multi_select")
                    if multi_val:
                        new_props[k] = {"multi_select": multi_val}
                elif prop_type == "number":
                    num_val = v.get("number")
                    if num_val is not None:
                        new_props[k] = {"number": num_val}
                elif prop_type == "url":
                    url_val = v.get("url")
                    if url_val:
                        new_props[k] = {"url": url_val}
                elif prop_type == "people":
                    people_val = v.get("people")
                    if people_val:
                        new_props[k] = {"people": people_val}
                elif prop_type == "email":
                    email_val = v.get("email")
                    if email_val:
                        new_props[k] = {"email": email_val}
                elif prop_type == "phone_number":
                    phone_val = v.get("phone_number")
                    if phone_val:
                        new_props[k] = {"phone_number": phone_val}
                elif prop_type == "checkbox":
                    check_val = v.get("checkbox")
                    if check_val is not None:
                        new_props[k] = {"checkbox": check_val}
                elif prop_type == "relation":
                    rel_val = v.get("relation")
                    if rel_val:
                        new_props[k] = {"relation": rel_val}
                # 他の型も必要に応じて追加
            # 空ならスキップ
            if not new_props:
                continue
            # 新規ページ作成
            create_url = f"https://api.notion.com/v1/pages"
            payload = {
                "parent": {"database_id": data_manage_db_id},
                "properties": new_props
            }
            resp = requests.post(create_url, headers=self.client.headers, json=payload)
            if resp.status_code == 200 or resp.status_code == 201:
                # 元ページ削除
                delete_url = f"https://api.notion.com/v1/pages/{page.get('id')}"
                requests.delete(delete_url, headers=self.client.headers)
                moved_count += 1
            else:
                print(f"データ移動失敗: {resp.text}")
        return moved_count

    def embed_and_migrate(self, uploadform_db_id: str, data_manage_db_id: str) -> None:
        """
        1. UPLOADFORM_TABLEの全ページにgdriveファイルのみ埋め込み
        2. ファイル以外の要素をDATA_MANAGE_TABLEに移動し、UPLOADFORM_TABLEから削除
        """
        # 1. ファイル埋め込み（gdriveのみ）
        print(f"UPLOADFORM_TABLE({uploadform_db_id})の全ページにgdriveファイルを埋め込みます...")
        self.embed_files_to_notion_pages(uploadform_db_id)
        print("ファイル埋め込み完了。ファイル以外の要素を移動します...")
        # 2. ファイル以外の要素を移動
        moved = self.migrate_nonfile_properties(uploadform_db_id, data_manage_db_id)
        print(f"{moved}件のデータをDATA_MANAGE_TABLE({data_manage_db_id})に移動し、UPLOADFORM_TABLEから削除しました。")
    def migrate_and_copy_with_file_link(self, uploadform_db_id: str, data_manage_db_id: str) -> int:
        """
        UPLOADFORM_TABLEからファイル以外の要素をDATA_MANAGE_TABLEにコピーし、
        ファイル列にはGDriveのリンクを設定する（削除はしない）
        Returns: コピーした件数
        """
        results = self.client.query_database(uploadform_db_id)
        upload_key = self.uploadform_tablekey.get("アップロード")
        file_column_key = self.data_manage_tablekey.get("ファイル") or "ファイル"
        copied_count = 0

        # コピー先テーブルのプロパティ名一覧を取得
        data_manage_props = self.client.retrieve_database(data_manage_db_id).get('properties', {})
        data_manage_keys = set(data_manage_props.keys())
        for page in results.get("results", []):
            properties = page.get("properties", {})
            new_props = {}
            page_id = page.get("id")
            # コピー先に"名前"プロパティがあればセット
            if "名前" in data_manage_keys:
                new_props["名前"] = {"title": [{"type": "text", "text": {"content": page_id}}]}
            for k, v in properties.items():
                if k == upload_key:
                    # GDriveリンクを生成して設定
                    gdrive_client = self.google_drive_client  # self.google_drive_client を使用
                    file_url = gdrive_client.upload_file(v.get("file"))  # ファイルをアップロードしてリンクを取得
                    new_props[file_column_key] = {"url": file_url}
                    continue
                if k == "提出日時":
                    continue
                if k not in data_manage_keys:
                    continue  # コピー先にないプロパティはスキップ

                prop_type = v.get("type")
                if prop_type in ("created_time", "last_edited_time"):
                    continue
                if prop_type == "date":
                    date_val = v.get("date")
                    if date_val and date_val.get("start"):
                        new_props[k] = {"date": {"start": date_val["start"]}}
                elif prop_type == "title":
                    continue  # 名前は上書きするのでスキップ
                elif prop_type == "rich_text":
                    rich_val = v.get("rich_text")
                    if rich_val:
                        new_props[k] = {"rich_text": rich_val}
                elif prop_type == "select":
                    select_val = v.get("select")
                    if select_val:
                        new_props[k] = {"select": select_val}
                elif prop_type == "multi_select":
                    multi_val = v.get("multi_select")
                    if multi_val:
                        new_props[k] = {"multi_select": multi_val}
                elif prop_type == "number":
                    num_val = v.get("number")
                    if num_val is not None:
                        new_props[k] = {"number": num_val}
                elif prop_type == "url":
                    url_val = v.get("url")
                    if url_val:
                        new_props[k] = {"url": url_val}
                elif prop_type == "people":
                    people_val = v.get("people")
                    if people_val:
                        new_props[k] = {"people": people_val}
                elif prop_type == "email":
                    email_val = v.get("email")
                    if email_val:
                        new_props[k] = {"email": email_val}
                elif prop_type == "phone_number":
                    phone_val = v.get("phone_number")
                    if phone_val:
                        new_props[k] = {"phone_number": phone_val}
                elif prop_type == "checkbox":
                    check_val = v.get("checkbox")
                    if check_val is not None:
                        new_props[k] = {"checkbox": check_val}
                elif prop_type == "relation":
                    rel_val = v.get("relation")
                    if rel_val:
                        new_props[k] = {"relation": rel_val}
                # 他の型も必要に応じて追加
            # コピー先データベースに新しいプロパティを追加
            # update_page メソッドの未解決エラーを修正
            # update_page メソッドが存在しないため、Notion API のページ作成エンドポイントを使用
            create_url = f"https://api.notion.com/v1/pages"
            payload = {
                "parent": {"database_id": data_manage_db_id},
                "properties": new_props
            }
            response = requests.post(create_url, headers=self.client.headers, json=payload)
            if response.status_code not in (200, 201):
                raise Exception(f"Failed to create page: {response.status_code}, {response.text}")

            copied_count += 1
        return copied_count
def is_previewable_url(url: str) -> str:
    """
    Notionがプレビュー対応しているサービスのURLか判定し、
    'image', 'video', 'embed' のいずれかを返す（該当しなければNone）
    """
    import re
    # Google Drive /preview であればembed
    if re.search(r"drive.google.com/.+/preview", url):
        return 'embed'
    # Google Drive 画像直リンク（uc?export=view&id=...）もembed（Notion imageブロック非対応のため）
    if re.search(r"drive.google.com/uc\?export=view&id=", url):
        return 'embed'
    # YouTube, Vimeo, Twitter, imgur, Dropbox, SoundCloud など
    if re.search(r"(youtube.com|youtu.be)", url):
        return 'video'
    if re.search(r"(vimeo.com)", url):
        return 'video'
    if re.search(r"(imgur.com|unsplash.com|images.unsplash.com)", url):
        return 'image'
    if re.search(r"(dropbox.com)", url):
        return 'image'
    if re.search(r"(twitter.com|soundcloud.com)", url):
        return 'embed'
    # 画像拡張子
    if re.search(r"\\.(jpg|jpeg|png|gif|webp|svg)(\\?|$)", url, re.IGNORECASE):
        return 'image'
    # 動画拡張子
    if re.search(r"\\.(mp4|webm|ogg|mov)(\\?|$)", url, re.IGNORECASE):
        return 'video'
    # 音声拡張子
    if re.search(r"\\.(mp3|wav|ogg|m4a)(\\?|$)", url, re.IGNORECASE):
        return 'embed'
    return ""
