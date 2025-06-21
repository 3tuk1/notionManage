import os
import argparse
from notionManage.file_viewer import NotionFileViewer

# Notionデータベース（テーブル）のデフォルトID
# uploadformtableに対応するデータベースID
DEFAULT_UPLOADFORM_DB_ID = os.environ.get("UPLOADFORM_DB_ID", "")

def main():
    """
    メイン実行関数

    コマンドライン引数:
        --database_id: NotionデータベースのID（省略時はデフォルトのuploadformテーブルを使用）
        --page_id: 特定のページID（指定しない場合は全ページ）
        --output: 出力HTMLファイルのパス（デフォルト: output.html）
        --embed: ページにファイルを直接埋め込む場合はこのフラグを指定
    """
    parser = argparse.ArgumentParser(description='Notionテーブルからファイルを取得して表示')
    parser.add_argument('--database_id', help='NotionデータベースのID（省略時はデフォルトのuploadformテーブルを使用）')
    parser.add_argument('--page_id', help='特定のページID（指定しない場合は全ページ）')
    parser.add_argument('--output', default='output.html', help='出力HTMLファイルのパス')
    parser.add_argument('--embed', action='store_true', help='ページにファイルを直接埋め込む')

    args = parser.parse_args()

    # データベースIDの設定（指定がない場合はデフォルト値を使用）
    database_id = args.database_id or DEFAULT_UPLOADFORM_DB_ID

    # データベースIDが提供されていない場合はエラー
    if not database_id:
        print("エラー: データベースIDが指定されていません。--database_id引数を指定するか、UPLOADFORM_DB_ID環境変数を設定してください。")
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
            print(f"uploadformテーブル (ID: {database_id}) の各ページにファイルを埋め込みます...")
            # Notionページに直接ファイルを埋め込む
            processed_pages = viewer.embed_files_to_notion_pages(database_id, args.page_id)
            if processed_pages:
                print(f"成功: {len(processed_pages)} 個のページにファイルを埋め込みました。")
                for page_id in processed_pages:
                    print(f"- ページID: {page_id}")
            else:
                print("埋め込み可能なファイルが見つからなかったか、埋め込みに失敗しました。")
        else:
            # HTMLの生成（従来の機能）
            html_content = viewer.generate_page_with_files(database_id, args.page_id)

            # ファイルに保存
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(html_content)

            print(f"成功: ファイルを {args.output} に保存しました。")
    except Exception as e:
        print(f"エラー: {e}")

if __name__ == "__main__":
    main()
