import os
import json
import argparse
from notionManage.file_viewer import NotionFileViewer

# Notionデータベース（テーブル）のデフォルトID取得
def get_default_db_id():
    """
    環境変数からNotionデータベースIDを取得

    まずUPLOADFORM_DB_IDから直接取得を試み、
    なければUPLOADFORM_TABLEKEYを使用
    """
    # 直接設定されているデータベースIDを確認
    direct_db_id = os.environ.get("UPLOADFORM_DB_ID", "")
    if direct_db_id:
        print(f"UPLOADFORM_DB_IDから取得したデータベースID: {direct_db_id}")
        return direct_db_id

    # UPLOADFORM_TABLEKEYからデータベースIDを取得
    try:
        table_key = os.environ.get("UPLOADFORM_TABLEKEY", "")
        if not table_key:
            print("UPLOADFORM_TABLEKEYが設定されていません")
            return ""

        # 先頭と末尾の空白文字を削除
        table_key = table_key.strip()

        # テーブルキーが単純な文字列の場合はそのまま使用
        if (len(table_key) > 30 and
            not table_key.startswith('{') and
            not table_key.startswith('[') and
            not table_key.startswith('"')):
            print(f"テーブルキーをデータベースIDとして使用: {table_key}")
            return table_key

        # 以下は従来のJSON解析ロジック（必要に応じて）
        print(f"処理するJSONデータ（先頭50文字）: {table_key[:50]}...")

        # JSONを解析
        table_key = json.loads(table_key)

        print("JSONデータのパース成功")

        # 辞書形式の場合
        if isinstance(table_key, dict):
            # 関係カラムからデータベースIDを抽出
            for column_name, column_data in table_key.items():
                if isinstance(column_data, dict):
                    column_type = column_data.get("type", "")
                    if column_type == "relation":
                        relation_data = column_data.get("relation", {})
                        if relation_data and isinstance(relation_data, dict):
                            db_id = relation_data.get("database_id", "")
                            if db_id:
                                print(f"抽出したデータベースID: {db_id}")
                                return db_id
        # リスト形式の場合は最初の要素を使用
        elif isinstance(table_key, list) and len(table_key) > 0:
            print("JSONデータはリスト形式です")
            for item in table_key:
                if isinstance(item, dict) and "database_id" in item:
                    db_id = item.get("database_id")
                    print(f"リストから抽出したデータベースID: {db_id}")
                    return db_id

        print("データベースIDを抽出できませんでした")
    except Exception as e:
        print(f"UPLOADFORM_TABLEKEYの処理エラー: {e}")
        print(f"UPLOADFORM_TABLEKEYの内容: {table_key if 'table_key' in locals() else 'なし'}")

    return ""

# uploadformtableに対応するデータベースID
DEFAULT_UPLOADFORM_DB_ID = get_default_db_id()

def main():
    """
    メイン実行関数

    コマンドライン引数:
        --database_id: NotionデータベースのID（省略時はデフォルトのuploadformテーブルを使用）
        --output: 出力HTMLファイルのパス（デフォルト: output.html）
        --embed: ページにファイルを直接埋め込む場合はこのフラグを指定
    """
    parser = argparse.ArgumentParser(description='Notionテーブルからファイルを取得して表示')
    parser.add_argument('--database_id', help='NotionデータベースのID（省略時はデフォルトのuploadformテーブルを使用）')
    parser.add_argument('--output', default='output.html', help='出力HTMLファイルのパス')
    parser.add_argument('--embed', action='store_true', help='ページにファイルを直接埋め込む')
    parser.add_argument('--copy-to-manage', action='store_true', help='UPLOADFORM_TABLEからファイル以外のデータをDATA_MANAGE_TABLEにコピー（ファイル列はGDriveリンク）')

    args = parser.parse_args()

    # データベースIDの設定（指定がない場合はデフォルト値を使用）
    database_id = args.database_id or DEFAULT_UPLOADFORM_DB_ID
    data_manage_db_id = os.environ.get("DATA_MANAGE_TABLEKEY")

    # データベースIDが提供されていない場合はエラー
    if not database_id:
        print("エラー: データベースIDが指定されていません。以下のいずれかを設定してください。")
        print("1. --database_id コマンドライン引数")
        print("2. UPLOADFORM_DB_ID 環境変数")
        print("3. UPLOADFORM_TABLEKEY 環境変数（データベース関連情報を含むもの）")
        return

    # 環境変数からNotionトークンを取得
    token = os.environ.get("NOTION_API_KEY")
    if not token:
        print("環境変数 NOTION_API_KEY が設定されていません。")
        return

    # Google Driveサービスアカウントキーを取得
    gdrive_key = os.environ.get("GDRIVE_KEY")
    if gdrive_key:
        print("Google Drive機能が有効です")
    else:
        print("Google Drive機能は無効です (GDRIVE_KEY環境変数が設定されていません)")

    try:
        # ファイルビューアーの初期化 (Google Drive機能も初期化)
        viewer = NotionFileViewer(token=token, google_service_account_key=gdrive_key)

        # data_manage_db_idが設定されていれば必ずコピー処理を実行
        if data_manage_db_id:
            print(f"UPLOADFORM_TABLE({database_id})からファイル以外のデータをDATA_MANAGE_TABLE({data_manage_db_id})にコピーします...")
            copied = viewer.migrate_and_copy_with_file_link(database_id, data_manage_db_id)
            print(f"{copied}件コピーしました。")
            return

        if args.embed:
            print(f"uploadformテーブル (ID: {database_id}) の全ページにファイルを埋め込みます...")
            # Notionページに直接ファイルを埋め込む（常に全ページ処理）
            processed_pages = viewer.embed_files_to_notion_pages(database_id)
            if processed_pages:
                print(f"成功: {len(processed_pages)} 個のページにファイルを埋め込みました。")
                for page_id in processed_pages:
                    print(f"- ページID: {page_id}")
            else:
                print("埋め込み可能なファイルが見つからなかったか、埋め込みに失敗しました。")
        else:
            # HTMLの生成（従来の機能）- 全ページ対象
            html_content = viewer.generate_page_with_files(database_id)

            # ファイルに保存
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(html_content)

            print(f"成功: ファイルを {args.output} に保存しました。")
    except Exception as e:
        print(f"エラー: {e}")

if __name__ == "__main__":
    main()
