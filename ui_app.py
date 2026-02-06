import sys
import logging
import shutil
import json
from pathlib import Path
from PySide6 import QtCore, QtWidgets

from vcbot.app import generate_template_files
from vcbot.config import load_config


def _rotate_logs(log_path: Path, max_backups: int) -> None:
    if not log_path.exists():
        return
    last_backup = log_path.with_suffix(log_path.suffix + f".{max_backups}")
    if last_backup.exists():
        last_backup.unlink()
    for i in range(max_backups - 1, 0, -1):
        src = log_path.with_suffix(log_path.suffix + f".{i}")
        dst = log_path.with_suffix(log_path.suffix + f".{i + 1}")
        if src.exists():
            shutil.move(str(src), str(dst))
    shutil.move(str(log_path), str(log_path.with_suffix(log_path.suffix + ".1")))


def _configure_logging(level: int) -> None:
    log_path = Path("logs/vcbot.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_logs(log_path, max_backups=10)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[handler],
    )


class Worker(QtCore.QObject):
    finished = QtCore.Signal(int, list)
    error = QtCore.Signal(str)

    def __init__(self, config, output_dir, templates, date_text):
        super().__init__()
        self.config = config
        self.output_dir = output_dir
        self.templates = templates
        self.date_text = date_text

    def run(self):
        try:
            total_found = 0
            for template_kind in self.templates:
                count = generate_template_files(
                    self.config,
                    output_dir=self.output_dir,
                    template_kind=template_kind,
                    cutoff_date=self.date_text,
                )
                total_found = count
            self.finished.emit(total_found, self.templates)
        except Exception as exc:
            self.error.emit(str(exc))


class MainWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VC Bot Template Generator")
        self.resize(520, 220)

        self.date_input = QtWidgets.QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(QtCore.QDate.currentDate())
        self.date_input.setMaximumDate(QtCore.QDate.currentDate())

        self.game_combo = QtWidgets.QComboBox()
        self.game_combo.addItems(["FALLOUT4", "SKYRIM", "STARFIELD"])

        self.wiki_check = QtWidgets.QCheckBox("Wiki")
        self.wiki_check.setChecked(True)
        self.reddit_check = QtWidgets.QCheckBox("Reddit")
        self.reddit_check.setChecked(True)
        self.discord_check = QtWidgets.QCheckBox("Discord")
        self.discord_check.setChecked(True)

        self.log_level_combo = QtWidgets.QComboBox()
        self.log_level_combo.addItems(["INFO", "DEBUG"])

        self.output_input = QtWidgets.QLineEdit()
        self.output_input.setText(str(Path.cwd() / "out"))
        self.output_button = QtWidgets.QPushButton("Browse")
        self.output_button.clicked.connect(self._browse_output)

        self.generate_button = QtWidgets.QPushButton("Generate")
        self.generate_button.clicked.connect(self._generate)

        self.help_button = QtWidgets.QPushButton("Help")
        self.help_button.clicked.connect(self._show_help)

        form = QtWidgets.QFormLayout()
        form.addRow("Cutoff date", self.date_input)
        form.addRow("Game", self.game_combo)

        template_layout = QtWidgets.QHBoxLayout()
        template_layout.addWidget(self.wiki_check)
        template_layout.addWidget(self.reddit_check)
        template_layout.addWidget(self.discord_check)
        form.addRow("Templates", template_layout)

        form.addRow("Log level", self.log_level_combo)

        output_layout = QtWidgets.QHBoxLayout()
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(self.output_button)
        form.addRow("Output folder", output_layout)

        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(form)
        
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.help_button)
        
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

        self._load_ui_config()
        self.worker_thread = None

    def _load_ui_config(self) -> None:
        config_path = Path("config.json")
        if not config_path.exists():
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            date_str = data.get("cutoff_date")
            if date_str:
                self.date_input.setDate(QtCore.QDate.fromString(date_str, QtCore.Qt.ISODate))
            
            game = data.get("game")
            if game:
                index = self.game_combo.findText(game)
                if index >= 0:
                    self.game_combo.setCurrentIndex(index)
            
            self.wiki_check.setChecked(data.get("wiki", True))
            self.reddit_check.setChecked(data.get("reddit", True))
            self.discord_check.setChecked(data.get("discord", True))
            
            log_level = data.get("log_level")
            if log_level:
                index = self.log_level_combo.findText(log_level)
                if index >= 0:
                    self.log_level_combo.setCurrentIndex(index)
            
            output_folder = data.get("output_folder")
            if output_folder:
                self.output_input.setText(output_folder)
        except Exception as exc:
            logging.error("Failed to load UI config: %s", exc)

    def _save_ui_config(self) -> None:
        data = {
            "cutoff_date": self.date_input.date().toString(QtCore.Qt.ISODate),
            "game": self.game_combo.currentText(),
            "wiki": self.wiki_check.isChecked(),
            "reddit": self.reddit_check.isChecked(),
            "discord": self.discord_check.isChecked(),
            "log_level": self.log_level_combo.currentText(),
            "output_folder": self.output_input.text(),
        }
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as exc:
            logging.error("Failed to save UI config: %s", exc)

    def _browse_output(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.output_input.setText(path)

    def _show_help(self) -> None:
        help_text = (
            "This application checks the Bethesda mod contents API for mods published "
            "between the current time (NOW) and your selected cutoff date.\n\n"
            "Key Points:\n"
            "• UTC Time: The API operates on UTC time. Depending on your timezone, "
            "you may need to select a date one day earlier than expected to capture all recent mods.\n"
            "• Templates: Select which platforms (Wiki, Reddit, Discord) you want to generate "
            "templates for. Each selection will create specialized post files.\n"
            "• Output: Generated templates are automatically saved into subfolders "
            "within your chosen 'Output folder'.\n"
            "• Persistent Settings: Your selections are saved to 'config.json' and "
            "reloaded next time you start the app."
        )
        QtWidgets.QMessageBox.information(self, "How to use VC Bot", help_text)

    def _generate(self) -> None:
        level = logging.DEBUG if self.log_level_combo.currentText() == "DEBUG" else logging.INFO
        logging.getLogger().setLevel(level)
        
        self._save_ui_config()

        date_text = self.date_input.date().toString("yyyy-MM-dd")
        date_text = f"{date_text}T00:00:00+00:00"
        
        templates = []
        if self.wiki_check.isChecked():
            templates.append("wiki")
        if self.reddit_check.isChecked():
            templates.append("reddit")
        if self.discord_check.isChecked():
            templates.append("discord")
        
        if not templates:
            QtWidgets.QMessageBox.warning(self, "Warning", "Please select at least one template.")
            return

        config = load_config()
        config = config.__class__(
            **{**config.__dict__, "product": self.game_combo.currentText()}
        )

        self.progress = QtWidgets.QProgressDialog("Generating templates...", None, 0, 0, self)
        self.progress.setWindowTitle("Please wait")
        self.progress.setWindowModality(QtCore.Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.show()

        self.generate_button.setEnabled(False)

        self.worker_thread = QtCore.QThread()
        self.worker = Worker(
            config,
            output_dir=self.output_input.text().strip(),
            templates=templates,
            date_text=date_text
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_generate_finished)
        self.worker.error.connect(self._on_generate_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.worker_thread.quit)
        self.worker.error.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    def _on_generate_finished(self, total_found, templates):
        self.progress.close()
        self.generate_button.setEnabled(True)
        msg = f"Templates generated for: {', '.join(templates)}\n\nFound {total_found} mods."
        QtWidgets.QMessageBox.information(self, "Done", msg)

    def _on_generate_error(self, error_msg):
        self.progress.close()
        self.generate_button.setEnabled(True)
        QtWidgets.QMessageBox.critical(self, "Error", error_msg)


def main() -> None:
    _configure_logging(logging.INFO)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
