"""
Batch processing queue dialog for multiple folders/files with Pause/Cancel controls.
Addresses upstream issue #1020: https://github.com/dmMaze/BallonsTranslator/issues/1020
"""
import os
import os.path as osp
from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QGroupBox, QCheckBox, QListView
)
from qtpy.QtCore import Signal, Qt
from .custom_widget.hover_animation import install_button_animations

def _collect_dirs(parent_path: str, include_subfolders: bool) -> list:
    """Возвращает parent_path и, если include_subfolders=True, ВСЕ вложенные подпапки (рекурсивно)."""
    out = []
    if not osp.isdir(parent_path):
        return out
    
    out.append(osp.normpath(osp.abspath(parent_path)))
    
    if include_subfolders:
        try:
            # os.walk рекурсивно обходит все вложенные папки на любой глубине
            for root, dirs, files in os.walk(parent_path):
                for d in dirs:
                    sub = osp.join(root, d)
                    norm_sub = osp.normpath(osp.abspath(sub))
                    if norm_sub not in out:
                        out.append(norm_sub)
        except OSError:
            pass
    return out

class BatchQueueDialog(QDialog):
    start_queue_requested = Signal(list, bool)
    pause_requested = Signal()
    resume_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Batch processing queue"))
        self.setMinimumSize(480, 360)
        layout = QVBoxLayout(self)

        group = QGroupBox(self.tr("Queue"))
        group_layout = QVBoxLayout(group)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        group_layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        add_btn = QPushButton(self.tr("Add folder(s)..."))
        add_btn.clicked.connect(self._on_add_folders)
        add_btn.setToolTip(self.tr("Select one or more folders to add to the queue."))
        
        add_sub_btn = QPushButton(self.tr("Add folder (include subfolders)"))
        add_sub_btn.clicked.connect(self._on_add_folder_with_subfolders)
        add_sub_btn.setToolTip(self.tr("Select one folder; add it and all its subfolders as separate queue items."))
        
        remove_btn = QPushButton(self.tr("Remove selected"))
        remove_btn.clicked.connect(self._on_remove_selected)
        
        clear_btn = QPushButton(self.tr("Clear all"))
        clear_btn.clicked.connect(self._on_clear)

        btn_row.addWidget(add_btn)
        btn_row.addWidget(add_sub_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        group_layout.addLayout(btn_row)
        layout.addWidget(group)

        self.skip_ignored_checker = QCheckBox(self.tr("Skip ignored pages"))
        self.skip_ignored_checker.setChecked(True)
        layout.addWidget(self.skip_ignored_checker)

        self.status_label = QLabel(self.tr("Queue: 0 items. Add folders and click Start."))
        self.status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.status_label)

        control_row = QHBoxLayout()
        self.start_btn = QPushButton(self.tr("Start queue"))
        self.start_btn.clicked.connect(self._on_start)
        self.pause_btn = QPushButton(self.tr("Pause"))
        self.pause_btn.clicked.connect(self._on_pause)
        self.pause_btn.setEnabled(False)
        self.resume_btn = QPushButton(self.tr("Resume"))
        self.resume_btn.clicked.connect(self._on_resume)
        self.resume_btn.setEnabled(False)
        self.cancel_btn = QPushButton(self.tr("Cancel queue"))
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit())
        self.cancel_btn.setEnabled(False)

        control_row.addWidget(self.start_btn)
        control_row.addWidget(self.pause_btn)
        control_row.addWidget(self.resume_btn)
        control_row.addWidget(self.cancel_btn)
        control_row.addStretch()
        layout.addLayout(control_row)

        for btn in (self.start_btn, self.pause_btn, self.resume_btn, self.cancel_btn, add_btn, add_sub_btn, remove_btn, clear_btn):
            install_button_animations(btn, normal_opacity=0.9, press_opacity=0.74)

        close_btn = QPushButton(self.tr("Close"))
        close_btn.clicked.connect(self.accept)
        install_button_animations(close_btn, normal_opacity=0.9, press_opacity=0.74)
        layout.addWidget(close_btn)

        self._update_buttons()

    def _paths_from_list(self) -> list:
        paths = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.text():
                p = item.text().strip()
                if p and p not in paths:
                    paths.append(p)
        return paths

    def _on_add_folders(self):
        """Открытие диалога для выбора НЕСКОЛЬКИХ папок (исправлено для Qt6)."""
        dialog = QFileDialog(self)
        dialog.setWindowTitle(self.tr("Select folders to add"))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        
        # В Qt6 внутренний список файлов — это QListView, а не QListWidget!
        list_view = dialog.findChild(QListView)
        if list_view:
            list_view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        selected_dirs = dialog.selectedFiles()
        if not selected_dirs:
            return
        
        existing_paths = set(self._paths_from_list())
        added_count = 0
        for d in selected_dirs:
            norm_d = osp.normpath(osp.abspath(d))
            if osp.isdir(norm_d) and norm_d not in existing_paths:
                self.list_widget.addItem(norm_d)
                existing_paths.add(norm_d)
                added_count += 1
        
        if added_count > 0:
            self._update_buttons()

    def _on_add_folder_with_subfolders(self):
        parent = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select folder (it and its subfolders will be added)"),
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not parent:
            return
        
        existing = set(self._paths_from_list())
        added_count = 0
        for p in _collect_dirs(parent, include_subfolders=True):
            if p not in existing:
                self.list_widget.addItem(p)
                existing.add(p)
                added_count += 1
        
        if added_count > 0:
            self._update_buttons()

    def _on_remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))
        self._update_buttons()

    def _on_clear(self):
        self.list_widget.clear()
        self._update_buttons()

    def _on_start(self):
        paths = self._paths_from_list()
        if not paths:
            QMessageBox.information(self, self.tr("Batch queue"), self.tr("Add at least one folder to the queue."))
            return
        self.start_queue_requested.emit(paths, self.skip_ignored_checker.isChecked())
        self._set_running(True)

    def _on_pause(self):
        self.pause_requested.emit()
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(True)
        self.status_label.setText(self.tr("Paused. Click Resume to continue."))

    def _on_resume(self):
        self.resume_requested.emit()
        self.resume_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.status_label.setText(self.tr("Running…"))

    def _update_buttons(self):
        n = self.list_widget.count()
        self.start_btn.setEnabled(n > 0)
        self.status_label.setText(self.tr("Queue: {} item(s). Add folders and click Start.").format(n))

    def _set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        self.resume_btn.setEnabled(False)
        self.cancel_btn.setEnabled(running)
        self.list_widget.setEnabled(not running)
        if running:
            self.status_label.setText(self.tr("Running… Use Pause / Cancel queue as needed."))
        else:
            self._update_buttons()

    def set_running_state(self, running: bool, paused: bool = False, current_path: str = ""):
        if not running:
            self._set_running(False)
            if self.list_widget.count() == 0:
                self.status_label.setText(self.tr("Queue empty. Add folders and click Start."))
            return
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(not paused)
        self.resume_btn.setEnabled(paused)
        self.cancel_btn.setEnabled(True)
        self.list_widget.setEnabled(False)
        if current_path:
            self.status_label.setText(self.tr("Running: {}").format(osp.basename(current_path)))
        else:
            self.status_label.setText(self.tr("Running…"))

    def set_queue_empty(self):
        self._set_running(False)
        self.status_label.setText(self.tr("Queue finished. Add more folders or close."))

    def set_queue_cancelled(self):
        self._set_running(False)
        self.status_label.setText(self.tr("Queue cancelled."))