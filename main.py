# -*- coding: utf-8 -*-
"""NuitkaのビルドコマンドをGUIで生成・実行するアプリ."""

from __future__ import annotations

import shlex
import subprocess
import asyncio
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from typing import Any

import flet as ft


DataType = Literal["file", "dir"]
GuiFramework = Literal["none", "tkinter", "customtkinter", "flet"]


# GUIライブラリごとに必要なNuitkaオプションをまとめる。
GUI_OPTION_PRESETS: dict[GuiFramework, list[str]] = {
    "none": [],
    "tkinter": ["--enable-plugin=tk-inter"],
    "customtkinter": [
        "--enable-plugin=tk-inter",
        "--include-package-data=customtkinter",
    ],
    "flet": [
        "--include-package=flet",
        "--include-package=flet_desktop",
        "--include-package-data=flet",
        "--include-package-data=flet_desktop",
    ],
}


@dataclass
class DataEntry:
    """同梱するデータファイルまたはフォルダの設定."""

    kind: DataType
    src: Path
    dest: str


@dataclass
class AppState:
    """画面入力のうちファイル選択系の状態."""

    script_path: Path | None = None
    icon_path: Path | None = None
    output_dir: Path | None = None
    data_entries: list[DataEntry] = field(default_factory=list)


class NuitkaBuildGUI:
    """FletでNuitkaビルド用の入力画面を構成する."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.state = AppState()

        # ウィンドウとページ全体の基本設定。
        self.page.title = "Nuitka Build GUI"
        self.page.window.width = 1100
        self.page.window.height = 900
        self.page.scroll = ft.ScrollMode.AUTO

        # 入力状態とエラーを画面に表示するコントロール。
        self.script_path_text = ft.Text("未選択", selectable=True)
        self.icon_path_text = ft.Text("未選択", selectable=True)
        self.output_dir_text = ft.Text("未選択", selectable=True)
        self.status_text = ft.Text("準備完了", color=ft.Colors.BLUE)
        self.error_text = ft.Text("", color=ft.Colors.RED)

        self.mode_dropdown = ft.Dropdown(
            label="ビルド方式",
            value="standalone",
            options=[
                ft.dropdown.Option("standalone"),
                ft.dropdown.Option("onefile"),
                ft.dropdown.Option("accelerated"),
            ],
            on_select=self.on_setting_changed,
        )
        self.console_mode_dropdown = ft.Dropdown(
            label="Windowsコンソール設定",
            value="force",
            options=[
                ft.dropdown.Option("force"),
                ft.dropdown.Option("disable"),
                ft.dropdown.Option("attach"),
                ft.dropdown.Option("hide"),
            ],
            on_select=self.on_setting_changed,
        )
        self.compiler_dropdown = ft.Dropdown(
            label="コンパイラ設定",
            value="auto",
            options=[
                ft.dropdown.Option("auto", "自動"),
                ft.dropdown.Option("msvc_latest", "MSVC latest"),
                ft.dropdown.Option("mingw64", "MinGW64"),
                ft.dropdown.Option("clang", "Clang"),
                ft.dropdown.Option("zig", "Zig"),
            ],
            on_select=self.on_setting_changed,
        )
        self.gui_framework_dropdown = ft.Dropdown(
            label="GUIライブラリ",
            value="none",
            options=[
                ft.dropdown.Option("none", "なし"),
                ft.dropdown.Option("tkinter", "tkinter"),
                ft.dropdown.Option("customtkinter", "customtkinter"),
                ft.dropdown.Option("flet", "Flet"),
            ],
            tooltip="選択したGUIライブラリ向けのNuitkaオプションを追加します。",
            on_select=self.on_gui_framework_changed,
        )

        self.output_filename_field = ft.TextField(
            label="出力ファイル名",
            hint_text="例: my_app.exe (未入力ならスクリプト名)",
            on_change=self.on_setting_changed,
        )
        self.jobs_field = ft.TextField(
            label="並列ビルド数 (jobs)",
            hint_text="正の整数のみ",
            on_change=self.on_setting_changed,
        )
        self.extra_options_field = ft.TextField(
            label="追加オプション",
            hint_text="例: --include-package=pandas --enable-plugin=tk-inter",
            on_change=self.on_setting_changed,
        )

        self.cb_remove_output = ft.Checkbox(label="remove output", on_change=self.on_setting_changed)
        self.cb_assume_yes = ft.Checkbox(label="assume yes for downloads", on_change=self.on_setting_changed)
        self.cb_low_memory = ft.Checkbox(label="low memory", on_change=self.on_setting_changed)
        self.cb_show_progress = ft.Checkbox(label="show progress", on_change=self.on_setting_changed)
        self.cb_show_memory = ft.Checkbox(label="show memory", on_change=self.on_setting_changed)
        self.cb_deployment = ft.Checkbox(label="deployment mode", on_change=self.on_setting_changed)

        self.command_preview = ft.TextField(
            label="コマンドプレビュー",
            multiline=True,
            min_lines=2,
            max_lines=5,
            read_only=True,
            value="",
        )

        self.log_view = ft.TextField(
            label="実行ログ",
            multiline=True,
            min_lines=12,
            max_lines=18,
            read_only=True,
            value="",
        )

        self.data_list_view = ft.ListView(expand=False, spacing=6, height=180)

        self.run_button = ft.ElevatedButton("実行", on_click=self.run_nuitka)

        self.build_ui()
        self.update_command_preview()

    def build_ui(self) -> None:
        """画面に表示するコントロールを配置する."""

        # Column をページに追加して横幅を最大化する
        self.page.add(
            ft.Column(
                [
                    ft.Text("Nuitka Build GUI", size=28, weight=ft.FontWeight.BOLD),
                    ft.Divider(),
                    ft.Text("1. スクリプト選択", weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                "Pythonスクリプトを選択",
                                on_click=self.pick_script,
                            ),
                            self.script_path_text,
                        ]
                    ),
                    ft.Text("2-3. ビルド方式 / Windowsコンソール設定", weight=ft.FontWeight.BOLD),
                    ft.Row([self.mode_dropdown, self.console_mode_dropdown]),
                    ft.Text("4. アイコン選択", weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                "アイコンを選択",
                                on_click=self.pick_icon,
                            ),
                            self.icon_path_text,
                        ]
                    ),
                    ft.Text("5. 出力設定", weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            self.output_filename_field,
                            ft.ElevatedButton(
                                "出力先フォルダを選択",
                                on_click=self.pick_output_dir,
                            ),
                            self.output_dir_text,
                        ]
                    ),
                    ft.Text("6-8. よく使うオプション / コンパイラ / GUI / jobs", weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [self.compiler_dropdown, self.gui_framework_dropdown, self.jobs_field],
                        wrap=True,
                    ),
                    ft.ResponsiveRow(
                        controls=[
                            ft.Container(self.cb_remove_output, col={"sm": 6, "md": 4}),
                            ft.Container(self.cb_assume_yes, col={"sm": 6, "md": 4}),
                            ft.Container(self.cb_low_memory, col={"sm": 6, "md": 4}),
                            ft.Container(self.cb_show_progress, col={"sm": 6, "md": 4}),
                            ft.Container(self.cb_show_memory, col={"sm": 6, "md": 4}),
                            ft.Container(self.cb_deployment, col={"sm": 6, "md": 4}),
                        ]
                    ),
                    ft.Text("9. データファイル指定", weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                "データファイル追加",
                                on_click=self.pick_data_file,
                            ),
                            ft.ElevatedButton(
                                "データフォルダ追加",
                                on_click=self.pick_data_dir,
                            ),
                        ]
                    ),
                    self.data_list_view,
                    ft.Text("10. 追加オプション", weight=ft.FontWeight.BOLD),
                    self.extra_options_field,
                    ft.Text("11. コマンドプレビュー", weight=ft.FontWeight.BOLD),
                    self.command_preview,
                    ft.Text("12. 実行", weight=ft.FontWeight.BOLD),
                    ft.Row([self.run_button, self.status_text]),
                    self.error_text,
                    self.log_view,
                ],
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        )

    def add_log(self, message: str) -> None:
        self.log_view.value += message + "\n"
        self.log_view.update()

    def on_setting_changed(self, _: Any) -> None:
        self.update_command_preview()

    def on_gui_framework_changed(self, _: Any) -> None:
        """GUIライブラリ選択時にコンソール設定とプレビューを更新する."""

        if (
            self.gui_framework_dropdown.value != "none"
            and self.console_mode_dropdown.value == "force"
        ):
            self.console_mode_dropdown.value = "disable"
        self.update_command_preview()

    def get_selected_file_path(self, files: list[ft.FilePickerFile]) -> Path | None:
        """FilePickerの結果からローカルパスを取り出す."""
        # ft.FilePicker の戻り値 (list of FilePickerFile) を期待するが、
        # フォールバックで文字列や Path を渡すこともあるため両対応する。
        if files is None:
            return None
        if isinstance(files, list):
            if not files or getattr(files[0], "path", None) is None:
                self.error_text.value = "Error: selected file path is unavailable."
                self.page.update()
                return None
            return Path(files[0].path)
        if isinstance(files, (str, Path)):
            return Path(files)
        return None

    async def pick_script(self, _: Any) -> None:
        path = None
        try:
            files = await ft.FilePicker().pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["py"],
            )
            if not files:
                return
            path = self.get_selected_file_path(files)
            if path is None:
                # 取得失敗時は tkinter にフォールバック
                raise RuntimeError("no path from FilePicker")
        except Exception:
            try:
                path_str = await asyncio.to_thread(self._tk_pick_file, ("*.py",))
                if path_str:
                    path = Path(path_str)
            except Exception:
                path = None
        if path is None:
            return
        if path.suffix.lower() != ".py":
            self.error_text.value = "エラー: .py ファイルを選択してください。"
            self.page.update()
            return
        self.state.script_path = path
        self.script_path_text.value = str(path)
        self.error_text.value = ""
        self.update_command_preview()

    async def pick_icon(self, _: Any) -> None:
        path = None
        try:
            files = await ft.FilePicker().pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["ico"],
            )
            if not files:
                return
            path = self.get_selected_file_path(files)
            if path is None:
                raise RuntimeError("no path from FilePicker")
        except Exception:
            try:
                path_str = await asyncio.to_thread(self._tk_pick_file, ("*.ico",))
                if path_str:
                    path = Path(path_str)
            except Exception:
                path = None
        if path is None:
            return
        if path.suffix.lower() != ".ico":
            self.error_text.value = "エラー: .ico を選択してください。"
            self.page.update()
            return
        self.state.icon_path = path
        self.icon_path_text.value = str(path)
        self.error_text.value = ""
        self.update_command_preview()

    async def pick_output_dir(self, _: Any) -> None:
        try:
            path = await ft.FilePicker().get_directory_path()
            if not path:
                return
            self.state.output_dir = Path(path)
        except Exception:
            try:
                dir_path = await asyncio.to_thread(self._tk_pick_dir)
                if not dir_path:
                    return
                self.state.output_dir = Path(dir_path)
            except Exception:
                return
        self.output_dir_text.value = str(self.state.output_dir)
        self.update_command_preview()

    async def pick_data_file(self, _: Any) -> None:
        src = None
        try:
            files = await ft.FilePicker().pick_files(allow_multiple=False)
            if not files:
                return
            src = self.get_selected_file_path(files)
            if src is None:
                return
        except Exception:
            try:
                path_str = await asyncio.to_thread(self._tk_pick_file, None)
                if not path_str:
                    return
                src = Path(path_str)
            except Exception:
                return
        self.state.data_entries.append(DataEntry(kind="file", src=src, dest=src.name))
        self.refresh_data_list()
        self.update_command_preview()

    async def pick_data_dir(self, _: Any) -> None:
        src = None
        try:
            path = await ft.FilePicker().get_directory_path()
            if not path:
                return
            src = Path(path)
        except Exception:
            try:
                dir_path = await asyncio.to_thread(self._tk_pick_dir)
                if not dir_path:
                    return
                src = Path(dir_path)
            except Exception:
                return
        self.state.data_entries.append(DataEntry(kind="dir", src=src, dest=src.name))
        self.refresh_data_list()
        self.update_command_preview()

    def refresh_data_list(self) -> None:
        """追加済みデータ項目の一覧を再描画する."""

        self.data_list_view.controls.clear()
        for idx, entry in enumerate(self.state.data_entries):
            option_text = (
                f"--include-data-files={entry.src}={entry.dest}"
                if entry.kind == "file"
                else f"--include-data-dir={entry.src}={entry.dest}"
            )
            self.data_list_view.controls.append(
                ft.Row(
                    [
                        ft.Text(option_text, selectable=True, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            tooltip="削除",
                            on_click=lambda _, i=idx: self.remove_data_entry(i),
                        ),
                    ]
                )
            )
        self.data_list_view.update()

    def _tk_pick_file(self, patterns=None) -> str | None:
        """tkinter を使ったファイル選択ダイアログの同期ヘルパー。

        `patterns` は拡張子タプル（例: ("*.py",)）か None。
        戻り値は選択パスまたは None。
        """
        try:
            import tkinter as _tk
            from tkinter import filedialog as _fd

            root = _tk.Tk()
            root.withdraw()
            filetypes = None
            if patterns:
                # 単純化のため、最初のパターンだけ使う
                pattern = patterns[0]
                ext = pattern.lstrip("*.")
                filetypes = [(f"{ext} files", pattern), ("All files", "*")]
            path = _fd.askopenfilename(filetypes=filetypes)
            try:
                root.destroy()
            except Exception:
                pass
            return path or None
        except Exception:
            return None

    def _tk_pick_dir(self) -> str | None:
        """tkinter を使ったフォルダ選択ダイアログの同期ヘルパー。"""
        try:
            import tkinter as _tk
            from tkinter import filedialog as _fd

            root = _tk.Tk()
            root.withdraw()
            path = _fd.askdirectory()
            try:
                root.destroy()
            except Exception:
                pass
            return path or None
        except Exception:
            return None

    def remove_data_entry(self, index: int) -> None:
        if 0 <= index < len(self.state.data_entries):
            self.state.data_entries.pop(index)
            self.refresh_data_list()
            self.update_command_preview()

    def validate_inputs(self) -> tuple[bool, str]:
        """ビルド前に必須入力と数値入力を検証する."""

        if self.state.script_path is None:
            return False, "エラー: Pythonスクリプトを選択してください。"
        if self.state.script_path.suffix.lower() != ".py":
            return False, "エラー: 選択したファイルが .py ではありません。"

        jobs_text = (self.jobs_field.value or "").strip()
        if jobs_text:
            if not jobs_text.isdigit() or int(jobs_text) <= 0:
                return False, "エラー: jobs は正の整数で入力してください。"
        return True, ""

    def get_output_filename(self) -> str | None:
        """出力ファイル名を.exe付きで返す."""

        if self.state.script_path is None:
            return None
        entered = (self.output_filename_field.value or "").strip()
        if not entered:
            entered = self.state.script_path.stem + ".exe"
        if not entered.lower().endswith(".exe"):
            entered += ".exe"
        return entered

    def build_command(self) -> list[str]:
        """現在の画面入力からNuitka実行コマンドを組み立てる."""

        if self.state.script_path is None:
            return [sys.executable, "-m", "nuitka"]

        cmd: list[str] = [sys.executable, "-m", "nuitka"]

        # Nuitka のオプションはフラグ方式なので、UI の選択を堅くマッピングする。
        # - standalone: --standalone
        # - onefile: --standalone --onefile
        # - accelerated: 通常（非-standalone）にして --standalone を付けない
        mode_value = self.mode_dropdown.value or "standalone"
        if mode_value == "standalone":
            cmd.append("--standalone")
        elif mode_value == "onefile":
            cmd.append("--standalone")
            cmd.append("--onefile")
        elif mode_value == "accelerated":
            # accelerated は現状 standalone にしない（要件次第で変更）
            pass
        console_value = self.console_mode_dropdown.value or "force"
        cmd.append(f"--windows-console-mode={console_value}")
        cmd.extend(self.get_gui_framework_options())

        if self.state.icon_path:
            cmd.append(f"--windows-icon-from-ico={str(self.state.icon_path)}")

        output_filename = self.get_output_filename()
        if output_filename:
            cmd.append(f"--output-filename={output_filename}")

        if self.state.output_dir:
            cmd.append(f"--output-dir={str(self.state.output_dir)}")

        if self.cb_remove_output.value:
            cmd.append("--remove-output")
        if self.cb_assume_yes.value:
            cmd.append("--assume-yes-for-downloads")
        if self.cb_low_memory.value:
            cmd.append("--low-memory")
        if self.cb_show_progress.value:
            cmd.append("--show-progress")
        if self.cb_show_memory.value:
            cmd.append("--show-memory")
        if self.cb_deployment.value:
            cmd.append("--deployment")

        compiler_map = {
            "auto": None,
            "msvc_latest": "--msvc=latest",
            "mingw64": "--mingw64",
            "clang": "--clang",
            "zig": "--zig",
        }
        comp_opt = compiler_map[self.compiler_dropdown.value or "auto"]
        if comp_opt:
            cmd.append(comp_opt)


        for entry in self.state.data_entries:
            if entry.kind == "file":
                cmd.append(f"--include-data-files={entry.src}={entry.dest}")
            else:
                cmd.append(f"--include-data-dir={entry.src}={entry.dest}")

        jobs_text = (self.jobs_field.value or "").strip()
        if jobs_text:
            cmd.append(f"--jobs={jobs_text}")

        extra_text = (self.extra_options_field.value or "").strip()
        if extra_text:
            cmd.extend(shlex.split(extra_text, posix=False))

        cmd.append(str(self.state.script_path))
        return cmd

    def get_gui_framework_options(self) -> list[str]:
        """選択中のGUIライブラリに対応するNuitkaオプションを返す."""

        framework = self.gui_framework_dropdown.value or "none"
        if framework in GUI_OPTION_PRESETS:
            return GUI_OPTION_PRESETS[framework]
        return []

    def quote_for_preview(self, cmd: list[str]) -> str:
        # Windows向けの安全なクォート。
        return subprocess.list2cmdline(cmd)

    def update_command_preview(self) -> None:
        """入力検証の結果に合わせてコマンドプレビューを更新する."""

        valid, msg = self.validate_inputs()
        if not valid and self.state.script_path is None:
            self.command_preview.value = "スクリプトを選択するとコマンドが表示されます。"
            self.error_text.value = ""
        elif not valid:
            self.command_preview.value = ""
            self.error_text.value = msg
        else:
            self.error_text.value = ""
            cmd = self.build_command()
            self.command_preview.value = self.quote_for_preview(cmd)

        self.page.update() # ←常に更新

    def run_nuitka(self, _: Any) -> None:
        """ビルド処理をバックグラウンドスレッドで開始する."""

        valid, msg = self.validate_inputs()
        if not valid:
            self.error_text.value = msg
            self.page.update()
            return

        cmd = self.build_command()
        self.log_view.value = ""
        self.status_text.value = "ビルド実行中..."
        self.status_text.color = ft.Colors.ORANGE
        self.error_text.value = ""
        self.run_button.disabled = True
        self.page.update()

        # 非推奨のスレッド経由 UI 更新を避け、async ベースで実行する。
        # `page.run_task` にコルーチンを渡して非同期でビルドを実行する。
        # `page.run_task` が利用可能か確認してからコルーチンを生成する。
        run_task = getattr(self.page, "run_task", None)
        if callable(run_task):
            try:
                # コルーチンオブジェクトを事前に生成しないように
                # コルーチン関数と引数を渡す（Flet のバージョン差異対策）。
                run_task(self._execute_build, cmd)
                return
            except Exception:
                # 例外が出たら同期実行のフォールバックへ落とす
                pass

        # フォールバックで既存のスレッド実行を使う（互換性保険）
        thread = threading.Thread(target=self._execute_build_sync, args=(cmd,), daemon=True)
        thread.start()

    async def _execute_build(self, cmd: list[str]) -> None:
        """非同期で Nuitka を実行し、標準出力をログ欄へ反映する."""

        try:
            # コマンド表示
            self.add_log("[CMD] " + self.quote_for_preview(cmd))

            # 非同期サブプロセスで実行
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            assert proc.stdout is not None
            # stdout を行単位で読み取り、ログへ追加
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="replace").rstrip("\n")
                except Exception:
                    text = str(line)
                self.add_log(text)

            return_code = await proc.wait()

            # 終了処理（UI 更新）
            self.add_log(f"\n終了コード: {return_code}")
            if return_code == 0:
                self.status_text.value = "ビルド完了"
                self.status_text.color = ft.Colors.GREEN
            else:
                self.status_text.value = "ビルド失敗"
                self.status_text.color = ft.Colors.RED
            self.run_button.disabled = False
            self.page.update()
        except Exception as ex:
            self.add_log(f"例外発生: {ex}")
            self.status_text.value = "ビルド失敗"
            self.status_text.color = ft.Colors.RED
            self.error_text.value = f"エラー: {ex}"
            self.run_button.disabled = False
            self.page.update()

    def _execute_build_sync(self, cmd: list[str]) -> None:
        """後方互換：従来のスレッド実行を維持するための同期ヘルパー。"""

        try:
            self.page.run_thread(lambda: self.add_log("[CMD] " + self.quote_for_preview(cmd)))
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
                encoding="utf-8",
                errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.page.run_thread(lambda msg=line.rstrip("\n"): self.add_log(msg))

            return_code = proc.wait()

            def finish() -> None:
                self.add_log(f"\n終了コード: {return_code}")
                if return_code == 0:
                    self.status_text.value = "ビルド完了"
                    self.status_text.color = ft.Colors.GREEN
                else:
                    self.status_text.value = "ビルド失敗"
                    self.status_text.color = ft.Colors.RED
                self.run_button.disabled = False
                self.page.update()

            self.page.run_thread(finish)
        except Exception as ex:
            def fail(e=ex) -> None:
                self.add_log(f"例外発生: {e}")
                self.status_text.value = "ビルド失敗"
                self.status_text.color = ft.Colors.RED
                self.error_text.value = f"エラー: {e}"
                self.run_button.disabled = False
                self.page.update()

            self.page.run_thread(fail)


def main(page: ft.Page) -> None:
    NuitkaBuildGUI(page)


if __name__ == "__main__":
    ft.app(target=main)
