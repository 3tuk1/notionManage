import os
import json
import io
import base64
import mimetypes

from typing import Optional, Tuple
from urllib.request import urlopen

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


class GoogleDriveClient:
    """Google Drive APIクライアント"""

    # フォルダ構造の定義
    ROOT_FOLDER_NAME = "Notion"
    FOLDER_TYPES = {
        "image": "画像",
        "video": "動画",
        "audio": "音声",
        "other": "その他"
    }

    def __init__(self, service_account_key: str = None):
        """
        Google Drive APIクライアントの初期化

        Args:
            service_account_key: サービスアカウントのJSON鍵（Base64エンコード）
        """
        # サービスアカウントの認証情報を作成
        if not service_account_key:
            # 環境変数から取得
            service_account_key = os.environ.get("GDRIVE_KEY")

        if not service_account_key:
            raise ValueError("Google Service Account鍵が見つかりません。GDRIVE_KEY環境変数を設定してください。")

        try:
            # Base64デコードしてJSONとして読み込む
            if ';base64,' in service_account_key:
                # データURIスキーム形式の場合
                _, encoded = service_account_key.split(';base64,')
                service_account_info = json.loads(base64.b64decode(encoded).decode('utf-8'))
            elif service_account_key.startswith('{'):
                # JSON文字列の場合
                service_account_info = json.loads(service_account_key)
            else:
                # Base64エンコード文字列の場合
                service_account_info = json.loads(base64.b64decode(service_account_key).decode('utf-8'))

            # サービスアカウントの認証情報を作成
            self.credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/drive']
            )

            # Drive APIクライアントを作成
            self.service = build('drive', 'v3', credentials=self.credentials)

            # キャッシュしたフォルダID
            self.folder_ids = {}

            # 共有先メールアドレス（環境変数から取得）
            self.share_with_email = os.environ.get("GDRIVE_SHARE_EMAIL", "")

            # フォルダ構造を初期化
            self._init_folder_structure()

        except Exception as e:
            raise ValueError(f"Google Drive APIクライアントの初期化に失敗しました: {e}")

    def _find_folder(self, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """
        特定の名前のフォルダを検索

        Args:
            folder_name: フォルダ名
            parent_id: 親フォルダのID（指定なしの場合はルート）

        Returns:
            フォルダID。見つからなければNone
        """
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        try:
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)'
            ).execute()

            items = results.get('files', [])

            if items:
                return items[0]['id']
            else:
                return None

        except Exception as e:
            return None

    def _create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        """
        フォルダを作成

        Args:
            folder_name: フォルダ名
            parent_id: 親フォルダのID（指定なしの場合はルート）

        Returns:
            作成されたフォルダのID
        """
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }

        if parent_id:
            file_metadata['parents'] = parent_id  # 型の不一致を修正

        folder = self.service.files().create(
            body=file_metadata,
            fields='id'
        ).execute()

        folder_id = folder['id']

        # フォルダを共有設定
        self._share_folder(folder_id)

        return folder_id

    def _share_folder(self, folder_id: str) -> None:
        """
        フォルダを特定のユーザーと共有する

        Args:
            folder_id: 共有するフォルダID
        """
        # anyone with linkに設定
        anyone_permission = {
            'type': 'anyone',
            'role': 'reader'
        }

        self.service.permissions().create(
            fileId=folder_id,
            body=anyone_permission
        ).execute()

        # 特定ユーザーと共有（管理者権限）
        if self.share_with_email:
            try:
                user_permission = {
                    'type': 'user',
                    'role': 'writer',  # writer権限を付与
                    'emailAddress': self.share_with_email
                }

                self.service.permissions().create(
                    fileId=folder_id,
                    body=user_permission,
                    sendNotificationEmail=False  # 通知メールを送信しない
                ).execute()

            except Exception as e:
                pass

    def _get_or_create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        """
        フォルダを検索し、なければ作成

        Args:
            folder_name: フォルダ名
            parent_id: 親フォルダのID（指定なしの場合はルート）

        Returns:
            フォルダID
        """
        folder_id = self._find_folder(folder_name, parent_id)
        if not folder_id:
            folder_id = self._create_folder(folder_name, parent_id)
        else:
            # 既存のフォルダでも共有設定を確認/更新
            self._share_folder(folder_id)
        return folder_id

    def _init_folder_structure(self) -> None:
        """
        Notion用のフォルダ構造を初期化

        Returns:
            None
        """
        try:
            # ルートフォルダ（Notion）を作成
            root_id = self._get_or_create_folder(self.ROOT_FOLDER_NAME)
            self.folder_ids["root"] = root_id

            # サブフォルダ（画像、動画、音声、その他）を作成
            for folder_type, folder_name in self.FOLDER_TYPES.items():
                folder_id = self._get_or_create_folder(folder_name, root_id)
                self.folder_ids[folder_type] = folder_id

        except Exception as e:
            pass

    def _get_folder_id_by_mime_type(self, mime_type: str) -> str:
        """
        MIMEタイプから適切なフォルダIDを取得

        Args:
            mime_type: ファイルのMIMEタイプ

        Returns:
            フォルダID
        """
        if "image" in mime_type:
            return self.folder_ids.get("image", self.folder_ids.get("root"))
        elif "video" in mime_type:
            return self.folder_ids.get("video", self.folder_ids.get("root"))
        elif "audio" in mime_type:
            return self.folder_ids.get("audio", self.folder_ids.get("root"))
        else:
            return self.folder_ids.get("other", self.folder_ids.get("root"))

    def upload_file_from_url(self, file_url: str, file_name: str, mime_type: Optional[str] = None) -> Tuple[str, str]:
        """
        URLからファイルをダウンロードしてGoogle Driveにアップロード

        Args:
            file_url: ファイルのURL
            file_name: 保存するファイル名
            mime_type: ファイルのMIMEタイプ（Noneの場合は自動検出）

        Returns:
            (file_id, view_url): アップロードされたファイルのIDとビューURL
        """
        try:
            # URLからファイルをダウンロード
            response = urlopen(file_url)
            file_content = response.read()

            # MIMEタイプが指定されていない場合は、ファイル名から推測
            if not mime_type:
                mime_type, _ = mimetypes.guess_type(file_name)
                if not mime_type:
                    # デフォルトのMIMEタイプ
                    mime_type = 'application/octet-stream'

            # ファイルタイプに応じたフォルダIDを取得
            parent_folder_id = self._get_folder_id_by_mime_type(mime_type)
            folder_type = "その他"
            for key, folder_id in self.folder_ids.items():
                if folder_id == parent_folder_id and key in self.FOLDER_TYPES:
                    folder_type = self.FOLDER_TYPES.get(key, "その他")
                    break

            # ファイルをメモリ上のバッファに読み込み
            file_buffer = io.BytesIO(file_content)

            # Google Driveにアップロード
            media = MediaIoBaseUpload(file_buffer, mimetype=mime_type, resumable=True)

            # ファイルメタデータ
            file_metadata = {
                'name': file_name,
                'parents': [parent_folder_id]
            }

            # アップロード実行
            uploaded_file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()

            # ファイルIDを取得
            file_id = uploaded_file.get('id')
            view_link = uploaded_file.get('webViewLink')

            if not file_id:
                raise ValueError("ファイルアップロードに失敗しました: ファイルIDが取得できません")

            return file_id, view_link

        except Exception as e:
            raise ValueError(f"ファイルのアップロード中にエラーが発生しました: {e}")

    def delete_file(self, file_id: str) -> bool:
        """
        Google Drive上のファイルを削除

        Args:
            file_id: 削除するファイルのID

        Returns:
            成功した場合はTrue
        """
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except Exception as e:
            return False

    def get_folder_share_url(self, folder_type: str = "root") -> str:
        """
        フォルダの共有URLを取得

        Args:
            folder_type: フォルダタイプ ("root", "image", "video", "audio", "other")

        Returns:
            共有URL
        """
        folder_id = self.folder_ids.get(folder_type)
        if not folder_id:
            return ""

        return f"https://drive.google.com/drive/folders/{folder_id}"

    def upload_file(self, file_path: str, mime_type: Optional[str] = None) -> str:
        """
        ファイルをGoogle Driveにアップロードし、共有可能なリンクを返す

        Args:
            file_path: アップロードするファイルのパス
            mime_type: ファイルのMIMEタイプ（省略可能）

        Returns:
            共有可能なファイルリンク
        """
        file_name = os.path.basename(file_path)
        mime_type = mime_type or mimetypes.guess_type(file_path)[0] or 'application/octet-stream'

        # ファイルをアップロード
        file_metadata = {
            'name': file_name,
            'parents': [self.folder_ids.get('other', 'root')],  # デフォルトで「その他」フォルダにアップロード
        }
        media = MediaIoBaseUpload(io.FileIO(file_path, 'rb'), mimetype=mime_type)
        uploaded_file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        # ファイルを共有可能に設定
        if self.share_with_email:
            self.service.permissions().create(
                fileId=uploaded_file['id'],
                body={
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': self.share_with_email
                },
                fields='id'
            ).execute()

        return uploaded_file['webViewLink']
