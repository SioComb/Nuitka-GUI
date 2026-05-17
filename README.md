# Nuitka-GUI

Nuitka のビルドコマンドを GUI で作成し、実行できる Flet 製アプリです。

## 機能

- Python スクリプト、出力先、アイコン、データファイルを GUI から指定
- `standalone` / `onefile` / `accelerated` のビルドモード選択
- Windows コンソール表示設定の切り替え
- `tkinter` / `customtkinter` / `Flet` 向けの Nuitka オプション追加
- コンパイラ、jobs、よく使うオプション、追加オプションの指定
- 実行前の Nuitka コマンドプレビュー表示

## 必要環境

- Python 3.12 以上
- Windows
- C/C++ コンパイラ
  - MSVC Build Tools、MinGW64、Clang、Zig など
- `uv` または `pip`

## セットアップ

`uv` を使う場合:

```powershell
uv sync
uv run python main.py
```

`pip` を使う場合:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 使い方

1. `Pythonスクリプトを選択` でビルド対象の `.py` ファイルを選びます。
2. ビルドモード、Windows コンソール設定、GUI ライブラリを選びます。
3. 必要に応じてアイコン、出力先、データファイル、追加オプションを設定します。
4. コマンドプレビューを確認します。
5. `実行` ボタンで Nuitka ビルドを開始します。

## GUI ライブラリ設定

`GUIライブラリ` の選択により、以下の Nuitka オプションが自動追加されます。

| 選択肢 | 追加される主なオプション |
| --- | --- |
| なし | 追加なし |
| tkinter | `--enable-plugin=tk-inter` |
| customtkinter | `--enable-plugin=tk-inter`, `--include-package-data=customtkinter` |
| Flet | `--include-package=flet`, `--include-package=flet_desktop`, package data 同梱 |

GUI ライブラリを選ぶと、コンソール設定が初期値の `force` の場合は `disable` に自動変更されます。

## トラブルシュート

`No module named nuitka` が出る場合は、実行中の Python 環境に Nuitka が入っていません。

```powershell
uv sync
```

または:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Flet アプリをビルドする場合は、Flet のデスクトップ実行に必要なファイルが初回実行時に取得されることがあります。ネットワーク制限がある環境では、事前に Flet の実行環境を準備してください。
