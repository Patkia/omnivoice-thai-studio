#!/usr/bin/env python3
"""Thai TTS Studio v1: a native PySide6 frontend for the frozen Engine v1."""

from __future__ import annotations

import sys
import threading
import subprocess
import os
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from PySide6.QtCore import QSettings, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHeaderView, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit, QProgressBar, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from long_text_batch import is_long
from studio_generation import generate_studio_request
from quick_voice_preview import PreviewTextError, preview_output_path, select_preview_text


class _LazyModule:
    """Proxy a heavy runtime module until a user action needs it."""
    def __init__(self, name: str):
        self.name = name
        self.module = None

    def _load(self):
        if self.module is None:
            self.module = importlib.import_module(self.name)
        return self.module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


batch_runner = _LazyModule("tts_batch_runner")
csv_batch = _LazyModule("csv_batch")

# Compatibility aliases keep existing Studio tests and integrations patchable;
# resolving these symbols only imports the lightweight CSV module.
read_csv = csv_batch.read_csv
batch_voice_project = csv_batch.batch_voice_project
default_project_output_dir = csv_batch.default_project_output_dir
validate_rows = csv_batch.validate_rows
row_diagnostic = csv_batch.row_diagnostic
write_launch_diagnostic = csv_batch.write_launch_diagnostic
new_mission_id = csv_batch.new_mission_id
build_job = csv_batch.build_job
write_job = csv_batch.write_job
CsvBatchError = csv_batch.CsvBatchError
VoiceTargetResolutionError = csv_batch.VoiceTargetResolutionError

DONE = "DONE"
ERROR = "ERROR"
GENERATING = "GENERATING"
PENDING = "PENDING"
SKIPPED = "SKIPPED"


class TtsInputError(ValueError):
    """Lightweight input error used before the heavy runtime is loaded."""


def _load_voice_aliases_light() -> dict:
    return json.loads((ROOT / "approved_voice_profiles.json").read_text(encoding="utf-8")).get("aliases", {})


def _voice_profile_light(alias: str) -> dict:
    data = json.loads((ROOT / "approved_voice_profiles.json").read_text(encoding="utf-8"))
    aliases = data.get("aliases", {})
    alias_data = aliases.get(alias)
    if not alias_data:
        raise TtsInputError(f"unknown voice alias: {alias}")
    key = alias_data.get("profile_key")
    for section in ("approved", "usable", "experimental_secondary"):
        profile = data.get(section, {}).get(key)
        if profile:
            return {"alias": alias, **alias_data, **profile}
    raise TtsInputError(f"voice profile not found: {key}")


def default_output_path(now: datetime | None = None) -> Path:
    now = now or datetime.now()
    return ROOT / "output" / "studio" / f"tts_{now:%Y%m%d_%H%M%S}.wav"


def load_voice_aliases() -> dict:
    return _load_voice_aliases_light()


def preview_text(*args, **kwargs):
    from studio_engine_adapter import preview_text as _preview_text
    return _preview_text(*args, **kwargs)


def preview_single_input_text(*args, **kwargs):
    from studio_engine_adapter import preview_single_input_text as _preview_single
    return _preview_single(*args, **kwargs)


if TYPE_CHECKING:
    from studio_engine_adapter import StudioEngineAdapter


ROOT = Path(__file__).resolve().parent

ENGINE_NOT_LOADED = "NOT_LOADED"
ENGINE_LOADING = "LOADING"
ENGINE_READY = "READY"
ENGINE_FAILED = "FAILED"


class EngineInitWorker(QThread):
    """Import and warm the frozen runtime away from the Qt main thread."""
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def run(self) -> None:
        try:
            from studio_engine_adapter import StudioEngineAdapter
            adapter = StudioEngineAdapter()
            adapter.ensure_engine_loaded(status=self.progress.emit)
            self.ready.emit(adapter)
        except Exception as exc:
            self.failed.emit(str(exc))


class GenerateWorker(QThread):
    finished_result = Signal(dict)
    failed = Signal(str)
    progress = Signal(int, int, str)

    def __init__(self, adapter: Any, text: str, alias: str, speed: float, steps: int, output: Path, force: bool):
        super().__init__()
        self.adapter, self.text, self.alias, self.speed, self.steps, self.output, self.force = adapter, text, alias, speed, steps, output, force
        self.cancel_event = threading.Event()
    def cancel(self): self.cancel_event.set()

    def run(self) -> None:
        try:
            self.finished_result.emit(generate_studio_request(
                self.adapter, self.text, self.alias, self.speed, self.steps,
                self.output, self.force, cancelled=self.cancel_event.is_set,
                progress=lambda i, n, s: self.progress.emit(i, n, s)))
        except Exception as exc:
            self.failed.emit(str(exc))


