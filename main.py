from __future__ import annotations

import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import sys

import flet as ft


DataType = Literal["file", "dir"]


@dataclass
class DataEntry:
    kind: DataType
    src: Path
    dest: str


@dataclass
class AppState:
    script_path: Path | None = None
    icon_path: Path | None = None
    output_dir: Path | None = None
    data_entries: list[DataEntry] | None = None

    def __post_init__(self) -> None:
        if self.data_entries is None:
            self.data_entries = []


class NuitkaBuildGUI:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.state = AppState()

        self.page.title = "Nuitka Build GUI"
        self.page.window.width = 1100
        self.page.window.height = 900
        self.page.scroll = ft.ScrollMode.AUTO

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
            on_change=self.on_setting_changed,
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
            on_change=self.on_setting_changed,
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
            on_change=self.on_setting_changed,
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

        self.script_picker = ft.FilePicker(on_result=self.on_script_picked)
        self.icon_picker = ft.FilePicker(on_result=self.on_icon_picked)
        self.output_dir_picker = ft.FilePicker(on_result=self.on_output_dir_picked)
        self.data_file_picker = ft.FilePicker(on_result=self.on_data_file_picked)
        self.data_dir_picker = ft.FilePicker(on_result=self.on_data_dir_picked)

        self.page.overlay.extend(
            [
                self.script_picker,
                self.icon_picker,
                self.output_dir_picker,
                self.data_file_picker,
                self.data_dir_picker,
            ]
        )

        self.build_ui()
        self.update_command_preview()

    def build_ui(self) -> None:
        self.page.add(
            ft.Text("Nuitka Build GUI", size=28, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            ft.Text("1. スクリプト選択", weight=ft.FontWeight.BOLD),
            ft.Row(
                [
                    ft.ElevatedButton(
                        "Pythonスクリプトを選択",
                        on_click=lambda _: self.script_picker.pick_files(
                            allow_multiple=False,
                            file_type=ft.FilePickerFileType.CUSTOM,
                            allowed_extensions=["py"],
                        ),
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
                        on_click=lambda _: self.icon_picker.pick_files(
                            allow_multiple=False,
                            file_type=ft.FilePickerFileType.CUSTOM,
                            allowed_extensions=["ico", "png"],
                        ),
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
                        on_click=lambda _: self.output_dir_picker.get_directory_path(),
                    ),
                    self.output_dir_text,
                ]
            ),
            ft.Text("6-8. よく使うオプション / コンパイラ / jobs", weight=ft.FontWeight.BOLD),
            ft.Row([self.compiler_dropdown, self.jobs_field]),
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
                        on_click=lambda _: self.data_file_picker.pick_files(allow_multiple=False),
                    ),
                    ft.ElevatedButton(
                        "データフォルダ追加",
                        on_click=lambda _: self.data_dir_picker.get_directory_path(),
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

    def on_script_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        path = Path(e.files[0].path)
        if path.suffix.lower() != ".py":
            self.error_text.value = "エラー: .py ファイルを選択してください。"
            self.page.update()
            return
        self.state.script_path = path
        self.script_path_text.value = str(path)
        self.error_text.value = ""
        self.update_command_preview()

    def on_icon_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        path = Path(e.files[0].path)
        if path.suffix.lower() not in {".ico", ".png"}:
            self.error_text.value = "エラー: .ico または .png を選択してください。"
            self.page.update()
            return
        self.state.icon_path = path
        self.icon_path_text.value = str(path)
        self.error_text.value = ""
        self.update_command_preview()

    def on_output_dir_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        self.state.output_dir = Path(e.path)
        self.output_dir_text.value = str(self.state.output_dir)
        self.update_command_preview()

    def on_data_file_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        src = Path(e.files[0].path)
        self.state.data_entries.append(DataEntry(kind="file", src=src, dest=src.name))
        self.refresh_data_list()
        self.update_command_preview()

    def on_data_dir_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        src = Path(e.path)
        self.state.data_entries.append(DataEntry(kind="dir", src=src, dest=src.name))
        self.refresh_data_list()
        self.update_command_preview()

    def refresh_data_list(self) -> None:
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
        if self.state.script_path is None:
            return None
        entered = self.output_filename_field.value.strip()
        if not entered:
            entered = self.state.script_path.stem + ".exe"
        if not entered.lower().endswith(".exe"):
            entered += ".exe"
        return entered

    def build_command(self) -> list[str]:
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

    def quote_for_preview(self, cmd: list[str]) -> str:
        # Windows向けの安全なクォート
        return subprocess.list2cmdline(cmd)

    def update_command_preview(self) -> None:
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
