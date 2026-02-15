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
    finished = QtCore.Signal(int, list, list)
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
            reddit_posts = []
            for template_kind in self.templates:
                count, posts = generate_template_files(
                    self.config,
                    output_dir=self.output_dir,
                    template_kind=template_kind,
                    cutoff_date=self.date_text,
                )
                total_found += count
                if template_kind.lower() == "reddit":
                    # Sort reddit posts by date (index 3 is pub_date)
                    reddit_posts = sorted(posts, key=lambda x: x[3])
                    logging.info("Collected and sorted %d reddit posts (oldest first)", len(reddit_posts))
            self.finished.emit(total_found, self.templates, reddit_posts)
        except Exception as exc:
            logging.exception("Error in Worker.run")
            self.error.emit(str(exc))


class PostWorker(QtCore.QObject):
    finished = QtCore.Signal(int, list)
    error = QtCore.Signal(str)
    progress = QtCore.Signal(str)

    def __init__(self, config, reddit_posts):
        super().__init__()
        self.config = config
        self.reddit_posts = reddit_posts

    def run(self):
        try:
            from vcbot.db import SQLiteStore
            from vcbot.reddit_client import RedditClient
            
            store = SQLiteStore(self.config.database_path)
            reddit = None
            try:
                reddit_refresh_token = store.get_meta("reddit_refresh_token")
                reddit = RedditClient(
                    client_id=self.config.reddit_client_id,
                    client_secret=self.config.reddit_client_secret,
                    username=self.config.reddit_username,
                    password=self.config.reddit_password,
                    user_agent=self.config.reddit_user_agent,
                    subreddit=self.config.reddit_subreddit,
                    refresh_token=reddit_refresh_token,
                    session_cookies=self.config.reddit_session_cookies,
                    csrf_token=self.config.reddit_csrf_token,
                )
            finally:
                store.close()

            if not reddit:
                raise Exception("Failed to initialize Reddit client")

            results = []
            success_count = 0
            for title, body, image_paths, _, flair_id in self.reddit_posts:
                try:
                    self.progress.emit(f"Posting: {title}")
                    # Convert string paths back to Path objects
                    image_path_objs = [Path(p) for p in image_paths] if image_paths else None
                    post_id, post_url = reddit.submit_post(title, body, flair_id=flair_id, image_paths=image_path_objs)
                    results.append((title, post_url))
                    success_count += 1
                except Exception as e:
                    logging.error(f"Failed to post '{title}': {e}")
                    results.append((title, f"Error: {e}"))
            
            self.finished.emit(success_count, results)
        except Exception as exc:
            logging.exception("Error in PostWorker.run")
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

        self.reddit_button = QtWidgets.QPushButton("Post to Reddit")
        self.reddit_button.setEnabled(False)
        self.reddit_button.clicked.connect(self._post_to_reddit)

        self.post_single_button = QtWidgets.QPushButton("Post Single")
        self.post_single_button.setEnabled(False)
        self.post_single_button.clicked.connect(self._post_single)

        self.dry_run_button = QtWidgets.QPushButton("Dry Run Post")
        self.dry_run_button.setEnabled(False)
        self.dry_run_button.clicked.connect(self._dry_run_post)

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
        button_layout.addWidget(self.reddit_button)
        button_layout.addWidget(self.post_single_button)
        button_layout.addWidget(self.dry_run_button)
        button_layout.addWidget(self.help_button)
        
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

        self._load_ui_config()
        self.worker_thread = None
        self.reddit_posts = []

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
        self.reddit_button.setEnabled(False)
        self.reddit_posts = []

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

    def _on_generate_finished(self, total_found, templates, reddit_posts):
        self.progress.close()
        self.generate_button.setEnabled(True)
        self.reddit_posts = reddit_posts
        if self.reddit_posts:
            self.reddit_button.setEnabled(True)
            self.post_single_button.setEnabled(True)
            self.dry_run_button.setEnabled(True)

        msg = f"Templates generated for: {', '.join(templates)}\n\nFound {total_found} mods."
        if self.reddit_posts:
            msg += f"\n\n{len(self.reddit_posts)} posts ready for Reddit."
        QtWidgets.QMessageBox.information(self, "Done", msg)

    def _on_generate_error(self, error_msg):
        self.progress.close()
        self.generate_button.setEnabled(True)
        QtWidgets.QMessageBox.critical(self, "Error", error_msg)

    def _post_to_reddit(self):
        if not self.reddit_posts:
            return
        
        confirm = QtWidgets.QMessageBox.question(
            self, "Confirm", 
            f"Are you sure you want to post {len(self.reddit_posts)} templates to Reddit?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        self._start_post_worker(self.reddit_posts)

    def _post_single(self):
        if not self.reddit_posts:
            return
        
        confirm = QtWidgets.QMessageBox.question(
            self, "Confirm", 
            "Are you sure you want to post the first template to Reddit for testing?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        self._start_post_worker([self.reddit_posts[0]])

    def _start_post_worker(self, posts_to_submit):
        config = load_config()
        
        self.post_progress = QtWidgets.QProgressDialog("Posting to Reddit...", "Cancel", 0, len(posts_to_submit), self)
        self.post_progress.setWindowTitle("Posting")
        self.post_progress.setWindowModality(QtCore.Qt.WindowModal)
        self.post_progress.show()

        self.generate_button.setEnabled(False)
        self.reddit_button.setEnabled(False)
        self.post_single_button.setEnabled(False)
        self.dry_run_button.setEnabled(False)

        self.post_thread = QtCore.QThread()
        self.post_worker = PostWorker(config, posts_to_submit)
        self.post_worker.moveToThread(self.post_thread)

        self.post_thread.started.connect(self.post_worker.run)
        self.post_worker.progress.connect(self._on_post_progress)
        self.post_worker.finished.connect(self._on_post_finished)
        self.post_worker.error.connect(self._on_post_error)
        
        self.post_worker.finished.connect(self.post_thread.quit)
        self.post_worker.finished.connect(self.post_worker.deleteLater)
        self.post_worker.error.connect(self.post_thread.quit)
        self.post_worker.error.connect(self.post_worker.deleteLater)
        self.post_thread.finished.connect(self.post_thread.deleteLater)

        self.post_thread.start()

    def _dry_run_post(self):
        if not self.reddit_posts:
            return
        
        title, body, image_paths, _, flair_id = self.reddit_posts[0]
        
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Dry Run - Reddit Post Preview")
        dialog.resize(600, 500)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        layout.addWidget(QtWidgets.QLabel(f"<b>Title:</b> (Flair: {flair_id or 'None'})"))
        title_edit = QtWidgets.QLineEdit(title)
        title_edit.setReadOnly(True)
        layout.addWidget(title_edit)
        
        if image_paths:
            layout.addWidget(QtWidgets.QLabel(f"<b>Images to upload ({len(image_paths)}):</b>"))
            images_list = QtWidgets.QListWidget()
            for p in image_paths:
                images_list.addItem(p)
            layout.addWidget(images_list)

        layout.addWidget(QtWidgets.QLabel("<b>Body:</b>"))
        body_edit = QtWidgets.QPlainTextEdit(body)
        body_edit.setReadOnly(True)
        layout.addWidget(body_edit)
        
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        
        dialog.exec()

    def _on_post_progress(self, message):
        self.post_progress.setLabelText(message)
        self.post_progress.setValue(self.post_progress.value() + 1)

    def _on_post_finished(self, success_count, results):
        self.post_progress.close()
        self.generate_button.setEnabled(True)
        self.reddit_button.setEnabled(True)
        self.post_single_button.setEnabled(True)
        self.dry_run_button.setEnabled(True)
        
        result_text = "\n".join([f"• {title}: {url}" for title, url in results])
        msg = f"Posted {success_count} of {len(self.reddit_posts)} successfully.\n\n{result_text}"
        QtWidgets.QMessageBox.information(self, "Reddit Results", msg)
        self.reddit_posts = [] # Clear after posting

    def _on_post_error(self, error_msg):
        self.post_progress.close()
        self.generate_button.setEnabled(True)
        self.reddit_button.setEnabled(True)
        self.post_single_button.setEnabled(True)
        self.dry_run_button.setEnabled(True)
        QtWidgets.QMessageBox.critical(self, "Error", error_msg)


def main() -> None:
    _configure_logging(logging.INFO)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