class QuickPreviewWorker(QThread):
    """Independent short preview; deliberately never calls the long-text path."""
    finished_result = Signal(dict)
    failed = Signal(str)

    def __init__(self, adapter: Any, text: str, alias: str, speed: float,
                 steps: int, output: Path):
        super().__init__()
        self.adapter, self.text, self.alias = adapter, text, alias
        self.speed, self.steps, self.output = speed, steps, output

    def run(self) -> None:
        try:
            self.finished_result.emit(
                self.adapter.generate(self.text, self.alias, self.speed, self.steps, self.output, force=False)
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class StudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Thai TTS Studio")
        self.settings = QSettings("OmniVoiceThai", "ThaiTTSStudio")
        self.adapter: Any | None = None
        self.engine_state = ENGINE_NOT_LOADED
        self.engine_error: str | None = None
        self.engine_worker: EngineInitWorker | None = None
        self._pending_engine_action: Callable[[Any], None] | None = None
        self.player, self.audio = QMediaPlayer(), QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.worker: GenerateWorker | None = None
        self.preview_worker: QuickPreviewWorker | None = None
        self.batch_rows: list[Any] = []
        self.batch_csv_path: Path | None = None
        self.batch_mission_id: str | None = None
        self.batch_job_path: Path | None = None
        self.batch_launcher: subprocess.Popen | None = None
        self.batch_diagnostic_path: Path | None = None
        self.batch_diagnostic: dict | None = None
        self._batch_refreshing = False
        self._batch_output_user_selected = False
        self.batch_timer = QTimer(self)
        self.batch_timer.setInterval(350)
        self.batch_timer.timeout.connect(self.poll_batch_status)
        self._build()
        self._restore_settings()
        self.model_label.setText("Engine: Not loaded")

    def _build(self) -> None:
        root, layout = QWidget(), QVBoxLayout()
        root.setLayout(layout)
        root.setMinimumWidth(1240)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.studio_scroll = QScrollArea()
        self.studio_scroll.setWidgetResizable(True)
        self.studio_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.studio_scroll.setWidget(root)
        self.setCentralWidget(self.studio_scroll)
        title = QLabel("Thai TTS Studio"); title.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(title); layout.addWidget(QLabel("Local Thai Text-to-Speech  •  Engine v1")); self.model_label = QLabel("โมเดล: ยังไม่ได้โหลด"); layout.addWidget(self.model_label)
        layout.addWidget(QLabel("ข้อความ"))
        self.editor = QPlainTextEdit(); self.editor.setMinimumHeight(150); self.editor.setPlaceholderText("พิมพ์หรือวางข้อความภาษาไทยที่นี่"); self.editor.textChanged.connect(self._update_count); layout.addWidget(self.editor, 1)
        count_row = QHBoxLayout(); self.count_label = QLabel("0 ตัวอักษร"); self.clear_button = QPushButton("ล้างข้อความ"); self.clear_button.clicked.connect(self.editor.clear); count_row.addWidget(self.count_label); count_row.addStretch(); count_row.addWidget(self.clear_button); layout.addLayout(count_row)
        tools = QHBoxLayout(); open_txt = QPushButton("เปิดไฟล์ TXT"); save_txt = QPushButton("บันทึกข้อความ"); open_txt.clicked.connect(self.open_text); save_txt.clicked.connect(self.save_text); tools.addWidget(open_txt); tools.addWidget(save_txt); tools.addStretch(); layout.addLayout(tools)
        form = QFormLayout(); self.voice = QComboBox(); self.aliases = load_voice_aliases(); self.voice.addItems(self.aliases.keys()); self.voice.currentTextChanged.connect(self._voice_changed)
        self.preview_button = QPushButton("🔊 ทดลองเสียง"); self.preview_button.clicked.connect(self.quick_preview)
        voice_row = QHBoxLayout(); voice_row.addWidget(self.voice); voice_row.addWidget(self.preview_button); form.addRow("เสียง", voice_row)
        self.description = QLabel(); self.description.setWordWrap(True); form.addRow("คำอธิบาย", self.description)
        self.speed = QDoubleSpinBox(); self.speed.setRange(0.25, 1.20); self.speed.setSingleStep(0.01); self.speed.setSuffix("x"); form.addRow("ความเร็ว", self.speed)
        self.output = QLabel(); choose = QPushButton("เลือก..."); choose.clicked.connect(self.choose_output); out_row = QHBoxLayout(); out_row.addWidget(self.output, 1); out_row.addWidget(choose); form.addRow("ไฟล์ปลายทาง", out_row); layout.addLayout(form)
        advanced = QGroupBox("ตัวเลือกเพิ่มเติม"); advanced.setCheckable(True); advanced.setChecked(False); adv = QFormLayout(); self.steps = QSpinBox(); self.steps.setRange(1, 100); self.steps.setValue(32); self.force = QCheckBox("สร้างใหม่แม้มี Cache"); self.show_normalized = QCheckBox("แสดงข้อความหลัง normalization"); adv.addRow("Steps", self.steps); adv.addRow(self.force); adv.addRow(self.show_normalized); advanced.setLayout(adv); layout.addWidget(advanced)
        self._build_csv_batch_panel(layout)
        layout.addWidget(QLabel("ข้อความที่จะส่งเข้า TTS")); self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setMaximumBlockCount(200); layout.addWidget(self.preview)
        actions = QGridLayout()
        self.check_button = QPushButton("ตรวจข้อความ")
        self.generate_button = QPushButton("สร้างเสียง")
        self.play_button = QPushButton("▶ เล่น")
        self.stop_button = QPushButton("■ หยุด")
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.check_button.clicked.connect(self.check_text)
        self.generate_button.clicked.connect(self.generate)
        self.play_button.clicked.connect(self.play)
        self.stop_button.clicked.connect(self.stop_action)
        actions.addWidget(self.check_button, 0, 0)
        actions.addWidget(self.generate_button, 0, 1)
        actions.addWidget(self.play_button, 0, 2)
        actions.addWidget(self.stop_button, 0, 3)
        layout.addLayout(actions)
        self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(0); layout.addWidget(self.progress); self.status = QLabel("พร้อมใช้งาน"); layout.addWidget(self.status)
        self._voice_changed(self.voice.currentText()); self.output.setText(str(default_output_path()))

    def _build_csv_batch_panel(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("CSV Batch")
        panel = QVBoxLayout()
        panel.setContentsMargins(14, 16, 14, 14)
        panel.setSpacing(12)

        top_controls = QGroupBox("นำเข้า CSV และ Output")
        top_layout = QVBoxLayout()
        source_row = QHBoxLayout()
        self.import_csv_button = QPushButton("Import CSV")
        self.import_csv_button.clicked.connect(self.import_csv)
        self.batch_csv_label = QLabel("ยังไม่ได้เลือก CSV")
        self.batch_csv_label.setWordWrap(True)
        source_row.addWidget(self.import_csv_button)
        source_row.addWidget(self.batch_csv_label, 1)
        top_layout.addLayout(source_row)

        output_row = QHBoxLayout()
        self.batch_output_label = QLabel(str(ROOT / "output" / "studio" / "batch"))
        self.choose_batch_output_button = QPushButton("เลือก Output directory")
        self.choose_batch_output_button.clicked.connect(self.choose_batch_output_directory)
        output_row.addWidget(QLabel("Batch output:"))
        output_row.addWidget(self.batch_output_label, 1)
        output_row.addWidget(self.choose_batch_output_button)
        top_layout.addLayout(output_row)
        self.batch_resolution_summary = QLabel("Resolved config: รอ import CSV")
        self.batch_resolution_summary.setWordWrap(True)
        top_layout.addWidget(self.batch_resolution_summary)
        top_controls.setLayout(top_layout)
        panel.addWidget(top_controls)

        selection_controls = QGroupBox("การเลือกรายการ")
        selection_layout = QHBoxLayout()
        select_row = QHBoxLayout()
        self.select_all_batch_button = QPushButton("Select All")
        self.deselect_all_batch_button = QPushButton("Deselect All")
        self.select_all_batch_button.clicked.connect(lambda: self.set_batch_selection(True))
        self.deselect_all_batch_button.clicked.connect(lambda: self.set_batch_selection(False))
        self.overwrite_batch = QCheckBox("เขียนทับเฉพาะ row ที่เลือก")
        selection_layout.addWidget(self.select_all_batch_button)
        selection_layout.addWidget(self.deselect_all_batch_button)
        selection_layout.addWidget(self.overwrite_batch)
        selection_layout.addStretch()
        selection_controls.setLayout(selection_layout)
        panel.addWidget(selection_controls)

        self.batch_table = QTableWidget(0, 11)
        self.batch_table.setHorizontalHeaderLabels([
            "เลือก", "#", "file_name", "character_name", "gender", "voice_target",
            "profile_alias", "thai_text", "TTS input (override)",
            "pronunciation_note / prosody_note", "status",
        ])
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_table.setWordWrap(True)
        self.batch_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.batch_table.setAlternatingRowColors(True)
        self.batch_table.setMinimumWidth(1240)
        self.batch_table.setMinimumHeight(400)
        self.batch_table.verticalHeader().setDefaultSectionSize(56)
        self.batch_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header = self.batch_table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(self.batch_table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self.batch_table.itemChanged.connect(self._batch_table_item_changed)
        panel.addWidget(self.batch_table)

        action_controls = QGroupBox("การสร้างเสียง")
        action_layout = QVBoxLayout()
        action_row = QHBoxLayout()
        self.generate_batch_button = QPushButton("Generate Selected Batch")
        self.stop_batch_button = QPushButton("Stop Batch")
        self.resume_batch_button = QPushButton("Resume Batch")
        self.open_batch_output_button = QPushButton("Open Output Folder")
        self.generate_batch_button.clicked.connect(self.generate_csv_batch)
        self.stop_batch_button.clicked.connect(self.stop_csv_batch)
        self.resume_batch_button.clicked.connect(self.resume_csv_batch)
        self.open_batch_output_button.clicked.connect(self.open_batch_output_directory)
        self.stop_batch_button.setEnabled(False)
        self.resume_batch_button.setEnabled(False)
        action_row.addWidget(self.generate_batch_button)
        action_row.addWidget(self.stop_batch_button)
        action_row.addWidget(self.resume_batch_button)
        action_row.addWidget(self.open_batch_output_button)
        action_row.addStretch()
        action_layout.addLayout(action_row)
        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 1)
        self.batch_progress.setValue(0)
        self.batch_status = QLabel("พร้อม import CSV")
        action_layout.addWidget(self.batch_progress)
        action_layout.addWidget(self.batch_status)
        action_controls.setLayout(action_layout)
        panel.addWidget(action_controls)
        box.setLayout(panel)
        layout.addWidget(box)

    def _batch_output_dir(self) -> Path:
        return Path(self.batch_output_label.text())

    def choose_batch_output_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "เลือก output directory สำหรับ CSV Batch", self.batch_output_label.text())
        if path:
            self.batch_output_label.setText(path)
            self._batch_output_user_selected = True
            if self.batch_rows:
                self.validate_batch_rows()

    def import_csv(self) -> None:
        if self._batch_is_running():
            return
        path, _ = QFileDialog.getOpenFileName(self, "เลือก CSV", "", "CSV (*.csv)")
        if not path:
            return
        try:
            self.batch_rows = read_csv(Path(path))
            self.batch_csv_path = Path(path)
            self.batch_mission_id = None
            self.batch_job_path = None
            project = batch_voice_project(self.batch_rows)
            if project and not self._batch_output_user_selected:
                self.batch_output_label.setText(str(default_project_output_dir(project)))
            self.validate_batch_rows(reset_selection=True)
            self.batch_csv_label.setText(path)
            self.batch_status.setText(f"นำเข้า CSV {len(self.batch_rows)} row แล้ว")
        except CsvBatchError as exc:
            self.batch_rows = []
            self.refresh_batch_table()
            self.batch_status.setText(str(exc))
            QMessageBox.warning(self, "CSV ไม่ผ่าน validation", str(exc))

    def validate_batch_rows(self, *, reset_selection: bool = False) -> None:
        if not self.batch_rows:
            return
        try:
            validate_rows(
                self.batch_rows, self._batch_output_dir(), self.voice.currentText(),
                speed=self.speed.value(), steps=self.steps.value(),
                reset_selection=reset_selection,
                defer_text_gate=reset_selection,
                skip_existing=not self.overwrite_batch.isChecked(),
            )
            self.refresh_batch_table()
            self._update_batch_resolution_summary()
        except Exception as exc:
            self.batch_status.setText(f"ตรวจ CSV ไม่ผ่าน: {exc}")
            self.batch_resolution_summary.setText(f"Resolved config: ERROR — {exc}")

    def _update_batch_resolution_summary(self) -> None:
        """Show the resolved non-text config without adding more crowded columns."""
        configs = [row.resolved_config for row in self.batch_rows if row.resolved_config]
        if not configs:
            errors = [row.error for row in self.batch_rows if row.error]
            self.batch_resolution_summary.setText(
                "Resolved config: ERROR — " + (errors[0] if errors else "ไม่มี row ที่พร้อมสร้างเสียง")
            )
            return
        unique = []
        seen = set()
        for config in configs:
            key = (config.voice_project, config.voice_target, config.profile_alias,
                   config.generation_mode, config.instruction,
                   config.speed, config.steps, config.seed,
                   config.reference_conditioning, config.reference_audio,
                   config.reference_sha256)
            if key not in seen:
                seen.add(key)
                unique.append(config)
        entries = []
        for config in unique:
            target = config.voice_target or "(Studio UI fallback)"
            entries.append(
                f"Voice Project: {config.voice_project or '(none)'} | "
                f"Voice Target: {target} | Profile Alias: {config.profile_alias} | "
                f"Generation Mode: {config.generation_mode} | "
                f"Instruction: {config.instruction or 'NONE (reference identity only)'} | Speed: {config.speed:.2f} | "
                f"Steps: {config.steps} | Seed: {config.seed} | "
                f"Reference Conditioning: {'ON' if config.reference_conditioning else 'OFF'}"
                + (f" | Reference: {config.reference_audio}" if config.reference_audio else "")
            )
        self.batch_resolution_summary.setText("Resolved config:\n" + "\n".join(entries))

    def refresh_batch_table(self) -> None:
        self._batch_refreshing = True
        self.batch_table.blockSignals(True)
        self.batch_table.setRowCount(len(self.batch_rows))
        for table_row, row in enumerate(self.batch_rows):
            selected = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            if row.status == ERROR:
                flags = Qt.ItemFlag.NoItemFlags
            selected.setFlags(flags)
            selected.setCheckState(Qt.CheckState.Checked if row.selected else Qt.CheckState.Unchecked)
            selected.setData(Qt.ItemDataRole.UserRole, table_row)
            self.batch_table.setItem(table_row, 0, selected)
            values = [
                str(table_row + 1), row.file_name, row.metadata("character_name"),
                row.metadata("gender"), row.metadata("voice_target"),
                row.resolved_config.profile_alias if row.resolved_config else "—",
                row.thai_text,
                row.spoken_text if row.tts_text else "—",
                " / ".join(part for part in (row.metadata("pronunciation_note"), row.metadata("prosody_note")) if part),
                row.status if not row.error else f"{row.status}: {row.error}",
            ]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if column == 8 and row.tts_text:
                    item.setToolTip(f"Canonical:\n{row.thai_text}\n\nTTS input:\n{row.spoken_text}")
                else:
                    item.setToolTip(value)
                self.batch_table.setItem(table_row, column, item)
        self.batch_table.blockSignals(False)
        self._batch_refreshing = False
        self._adjust_csv_table_layout()

    def _adjust_csv_table_layout(self) -> None:
        """Keep CSV metadata readable; scroll instead of squeezing narrow columns."""
        if not hasattr(self, "batch_table"):
            return
        table = self.batch_table
        available = max(table.viewport().width(), 1240)
        fixed = {
            0: 58,   # select
            1: 48,   # row number
            2: 260,  # file name
            3: 170,  # character
            4: 90,   # gender
            5: 160,  # voice target
            6: 160,  # resolved voice profile
            8: 320,  # explicit TTS override
            9: 340,  # pronunciation / prosody notes
            10: 190, # status
        }
        for column, width in fixed.items():
            table.setColumnWidth(column, width)
        thai_width = max(360, available - sum(fixed.values()) - 20)
        table.setColumnWidth(7, thai_width)
        table.resizeRowsToContents()
        for row in range(table.rowCount()):
            table.setRowHeight(row, max(56, table.rowHeight(row)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._adjust_csv_table_layout)

    def _batch_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._batch_refreshing or item.column() != 0:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < len(self.batch_rows):
            self.batch_rows[index].selected = item.checkState() == Qt.CheckState.Checked

    def set_batch_selection(self, selected: bool) -> None:
        for row in self.batch_rows:
            if row.status != ERROR:
                row.selected = selected
        self.refresh_batch_table()

    def _batch_is_running(self) -> bool:
        return bool(self.batch_launcher and self.batch_launcher.poll() is None)

    def _begin_batch_diagnostic(self, mission_id: str) -> None:
        paths = batch_runner._mission_paths(mission_id)
        self.batch_mission_id = mission_id
        self.batch_diagnostic_path = paths["base"] / "launch_diagnostic.json"
        self.batch_diagnostic = {
            "mission_id": mission_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "started",
            "selected_rows": [row_diagnostic(row) for row in self.batch_rows if row.selected],
            "output_directory": str(self._batch_output_dir()),
            "studio_ui_config": {
                "profile_alias": self.voice.currentText(),
                "speed": self.speed.value(),
                "steps": self.steps.value(),
            },
            "validation": {"result": "pending", "rows": []},
            "job_build": {"result": "pending"},
            "job_write": {"result": "pending"},
            "launcher": {"result": "pending"},
            "error_stage": None,
            "error_type": None,
            "error_message": None,
        }
        self._persist_batch_diagnostic()

    def _persist_batch_diagnostic(self) -> None:
        if self.batch_diagnostic_path and self.batch_diagnostic is not None:
            self.batch_diagnostic["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_launch_diagnostic(self.batch_diagnostic_path, self.batch_diagnostic)

    def _fail_batch_launch(self, stage: str, exc: Exception) -> None:
        if self.batch_diagnostic is not None:
            self.batch_diagnostic.update({
                "status": "failed", "error_stage": stage,
                "error_type": type(exc).__name__, "error_message": str(exc),
            })
            self._persist_batch_diagnostic()
        message = f"CSV Batch {stage}: {exc}"
        self.batch_status.setText(message)
        QMessageBox.warning(self, "เริ่ม CSV Batch ไม่ได้", message)

    def _launch_batch_runner(self, job_path: Path) -> None:
        command = [sys.executable, str(ROOT / "tts_batch_runner.py"), "run", "--job", str(job_path)]
        self.batch_launcher = subprocess.Popen(
            command, cwd=str(ROOT), **batch_runner.background_process_kwargs(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )
        if self.batch_diagnostic is not None:
            self.batch_diagnostic["launcher"] = {
                "result": "launched", "command": command, "pid": self.batch_launcher.pid,
            }
            self.batch_diagnostic["status"] = "running"
            self._persist_batch_diagnostic()
        self.batch_timer.start()
        self.import_csv_button.setEnabled(False)
        self.generate_batch_button.setEnabled(False)
        self.resume_batch_button.setEnabled(False)
        self.stop_batch_button.setEnabled(True)
        self.batch_status.setText("กำลังเริ่ม CSV Batch...")

    def generate_csv_batch(self) -> None:
        if self._batch_is_running() or not self.batch_rows:
            return
        if (self.worker and self.worker.isRunning()) or (self.preview_worker and self.preview_worker.isRunning()):
            self.batch_status.setText("Studio กำลังสร้างเสียงรายการอื่นอยู่")
            return
        mission_id = new_mission_id(self.batch_rows)
        try:
            self._begin_batch_diagnostic(mission_id)
            self.validate_batch_rows()
            assert self.batch_diagnostic is not None
            self.batch_diagnostic["validation"] = {
                "result": "completed",
                "rows": [row_diagnostic(row) for row in self.batch_rows],
            }
            self._persist_batch_diagnostic()
            if not any(row.selected for row in self.batch_rows):
                stages = {row.error_stage for row in self.batch_rows if row.error_stage}
                stage = "VOICE_TARGET_RESOLUTION" if "VOICE_TARGET_RESOLUTION" in stages else "VALIDATION"
                raise CsvBatchError("ไม่มี row ที่ผ่าน validation และถูกเลือกสำหรับสร้างเสียง")
            job = build_job(
                self.batch_rows, self._batch_output_dir(), self.voice.currentText(),
                self.speed.value(), self.steps.value(), mission_id=mission_id,
                overwrite_selected=self.overwrite_batch.isChecked(),
            )
            self.batch_diagnostic["job_build"] = {
                "result": "completed",
                "resolved_generation_config": [
                    {"line_id": line["id"], "voice_project": line.get("voice_project", ""),
                     "voice_target": line.get("voice_target", ""),
                     "profile_alias": line["voice"], "generation_mode": line.get("generation_mode", "voice_design"),
                     "instruction_override": line.get("instruction_override"),
                     "speed": line["speed"], "steps": line["steps"], "seed": line["seed"],
                     "language": line.get("language"), "denoise": line.get("denoise"),
                     "postprocess_output": line.get("postprocess_output"),
                     "reference_conditioning": line.get("reference_conditioning", False),
                     "reference_audio": line.get("reference_audio"),
                     "reference_sha256": line.get("reference_sha256"),
                     "reference_prompt_preparation_status": "pending" if line.get("reference_conditioning") else "not_required",
                     "resolved_spoken_text": line.get("resolved_spoken_text")}
                    for line in job["lines"]
                ],
            }
            self._persist_batch_diagnostic()
            job_path = batch_runner._mission_paths(mission_id)["base"] / "studio_job.json"
            write_job(job_path, job)
            self.batch_diagnostic["job_write"] = {"result": "completed", "path": str(job_path)}
            self._persist_batch_diagnostic()
            self.batch_mission_id, self.batch_job_path = mission_id, job_path
            self.batch_progress.setRange(0, len(job["lines"]))
            self.batch_progress.setValue(0)
            self._launch_batch_runner(job_path)
        except Exception as exc:
            if isinstance(exc, VoiceTargetResolutionError):
                stage = "VOICE_TARGET_RESOLUTION"
            elif isinstance(exc, OSError):
                stage = "JOB_WRITE" if self.batch_job_path is None else "LAUNCH"
            elif self.batch_diagnostic and self.batch_diagnostic["job_build"]["result"] == "pending":
                stages = {row.error_stage for row in self.batch_rows if row.error_stage}
                if "VOICE_TARGET_RESOLUTION" in stages:
                    stage = "VOICE_TARGET_RESOLUTION"
                elif "VALIDATION" in stages:
                    stage = "VALIDATION"
                else:
                    stage = "JOB_BUILD"
            elif self.batch_diagnostic and self.batch_diagnostic["job_write"]["result"] == "pending":
                stage = "JOB_WRITE"
            else:
                stage = "LAUNCH"
            self._fail_batch_launch(stage, exc)

    def poll_batch_status(self) -> None:
        if not self.batch_mission_id:
            return
        try:
            state = batch_runner.mission_status(self.batch_mission_id)
        except Exception as exc:
            self.batch_status.setText(f"อ่าน batch status ไม่ได้: {exc}")
            return
        checkpoint = state.get("checkpoint") or {}
        if self.batch_diagnostic is not None and checkpoint:
            self.batch_diagnostic["reference_prompts"] = checkpoint.get("reference_prompts", {})
            self.batch_diagnostic["runner_runtime"] = checkpoint.get("runtime", {})
            self._persist_batch_diagnostic()
        line_states = checkpoint.get("lines") or {}
        terminal = {"completed": DONE, "failed": ERROR, "timeout": ERROR, "cancelled": ERROR, "skipped": SKIPPED}
        completed = 0
        timeout_rows = []
        failed_rows = []
        for row in self.batch_rows:
            line = line_states.get(f"csv-{row.csv_row_number:05d}")
            if not line:
                continue
            raw_status = line.get("status", "pending")
            if raw_status == "running":
                row.status, row.error = GENERATING, None
            elif raw_status in terminal:
                row.status = terminal[raw_status]
                error = line.get("error") or line.get("reason")
                if error and (line.get("error_type") or line.get("error_stage")):
                    details = ": ".join(filter(None, (line.get("error_stage"), line.get("error_type"))))
                    error = f"[{details}] {error}"
                row.error = error
            else:
                row.status, row.error = PENDING, None
            if row.status in {DONE, SKIPPED, ERROR}:
                if raw_status in {"completed", "skipped"}:
                    completed += 1
                elif raw_status == "timeout":
                    timeout_rows.append(row.csv_row_number)
                elif raw_status in {"failed", "cancelled"}:
                    failed_rows.append(row.csv_row_number)
        self.batch_progress.setValue(min(completed, self.batch_progress.maximum()))
        total = self.batch_progress.maximum()
        remaining = max(0, total - completed - len(timeout_rows) - len(failed_rows))
        if timeout_rows:
            self.batch_status.setText(
                f"CSV Batch: row {timeout_rows[0]} Timed out — Completed {completed} / {total}; "
                f"remaining {remaining}; Resume Batch ได้"
            )
        elif failed_rows:
            self.batch_status.setText(
                f"CSV Batch: row {failed_rows[0]} Failed — Completed {completed} / {total}; "
                f"remaining {remaining}; Resume Batch ได้"
            )
        else:
            self.batch_status.setText(f"CSV Batch: Generating/Completed {completed} / {total}")
        self.refresh_batch_table()
        launcher_finished = self.batch_launcher is not None and self.batch_launcher.poll() is not None
        if launcher_finished and not state.get("running"):
            process = self.batch_launcher
            exit_code = process.poll()
            stdout = stderr = ""
            try:
                stdout, stderr = process.communicate(timeout=0)
            except (subprocess.TimeoutExpired, OSError):
                pass
            if self.batch_diagnostic is not None:
                if exit_code == 0:
                    self.batch_diagnostic.update({"status": "completed", "error_stage": None,
                                                  "error_type": None, "error_message": None})
                else:
                    stage = "GENERATION" if checkpoint.get("status") in {"failed", "timeout", "cancelled"} else "RUNNER"
                    self.batch_diagnostic.update({
                        "status": "failed", "error_stage": stage, "error_type": "RunnerExit",
                        "error_message": (stderr or stdout or f"runner exited with code {exit_code}").strip(),
                    })
                self.batch_diagnostic["launcher"].update({
                    "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
                })
                self._persist_batch_diagnostic()
            self.batch_timer.stop()
            self.batch_launcher = None
            self.import_csv_button.setEnabled(True)
            self.generate_batch_button.setEnabled(True)
            self.stop_batch_button.setEnabled(False)
            self.resume_batch_button.setEnabled(bool(self.batch_job_path and self.batch_job_path.exists()))
            state_name = checkpoint.get("status", "unknown")
            if state_name == "timeout":
                timeout_ids = [row.csv_row_number for row in self.batch_rows if row.status == ERROR and row.error and "timeout" in row.error.lower()]
                self.batch_status.setText(
                    f"CSV Batch จบด้วยสถานะ: Timed out — row {timeout_ids[0] if timeout_ids else '?'}; "
                    f"Completed {sum(row.status in {DONE, SKIPPED} for row in self.batch_rows)} / {total}; Resume Batch ได้"
                )
            else:
                self.batch_status.setText(f"CSV Batch จบด้วยสถานะ: {state_name}")

    def stop_csv_batch(self) -> None:
        if not self.batch_mission_id:
            return
        try:
            state = batch_runner.mission_status(self.batch_mission_id)
            parent_pid = (state.get("lock") or {}).get("parent_pid")
            if parent_pid == os.getpid():
                raise RuntimeError("ปฏิเสธการ stop: runner ไม่ได้เป็น external process")
            batch_runner.cancel_mission(self.batch_mission_id)
            self.batch_status.setText("สั่งหยุด CSV Batch แล้ว; checkpoint จะเก็บ row ที่เสร็จแล้ว")
        except Exception as exc:
            self.batch_status.setText(f"หยุด CSV Batch ไม่ได้: {exc}")

    def resume_csv_batch(self) -> None:
        if self._batch_is_running() or not self.batch_job_path or not self.batch_job_path.exists():
            return
        try:
            self._launch_batch_runner(self.batch_job_path)
        except OSError as exc:
            self.batch_status.setText(f"resume runner ไม่ได้: {exc}")

    def open_batch_output_directory(self) -> None:
        directory = self._batch_output_dir()
        if not directory.exists():
            self.batch_status.setText("ยังไม่มี output directory")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _restore_settings(self) -> None:
        self.resize(self.settings.value("window_size", self.size()))
        alias = self.settings.value("voice", "narrator"); self.voice.setCurrentText(alias if alias in self.aliases else "narrator")
        self.speed.setValue(float(self.settings.value("speed", self.speed.value())))
        directory = self.settings.value("output_dir", "")
        if directory:
            saved_dir = Path(directory)
            parts = list(saved_dir.parts)
            try:
                old_root_index = parts.index("omnivoice-thai-poc")
            except ValueError:
                pass
            else:
                relative_parts = parts[old_root_index + 1:]
                saved_dir = ROOT.joinpath(*relative_parts)
                self.settings.setValue("output_dir", str(saved_dir))
            self.output.setText(str(saved_dir / default_output_path().name))

    def _voice_changed(self, alias: str) -> None:
        item = self.aliases[alias]; self.description.setText(item["description_th"])
        voice = _voice_profile_light(alias); self.speed.setValue(float(voice["speed"]))

    def _update_count(self) -> None: self.count_label.setText(f"{len(self.editor.toPlainText())} ตัวอักษร")
    def _text(self) -> str:
        text = self.editor.toPlainText().strip()
        if not text: raise TtsInputError("กรุณากรอกข้อความก่อน")
        return text
    def check_text(self) -> bool:
        try:
            text = self._text()
            result = (preview_text(text, self.voice.currentText()) if is_long(text)
                      else preview_single_input_text(text, self.voice.currentText()))
            prepared = result["prepared"]; gate = prepared["gate"]
            details = f"ต้นฉบับ: {prepared['original']}\n\nหลัง normalization: {prepared['normalized']}\n\nข้อความที่จะพูด: {prepared['spoken']}\n\nPronunciation substitutions: {prepared['substitutions']}\n\nThai-only gate: {'ผ่าน' if gate.thai_only_gate_passed else 'ไม่ผ่าน'}"
            self.preview.setPlainText(details)
            if not gate.thai_only_gate_passed: self.status.setText("พบตัวอักษรอังกฤษหรือเลขที่ยังไม่ได้ normalize"); self.generate_button.setEnabled(False); return False
            self.generate_button.setEnabled(True); self.status.setText("ข้อความผ่าน Thai-only gate"); return True
        except Exception as exc: self.preview.setPlainText(str(exc)); self.status.setText("ตรวจข้อความไม่ผ่าน"); self.generate_button.setEnabled(False); return False
    def _request_engine(self, action: Callable[[Any], None]) -> None:
        """Run one engine action after background initialization, if needed."""
        if self.engine_state == ENGINE_READY and self.adapter is not None:
            action(self.adapter)
            return
        if self.engine_state == ENGINE_LOADING:
            self._pending_engine_action = action
            self.status.setText("Engine: Loading...")
            return
        self.engine_state = ENGINE_LOADING
        self.engine_error = None
        self._pending_engine_action = action
        self.model_label.setText("Engine: Loading...")
        self.status.setText("Engine: Loading...")
        self.generate_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.engine_worker = EngineInitWorker(self)
        self.engine_worker.progress.connect(self.status.setText)
        self.engine_worker.ready.connect(self._engine_ready)
        self.engine_worker.failed.connect(self._engine_failed)
        self.engine_worker.start()

    def _engine_ready(self, adapter: Any) -> None:
        self.adapter = adapter
        self.engine_state = ENGINE_READY
        self.engine_error = None
        self.model_label.setText("Engine: Ready")
        self.generate_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.engine_worker = None
        action = self._pending_engine_action
        self._pending_engine_action = None
        if action is not None:
            action(adapter)

    def _engine_failed(self, message: str) -> None:
        self.engine_state = ENGINE_FAILED
        self.engine_error = message
        self.engine_worker = None
        self._pending_engine_action = None
        self.adapter = None
        self.model_label.setText("Engine: Failed")
        self.generate_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.status.setText(f"Engine initialization failed: {message}")

    def _start_generation(self, adapter: Any, text: str, output: Path, force: bool) -> None:
        self.status.setText("กำลังตรวจ Cache...")
        self.generate_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.worker = GenerateWorker(adapter, text, self.voice.currentText(), self.speed.value(), self.steps.value(), output, force)
        self.worker.finished_result.connect(self.generated)
        self.worker.failed.connect(self.failed)
        self.worker.progress.connect(self.batch_progress)
        self.worker.start()

    def _start_preview(self, adapter: Any, text: str, output: Path) -> None:
        self.preview_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.preview_worker = QuickPreviewWorker(adapter, text, self.voice.currentText(), self.speed.value(), self.steps.value(), output)
        self.preview_worker.finished_result.connect(self.preview_generated)
        self.preview_worker.failed.connect(self.preview_failed)
        self.preview_worker.start()

    def choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "เลือกไฟล์ WAV", self.output.text(), "WAV (*.wav)")
        if path: self.output.setText(path)
    def open_text(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "เปิดไฟล์ TXT", "", "Text (*.txt)")
        if path:
            try: self.editor.setPlainText(Path(path).read_text(encoding="utf-8")); self.status.setText("เปิดไฟล์ข้อความแล้ว")
            except Exception as exc: QMessageBox.warning(self, "เปิดไฟล์ไม่ได้", str(exc))
    def save_text(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "บันทึกข้อความ", "", "Text (*.txt)")
        if path:
            try: Path(path).write_text(self.editor.toPlainText(), encoding="utf-8"); self.status.setText("บันทึกข้อความแล้ว")
            except Exception as exc: QMessageBox.warning(self, "บันทึกไม่ได้", str(exc))
    def generate(self) -> None:
        if self._batch_is_running():
            self.status.setText("CSV Batch กำลังทำงานอยู่")
            return
        if self.preview_worker and self.preview_worker.isRunning():
            return
        try:
            text = self._text()
        except TtsInputError as exc:
            self.status.setText(str(exc))
            return
        output = Path(self.output.text())
        force = self.force.isChecked()
        self.generate_button.setEnabled(False); self.preview_button.setEnabled(False); self.progress.setRange(0, 0); self.status.setText("กำลังตรวจ Cache...")
        self._request_engine(lambda adapter: self._start_generation(adapter, text, output, force))
    def batch_progress(self,current,total,status):
        self.progress.setRange(0,total); self.progress.setValue(current); self.status.setText(("ใช้ Cache" if status=="CACHED" else "กำลังสร้าง")+f" {current} / {total}")
    def generated(self, result: dict) -> None:
        if result.get("cancelled"):
            self.progress.setRange(0, 1); self.progress.setValue(0); self.generate_button.setEnabled(True); self.preview_button.setEnabled(True); self.play_button.setEnabled(False); self.status.setText("ยกเลิกแล้ว — เก็บ chunk ที่สร้างสำเร็จไว้แล้ว"); self.worker = None; return
        self.progress.setRange(0, 1); self.progress.setValue(1); self.generate_button.setEnabled(True); self.preview_button.setEnabled(True); self.output.setText(str(result["output"])); self.model_label.setText("Engine: Ready" if self.engine_state == ENGINE_READY else "Engine: Not loaded"); self.status.setText("ใช้ไฟล์จาก Cache" if result["cache_hit"] else f"สร้างเสียงสำเร็จ — {result.get('total_generation_seconds', 0):.1f} วินาที"); self.play_button.setEnabled(True); self.stop_button.setEnabled(True); self.worker = None
    def failed(self, message: str) -> None:
        self.progress.setRange(0, 1); self.progress.setValue(0); self.generate_button.setEnabled(True); self.preview_button.setEnabled(True); self.worker = None; self.status.setText("ไม่สามารถสร้างไฟล์ WAV ได้"); QMessageBox.warning(self, "สร้างเสียงไม่สำเร็จ", message)
    def quick_preview(self) -> None:
        if self._batch_is_running():
            self.status.setText("CSV Batch กำลังทำงานอยู่")
            return
        if (self.worker and self.worker.isRunning()) or (self.preview_worker and self.preview_worker.isRunning()):
            return
        try:
            text = select_preview_text(self._text())
        except (PreviewTextError, TtsInputError) as exc:
            self.status.setText(str(exc)); return
        output = preview_output_path(text, self.voice.currentText(), self.speed.value(), self.steps.value())
        self._request_engine(lambda adapter: self._start_preview(adapter, text, output))
        self.preview_button.setEnabled(False); self.generate_button.setEnabled(False); self.status.setText("กำลังสร้างเสียงตัวอย่าง...")
        # The worker is created by _start_preview after the engine is ready.
    def preview_generated(self, result: dict) -> None:
        self.preview_worker = None; self.preview_button.setEnabled(True); self.generate_button.setEnabled(True)
        self.model_label.setText("Engine: Ready" if self.engine_state == ENGINE_READY else "Engine: Not loaded")
        self.player.setSource(QUrl.fromLocalFile(str(Path(result["output"]).resolve()))); self.player.play(); self.stop_button.setEnabled(True)
        self.status.setText("เสียงตัวอย่างจาก Cache — เล่นแล้ว" if result["cache_hit"] else "เสียงตัวอย่างพร้อม — เล่นแล้ว")
    def preview_failed(self, message: str) -> None:
        self.preview_worker = None; self.preview_button.setEnabled(True); self.generate_button.setEnabled(True); self.status.setText("ไม่สามารถสร้างเสียงตัวอย่างได้"); QMessageBox.warning(self, "ทดลองเสียงไม่สำเร็จ", message)
    def play(self) -> None: self.player.setSource(QUrl.fromLocalFile(self.output.text())); self.player.play()
    def stop_action(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText("กำลังยกเลิกหลังจบ chunk ปัจจุบัน...")
        else:
            self.player.stop()

    def closeEvent(self, event) -> None:
        self.settings.setValue("voice", self.voice.currentText()); self.settings.setValue("speed", self.speed.value()); self.settings.setValue("output_dir", str(Path(self.output.text()).parent)); self.settings.setValue("window_size", self.size()); super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv); window = StudioWindow(); window.show(); return app.exec()

if __name__ == "__main__": raise SystemExit(main())
