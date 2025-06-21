import os
import json
import argparse
from notionManage.file_viewer import NotionFileViewer

# Notionデータベース（テーブル）のデフォルトID取得
def get_default_db_id():
    """
    環境変数からNotionデータベースIDを取得

    まずUPLOADFORM_DB_IDから直接取得を試み、
    なければUPLOADFORM_TABLEKEYから関連情報を抽出
    """
    # 直接設定されているデータベースIDを確認
    direct_db_id = os.environ.get("UPLOADFORM_DB_ID", "")
    if direct_db_id:
        return direct_db_id

    # UPLOADFORM_TABLEKEYからデータベースIDを取得
    try:
        table_key_json = os.environ.get("UPLOADFORM_TABLEKEY", "{}")
        table_key = json.loads(table_key_json)

        # 関係カラムからデータベースIDを抽出
        for column_name, column_data in table_key.items():
            column_type = column_data.get("type", "")
            if column_type == "relation":
                relation_data = column_data.get("relation", {})
                if relation_data:
                    return relation_data.get("database_id", "")
    except Exception as e:
        print(f"UPLOADFORM_TABLEKEYの解析エラー: {e}")

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

    args = parser.parse_args()

    # データベースIDの設定（指定がない場合はデフォルト値を使用）
    database_id = args.database_id or DEFAULT_UPLOADFORM_DB_ID

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

    try:
        # ファイルビューアーの初期化
        viewer = NotionFileViewer(token)

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
