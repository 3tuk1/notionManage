import os
import json
import io
import base64
from typing import Dict, List, Optional, Any, Tuple
from urllib.request import urlopen

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


class GoogleDriveClient:
    """Google Drive APIクライアント"""

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

            print("Google Drive APIクライアントの初期化に成功しました")
        except Exception as e:
            raise ValueError(f"Google Drive APIクライアントの初期化に失敗しました: {e}")

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
            print(f"ファイル '{file_name}' をURLからダウンロード中: {file_url}")

            # URLからファイルをダウンロード
            response = urlopen(file_url)
            file_content = response.read()

            # MIMEタイプが指定されていない場合は、ファイル名から推測
            if not mime_type:
                mime_type, _ = mimetypes.guess_type(file_name)
                if not mime_type:
                    # デフォルトのMIMEタイプ
                    mime_type = 'application/octet-stream'

            print(f"ファイル '{file_name}' をGoogle Driveにアップロード中 (タイプ: {mime_type})")

            # ファイルをメモリ上のバッファに読み込み
            file_buffer = io.BytesIO(file_content)

            # Google Driveにアップロード
            media = MediaIoBaseUpload(file_buffer, mimetype=mime_type, resumable=True)

            # ファイルメタデータ
            file_metadata = {
                'name': file_name,
                # anyoneが閲覧可能に設定
                'permissionIds': ['anyoneWithLink']
            }

            # アップロード実行
            uploaded_file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            # ファイルIDを取得
            file_id = uploaded_file.get('id')

            if not file_id:
                raise ValueError("ファイルアップロードに失敗しました: ファイルIDが取得できません")

            print(f"アップロード成功: ファイルID = {file_id}")

            # 権限を設定（anyoneが閲覧可能に）
            permission = {
                'type': 'anyone',
                'role': 'reader'
            }
            self.service.permissions().create(
                fileId=file_id,
                body=permission
            ).execute()

            # 閲覧用URLを構築
            view_url = f"https://drive.google.com/file/d/{file_id}/view"

            # ファイルタイプごとに適切なビューURLを生成
            if "image" in mime_type:
                embed_url = f"https://drive.google.com/uc?export=view&id={file_id}"
            elif "video" in mime_type:
                embed_url = f"https://drive.google.com/file/d/{file_id}/preview"
            elif "audio" in mime_type:
                embed_url = f"https://drive.google.com/file/d/{file_id}/preview"
            else:
                embed_url = view_url

            return file_id, embed_url

        except Exception as e:
            print(f"ファイルのアップロードに失敗しました: {e}")
            raise

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
            print(f"ファイル (ID: {file_id}) の削除に成功しました")
            return True
        except Exception as e:
            print(f"ファイルの削除に失敗しました: {e}")
            return False
