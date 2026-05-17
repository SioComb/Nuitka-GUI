# -*- coding: utf-8 -*-
"""NuitkaのビルドコマンドをGUIで生成・実行するアプリ."""

from __future__ import annotations

import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    data_entries: list[DataEntry] | None = None

    def __post_init__(self) -> None:
        if self.data_entries is None:
            self.data_entries = []


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

        self.file_picker = ft.FilePicker()

        self.build_ui()
        self.update_command_preview()

    def build_ui(self) -> None:
        """画面に表示するコントロールを配置する."""

        self.page.add(
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
        )

    def add_log(self, message: str) -> None:
        self.log_view.value += message + "\n"
        self.log_view.update()

    def on_setting_changed(self, _: ft.ControlEvent) -> None:
        self.update_command_preview()

    def on_gui_framework_changed(self, _: ft.ControlEvent) -> None:
        """GUIライブラリ選択時にコンソール設定とプレビューを更新する."""

        if (
            self.gui_framework_dropdown.value != "none"
            and self.console_mode_dropdown.value == "force"
        ):
            self.console_mode_dropdown.value = "disable"
        self.update_command_preview()

    def get_selected_file_path(self, files: list[ft.FilePickerFile]) -> Path | None:
        """FilePickerの結果からローカルパスを取り出す."""

        if not files or files[0].path is None:
            self.error_text.value = "Error: selected file path is unavailable."
            self.page.update()
            return None
        return Path(files[0].path)

    async def pick_script(self, _: ft.ControlEvent) -> None:
        files = await self.file_picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["py"],
        )
        path = self.get_selected_file_path(files)
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

    async def pick_icon(self, _: ft.ControlEvent) -> None:
        files = await self.file_picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["ico", "png"],
        )
        path = self.get_selected_file_path(files)
        if path is None:
            return
        if path.suffix.lower() not in {".ico", ".png"}:
            self.error_text.value = "エラー: .ico または .png を選択してください。"
            self.page.update()
            return
        self.state.icon_path = path
        self.icon_path_text.value = str(path)
        self.error_text.value = ""
        self.update_command_preview()

    async def pick_output_dir(self, _: ft.ControlEvent) -> None:
        path = await self.file_picker.get_directory_path()
        if not path:
            return
        self.state.output_dir = Path(path)
        self.output_dir_text.value = str(self.state.output_dir)
        self.update_command_preview()

    async def pick_data_file(self, _: ft.ControlEvent) -> None:
        files = await self.file_picker.pick_files(allow_multiple=False)
        src = self.get_selected_file_path(files)
        if src is None:
            return
        self.state.data_entries.append(DataEntry(kind="file", src=src, dest=src.name))
        self.refresh_data_list()
        self.update_command_preview()

    async def pick_data_dir(self, _: ft.ControlEvent) -> None:
        path = await self.file_picker.get_directory_path()
        if not path:
            return
        src = Path(path)
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

        jobs_text = self.jobs_field.value.strip()
        if jobs_text:
            if not jobs_text.isdigit() or int(jobs_text) <= 0:
                return False, "エラー: jobs は正の整数で入力してください。"
        return True, ""

    def get_output_filename(self) -> str | None:
        """出力ファイル名を.exe付きで返す."""

        if self.state.script_path is None:
            return None
        entered = self.output_filename_field.value.strip()
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

        mode_map = {
            "standalone": "--mode=standalone",
            "onefile": "--mode=onefile",
            "accelerated": "--mode=accelerated",
        }
        cmd.append(mode_map[self.mode_dropdown.value])
        cmd.append(f"--windows-console-mode={self.console_mode_dropdown.value}")
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
        comp_opt = compiler_map[self.compiler_dropdown.value]
        if comp_opt:
            cmd.append(comp_opt)

        jobs_text = self.jobs_field.value.strip()
        if jobs_text:
            cmd.append(f"--jobs={jobs_text}")

        for entry in self.state.data_entries:
            if entry.kind == "file":
                cmd.append(f"--include-data-files={entry.src}={entry.dest}")
            else:
                cmd.append(f"--include-data-dir={entry.src}={entry.dest}")

        extra_text = self.extra_options_field.value.strip()
        if extra_text:
            cmd.extend(shlex.split(extra_text, posix=False))

        cmd.append(str(self.state.script_path))
        return cmd

    def get_gui_framework_options(self) -> list[str]:
        """選択中のGUIライブラリに対応するNuitkaオプションを返す."""

        framework = self.gui_framework_dropdown.value
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
            self.page.update()

    def run_nuitka(self, _: ft.ControlEvent) -> None:
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

        thread = threading.Thread(target=self._execute_build, args=(cmd,), daemon=True)
        thread.start()

    def _execute_build(self, cmd: list[str]) -> None:
        """Nuitkaを実行し、標準出力をログ欄へ反映する."""

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
                self.page.run_thread(lambda l=line.rstrip("\n"): self.add_log(l))

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
            def fail() -> None:
                self.add_log(f"例外発生: {ex}")
                self.status_text.value = "ビルド失敗"
                self.status_text.color = ft.Colors.RED
                self.error_text.value = f"エラー: {ex}"
                self.run_button.disabled = False
                self.page.update()

            self.page.run_thread(fail)


def main(page: ft.Page) -> None:
    NuitkaBuildGUI(page)


if __name__ == "__main__":
    ft.app(target=main)
