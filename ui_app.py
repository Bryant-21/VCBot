import sys
import logging
import shutil
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


class MainWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VC Bot Template Generator")
        self.resize(520, 220)

        self.date_input = QtWidgets.QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(QtCore.QDate.currentDate())

        self.game_combo = QtWidgets.QComboBox()
        self.game_combo.addItems(["FALLOUT4", "SKYRIM", "STARFIELD"])

        self.template_combo = QtWidgets.QComboBox()
        self.template_combo.addItems(["reddit", "discord", "wiki"])

        self.log_level_combo = QtWidgets.QComboBox()
        self.log_level_combo.addItems(["INFO", "DEBUG"])

        self.output_input = QtWidgets.QLineEdit()
        self.output_input.setText(str(Path.cwd() / "out"))
        self.output_button = QtWidgets.QPushButton("Browse")
        self.output_button.clicked.connect(self._browse_output)

        self.generate_button = QtWidgets.QPushButton("Generate")
        self.generate_button.clicked.connect(self._generate)

        form = QtWidgets.QFormLayout()
        form.addRow("Cutoff date", self.date_input)
        form.addRow("Game", self.game_combo)
        form.addRow("Template", self.template_combo)
        form.addRow("Log level", self.log_level_combo)

        output_layout = QtWidgets.QHBoxLayout()
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(self.output_button)
        form.addRow("Output folder", output_layout)

        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(form)
        main_layout.addWidget(self.generate_button)
        self.setLayout(main_layout)

    def _browse_output(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.output_input.setText(path)

    def _generate(self) -> None:
        level = logging.DEBUG if self.log_level_combo.currentText() == "DEBUG" else logging.INFO
        logging.getLogger().setLevel(level)
        date_text = self.date_input.date().toString("yyyy-MM-dd")
        date_text = f"{date_text}T00:00:00+00:00"
        config = load_config()
        config = config.__class__(
            **{**config.__dict__, "product": self.game_combo.currentText()}
        )
        try:
            generate_template_files(
                config,
                output_dir=self.output_input.text().strip(),
                template_kind=self.template_combo.currentText(),
                cutoff_date=date_text,
            )
            QtWidgets.QMessageBox.information(self, "Done", "Templates generated.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error", str(exc))


def main() -> None:
    _configure_logging(logging.INFO)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
