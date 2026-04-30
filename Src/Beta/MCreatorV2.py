import ctypes
import winreg
import math
import ast
import operator as op
import codecs
from collections import defaultdict, OrderedDict
import sys
import re
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
	QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
	QPushButton, QLineEdit, QComboBox, QLabel, QGraphicsView,
	QGraphicsScene, QGraphicsPixmapItem, QGraphicsItem, QListWidget,
	QListWidgetItem, QAbstractItemView, QSlider, QTabWidget, QFileDialog, QMessageBox, QDialog, QTextEdit, QScrollArea,
	QFrame, QSplitter, QSizePolicy, QTableWidget, QTableWidgetItem, QSizeGrip, QColorDialog, QScrollBar, QTreeWidget,
	QTreeWidgetItem, QMenu, QInputDialog, QCheckBox, QSpinBox, QStyleFactory, QFormLayout, QHeaderView, QGroupBox,
	QStyledItemDelegate, QProgressBar
)
from PySide6.QtGui import QPixmap, QColor, QPainter, QGuiApplication, QCursor, QFont, QTextCharFormat, \
	QSyntaxHighlighter, QPen, QFontMetrics, QBrush, QIcon, QIntValidator, QTextCursor, QPalette, QFontDatabase, \
	QShortcut, QKeyEvent
from PySide6.QtCore import Qt, QPoint, QEvent, QTimer, QRect, Signal, QPointF, QObject, QThread, qInstallMessageHandler

from PySide6.QtGui import QUndoStack, QUndoCommand, QKeySequence, QAction

from datetime import datetime

import shutil
import hashlib
import tempfile
import base64
import subprocess
import logging
import traceback
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from logging.handlers import RotatingFileHandler

try:
	from cryptography.hazmat.primitives import hashes, serialization
	from cryptography.hazmat.primitives.asymmetric import padding
	HAS_CRYPTO = True
except Exception:
	HAS_CRYPTO = False


VERSION = "3.3.7.1B"

UPDATE_CHANNELS = ("Main", "Beta")
UPDATE_MANIFEST_PATH_DEFAULT = "Updates"
UPDATE_PRIVATE_REDEEM_URL_DEFAULT = ""
UPDATE_PRIVATE_MANIFEST_URL_DEFAULT = ""

PUBLIC_KEY = ""  # optional: put your PEM public key here if you enable signature checks
UPDATE_REQUIRE_SIGNATURE = False
ALLOW_DEV_UPDATES = os.environ.get("MENUCREATOR_ALLOW_DEV_UPDATES", "0") == "1"

SAVE_DIR = "Saves"
SNAPSHOT_DIR = "Saves/SnapShots"
LAYOUTS_DIR = "Saves/Layouts"

TEMPLATES_FILE = "Templates.json"
LAST_SESSION_FILE = "LastSession.json"
SAVE_VERSION = 1  # Versioned Save Format

GEN_START = "; === MENU_CREATOR GENERATED START ==="
GEN_END = "; === MENU_CREATOR GENERATED END ==="

os.makedirs(SAVE_DIR, exist_ok = True)
os.makedirs(SNAPSHOT_DIR, exist_ok = True)
os.makedirs(LAYOUTS_DIR, exist_ok = True)

TEXCONV_PATH = os.path.join("Tools", "texconv.exe")

SECTION_ORDER = [
	"Namespace"
	"Constants",
	"Present",
	"Key",
	"TextureOverride",
	"ShaderOverride",
	"CommandList",
	"CustomShader",
	"Resource",
]

# LOGS

# Crash-Log

# =========================
# CONFIG
# =========================

LOG_DIR = "Logs"
LOG_FILE = os.path.join(LOG_DIR, "MenuCreator.log")
CRASH_FILE = os.path.join(LOG_DIR, "Crash.log")

os.makedirs(LOG_DIR, exist_ok = True)


# =========================
# LOGGER SETUP
# =========================

class CrashHandler(logging.Handler):
	def emit(self, record):
		if record.levelno >= logging.ERROR:
			try:
				with open(CRASH_FILE, "a", encoding = "utf-8") as f:
					f.write("\n" + "=" * 90 + "\n")
					f.write(f"Time: {datetime.now()}\n")
					f.write(self.format(record))
					f.write("\n")
			except:
				pass


def setup_logger():
	logger = logging.getLogger("app")
	logger.setLevel(logging.DEBUG)

	formatter = logging.Formatter(
		"[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
		datefmt = "%Y-%m-%d %H:%M:%S"
	)

	# main file (rotating)
	file_handler = RotatingFileHandler(
		LOG_FILE,
		maxBytes = 5 * 1024 * 1024,
		backupCount = 3,
		encoding = "utf-8"
	)
	file_handler.setLevel(logging.DEBUG)
	file_handler.setFormatter(formatter)

	# console
	console = logging.StreamHandler(sys.stdout)
	console.setLevel(logging.INFO)
	console.setFormatter(formatter)

	# crash log
	crash_handler = CrashHandler()
	crash_handler.setLevel(logging.ERROR)
	crash_handler.setFormatter(formatter)

	logger.addHandler(file_handler)
	logger.addHandler(console)
	logger.addHandler(crash_handler)

	return logger


logger = setup_logger()


# =========================
# GLOBAL EXCEPTION HOOK
# =========================

def global_exception_hook(exc_type, exc_value, exc_tb):
	error = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

	logger.critical("UNHANDLED EXCEPTION:\n" + error)

	try:
		from PySide6.QtWidgets import QMessageBox

		msg = QMessageBox()
		msg.setWindowTitle("Fatal Error")
		msg.setText("Application crashed. See logs/crash.log")
		msg.setDetailedText(error)
		msg.exec()
	except:
		pass


sys.excepthook = global_exception_hook


# =========================
# QT MESSAGE HANDLER
# =========================

def qt_message_handler(mode, context, message):
	if mode == 0:
		logger.debug(message)
	elif mode == 1:
		logger.info(message)
	elif mode == 2:
		logger.warning(message)
	elif mode == 3:
		logger.error(message)
	elif mode == 4:
		logger.critical(message)


qInstallMessageHandler(qt_message_handler)

# Colors
COLOR_PAGE = QBrush(QColor("#00CFFF"))  # Cyan-ish for pages
COLOR_GROUP = QBrush(QColor("#FF4480"))
COLOR_ELEMENT = QBrush(QColor("#FFFFFF"))  # White for elements
COLOR_ROOT = QBrush(QColor("#FFAA00"))

_COND_RE = re.compile(r"\{if\s+([^:}]+?)\s*:\s*([^}]+?)\}")


def is_windows_dark_mode():
	try:
		key = winreg.OpenKey(
			winreg.HKEY_CURRENT_USER,
			r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
		)
		value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
		return value == 0  # 0 = Dark Mode
	except:
		return False  # fallback


# ---------------- KEYBIND MANAGER ----------------

class KeyBindingsManager:
	def __init__(self, path="Saves/KeyBinds.json"):
		self.path = path

		self.defaults = {
			"move_mode": "G",
			"scale_mode": "S",
			"delete": "X",
			"lock_x": "Z",
			"lock_z": "X",
			"toggle_aspect": "C",
			"cancel": "Esc",
			"help": "F1"
		}

		self.bindings = {}
		self.load()

	def load(self):
		import json, os
		if os.path.exists(self.path):
			with open(self.path, "r") as f:
				self.bindings = {**self.defaults, **json.load(f)}
		else:
			self.bindings = dict(self.defaults)
			self.save()

	def save(self):
		import json
		with open(self.path, "w") as f:
			json.dump(self.bindings, f, indent = 2)

	def set(self, action, seq):
		self.bindings[action] = seq
		self.save()

	def get(self, action):
		return self.bindings.get(action, self.defaults[action])

	def event_to_string(self, e):
		return QKeySequence(e.keyCombination()).toString()

	def matches(self, e, action):
		return self.event_to_string(e) == self.get(action)


# ---------------- REBIND DIALOG ----------------

class RebindDialog(QDialog):
	def __init__(self, kb, action, parent=None):
		super().__init__(parent)
		self.kb = kb
		self.action = action
		self.value = None

		self.setWindowTitle("Press a New Key")
		self.setModal(True)
		self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

		lbl = QLabel(f"Press a New Key for:\n«{self._human(action)}»")
		lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

		hint = QLabel(
			"Esc — Cancel\n"
			"You may use Ctrl / Alt / Shift"
		)
		hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

		v = QVBoxLayout(self)
		v.addWidget(lbl)
		v.addWidget(hint)

		self.resize(380, 140)

	def _human(self, a):
		return a.replace("_", " ").title()

	def keyPressEvent(self, e):
		if e.key() == Qt.Key.Key_Escape:
			self.reject()  # Cancel the dialog
			return

		seq = QKeySequence(e.keyCombination()).toString()

		if seq:
			self.value = seq
			self.accept()
		else:
			super().keyPressEvent(e)


# ---------------- FULL INFO MODAL ----------------

class FullKeyBindingsInfoDialog(QDialog):
	def __init__(self, kb: KeyBindingsManager, parent=None):
		super().__init__(parent)
		self.kb = kb

		self.setWindowTitle("Help")
		self.resize(900, 650)

		main = QVBoxLayout(self)

		title = QLabel("Keyboard Shortcuts")
		title.setStyleSheet("font-size:18px; font-weight:600;")
		main.addWidget(title)

		# ---------- TREE ----------
		self.tree = QTreeWidget()
		self.tree.setColumnCount(4)
		self.tree.setHeaderLabels(["Action", "Key", "Context", "Description"])

		self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
		self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
		self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
		self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

		main.addWidget(self.tree, 1)

		for action in self.kb.defaults.keys():
			key = self.kb.get(action)
			context, desc = self._action_description(action)

			item = QTreeWidgetItem([
				self._human(action),
				"",  # key handled by widget
				context,
				desc
			])

			self.tree.addTopLevelItem(item)

			# ---- Key + Button widget ----
			key_label = QLabel(key)
			key_label.setMinimumWidth(60)

			btn = QPushButton("Rebind")
			btn.setProperty("action", action)
			btn.setProperty("label", key_label)
			btn.clicked.connect(self._on_rebind_clicked)

			w = QWidget()
			hl = QHBoxLayout(w)
			hl.setContentsMargins(4, 0, 4, 0)
			hl.setSpacing(10)
			hl.addWidget(key_label)
			hl.addWidget(btn)

			self.tree.setItemWidget(item, 1, w)

		# ---------- MODIFIERS ----------
		box = QGroupBox("Other")
		box_layout = QVBoxLayout(box)

		md_lbl = QLabel(
			"<br>"
			"<b>In Central Display:</b>"

			"<div style='margin-top:6px; margin-left:12px'><b>Shift:</b></div>"
			"<ul style='margin:0px; padding-left:18px'>"
			"  <li>Grid snapping during Move/Scale</li>"
			"  <li>Show Grid (Scales with Scroll)</li>"
			"</ul>"

			"<div style='margin-top:6px; margin-left:12px'><b>Middle mouse button:</b></div>"
			"<ul style='margin:0px; padding-left:18px'>"
			"  <li>Opens Color Picker for the Clicked Element</li>"
			"</ul>"

			"<div style='margin-top:6px; margin-left:12px'><b>Double-click (LMB):</b></div>"
			"<ul style='margin:0px; padding-left:18px'>"
			"  <li>Opens Image Selector</li>"
			"</ul>"

			"<div style='margin-top:6px; margin-left:12px'><b>Ctrl+Z:</b></div>"
			"<ul style='margin:0px; padding-left:18px'>"
			"  <li>Undo</li>"
			"</ul>"

			"<div style='margin-top:6px; margin-left:12px'><b>Ctrl+Y or Ctrl+Shift+Z:</b></div>"
			"<ul style='margin:0px; padding-left:18px'>"
			"  <li>Re:Do</li>"
			"</ul>"
			"<br>"


			"<b style='margin-top:12px; display:block;'>In Ini Code Text Editors:</b>"

			"<div style='margin-top:6px; margin-left:12px'><b>Control (Ctrl) + Space:</b></div>"
			"<ul style='margin:0px; padding-left:18px'>"
			"  <li>Code AutoComplete</li>"
			"</ul>"
			"<br>"
			"<i style='display:block; margin-top:12px;'>Modifiers are fixed and cannot be Re:Bound.</i>"
		)

		md_lbl.setWordWrap(True)

		box_layout.addWidget(md_lbl)
		main.addWidget(box)

		# ---------- BUTTONS ----------
		buttons = QHBoxLayout()

		self.reset_btn = QPushButton("Reset to Defaults")
		self.reset_btn.clicked.connect(self._on_reset)

		close_btn = QPushButton("Close")
		close_btn.clicked.connect(self.accept)

		buttons.addStretch()
		buttons.addWidget(self.reset_btn)
		buttons.addWidget(close_btn)

		main.addLayout(buttons)

		# ---------- STYLE ----------
		self.setStyleSheet("""
            QDialog { background:#2b2b2b; }
            QLabel { color:#ddd; }
            QTreeWidget { 
                background:#323232;
                color:#eee;
                font-size:13px;
            }
            QGroupBox {
                font-weight:600;
                margin-top:10px;
                color:#ddd;
            }
            QPushButton {
                padding:6px 12px;
                border-radius:6px;
                background:#444;
                color:white;
            }
            QPushButton:hover {
                background:#666;
            }
        """)

	# ---------- HELPERS ----------

	def _human(self, a):
		mapping = {
			"move_mode": "Move Mode",
			"scale_mode": "Scale Mode",
			"delete": "Delete Element(s)",
			"lock_x": "Lock X Axis",
			"lock_z": "Lock Y Axis",
			"toggle_aspect": "Toggle Aspect Ratio",
			"cancel": "Cancel Editing",
			"help": "Show Help"
		}
		return mapping.get(a, a)

	def _action_description(self, action):
		if action == "move_mode":
			return (
				"Normal Mode",
				"Enable Movement for Selected Element(s)"
			)
		if action == "scale_mode":
			return (
				"Normal Mode",
				"Scale selected Element(s)"
			)
		if action == "delete":
			return (
				"Normal Mode",
				"Delete Selected Element(s)"
			)
		if action == "lock_x":
			return (
				"Edit Mode",
				"Lock Horizontal Movement/Scale"
			)
		if action == "lock_z":
			return (
				"Edit Mode",
				"Lock Vertical Movement/Scale"
			)
		if action == "toggle_aspect":
			return (
				"Scale Mode",
				"Lock Aspect (Width/Height) Ratio"
			)
		if action == "cancel":
			return (
				"Edit Mode",
				"Cancel Editing and Restores Previous State"
			)
		if action == "help":
			return (
				"General",
				"Open Help/Re:Bind Modal (This)"
			)

		return ("General", "No Description.")

	# ---------- ACTIONS ----------

	def _on_rebind_clicked(self):
		btn = self.sender()
		action = btn.property("action")
		label = btn.property("label")

		d = RebindDialog(self.kb, action, self)
		if d.exec() == QDialog.DialogCode.Accepted and d.value:
			self.kb.set(action, d.value)
			label.setText(d.value)

	def _on_reset(self):
		for k, v in self.kb.defaults.items():
			self.kb.set(k, v)

		# refresh labels
		for i in range(self.tree.topLevelItemCount()):
			it = self.tree.topLevelItem(i)
			for action in self.kb.defaults.keys():
				if it.text(0) == self._human(action):
					widget = self.tree.itemWidget(it, 1)
					label = widget.layout().itemAt(0).widget()
					label.setText(self.kb.get(action))

	def keyPressEvent(self, e):
		if e.key() == Qt.Key.Key_Escape:
			self.accept()
		else:
			super().keyPressEvent(e)


def extract_dependencies_from_text(text: str) -> list[list[str]]:
	pattern = re.compile(r"Dependencies:\s*([^}\n]+)", re.IGNORECASE)
	found = pattern.findall(text)

	groups = []

	for raw in found:
		parts = re.split(r',\s*', raw)

		for part in parts:
			strings = re.findall(r'"([^"]+)"', part)

			if strings:
				groups.append(strings)

	# 🔥 REMOVE DUPLICATES (preserve order)
	seen = set()
	unique_groups = []

	for group in groups:
		key = tuple(group)  # list → hashable
		if key not in seen:
			seen.add(key)
			unique_groups.append(group)

	return unique_groups


# -------------------------
# 2) helper do czytania typu elementu tolerancyjnie
# -------------------------
def _get_type_name(elem) -> str | None:
	for key in ("type_name", "typeName", "type", "typename", "Type"):
		# atrybut
		try:
			if hasattr(elem, key):
				val = getattr(elem, key)
				if isinstance(val, str) and val:
					return val
		except Exception:
			pass
		# dict-like
		try:
			if isinstance(elem, dict) and key in elem:
				val = elem[key]
				if isinstance(val, str) and val:
					return val
		except Exception:
			pass
	# ostatnia próba: jeżeli element sam ma 'name' lub 'label'
	for key in ("name", "label"):
		try:
			if hasattr(elem, key):
				val = getattr(elem, key)
				if isinstance(val, str) and val:
					return val
		except Exception:
			pass
		try:
			if isinstance(elem, dict) and key in elem:
				val = elem[key]
				if isinstance(val, str) and val:
					return val
		except Exception:
			pass
	return None


def element_matches_dependency(el, dep, dep_to_types=None):
	t = getattr(el, "type_name", None)
	if not t:
		return False

	# najpierw sprawdź mapowanie dependency -> lista typów
	if dep_to_types and dep in dep_to_types:
		return t in dep_to_types[dep]

	# inaczej exact match dependency == typ elementu
	return t == dep


# -------------------------
# 4) główna funkcja: extract -> check against elements -> popup for missing
# -------------------------

def ensure_declared_dependencies_have_elements(parent, text: str, editor,
											   dep_to_types: dict[str, list[str]] | None = None,
											   include_displayed_items: bool = True) -> str:
	"""
    - Wyciąga deklarowane Dependencies z text
    - Dla każdej deklaracji sprawdza, czy istnieje odpowiadający element w editor.code_elements / editor.display_items
      (używa dep_to_types jeśli podasz mapping dependency -> [typeName,...], inaczej robi substring-match)
    - Jeśli jakieś deklaracje nie mają odpowiadających elementów → pokazuje QMessageBox z listą braków (Yes/No)
    - Zwraca oryginalny text (bez modyfikacji). Popup to jedyna akcja.
    """
	declared = extract_dependencies_from_text(text)
	if not declared:
		return text  # nic zadeklarowanego

	# zbierz źródła elementów
	sources = []
	if hasattr(editor, "code_elements"):
		sources.append(getattr(editor, "code_elements"))
	if include_displayed_items and hasattr(editor, "display_items"):
		sources.append(getattr(editor, "display_items"))

	elements = []
	for src in sources:
		if not src:
			continue
		# spodziewamy się iterable
		try:
			for e in src:
				elements.append(e)
		except Exception:
			pass

	missing = []

	for group in declared:  # group = ["A","B"]
		group_matched = False

		for dep in group:
			for el in elements:
				if element_matches_dependency(el, dep, dep_to_types):
					group_matched = True
					break
			if group_matched:
				break

		if not group_matched:
			missing.append(" OR ".join(group))

	if not missing:
		return text  # wszystkie deklaracje mają odpowiadające elementy

	# Qt parent fallback
	if parent is None:
		parent = QApplication.activeWindow()

	msg = QMessageBox(parent)
	msg.setIcon(QMessageBox.Warning)
	msg.setWindowTitle("Missing Dependencies")
	msg.setText("Please add the Corresponding Elements:")
	msg.setInformativeText("\n".join(f"• {m}" for m in missing))
	msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
	msg.setDefaultButton(QMessageBox.Ok)
	msg.exec()

	return text


# PARSER METHODS
CALL_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*\((.*)\)\s*$', re.DOTALL)

METHOD_RE = re.compile(
	r'\.(replace|lower|upper)\((.*)\)\s*$',
	re.IGNORECASE | re.DOTALL
)


def _compile_regex_spec(raw_pat: str):
	pat = raw_pat.strip()
	flags = 0

	# /pattern/imsx style
	if len(pat) >= 2 and pat.startswith('/'):
		last = pat.rfind('/')
		if last > 0:
			flag_str = pat[last + 1:]
			pat_body = pat[1:last]

			for ch in flag_str:
				if ch == 'i':
					flags |= re.IGNORECASE
				elif ch == 'm':
					flags |= re.MULTILINE
				elif ch == 's':
					flags |= re.DOTALL
				elif ch == 'x':
					flags |= re.VERBOSE

			return pat_body, flags, True

	# re:pattern / regex:pattern
	for prefix in ('re:', 'regex:'):
		if pat.lower().startswith(prefix):
			return pat[len(prefix):], flags, True

	return pat, flags, False


def parse_method_chain(expr: str):
	"""
    Rozdziela:
        d_element.name.replace(" ", "").lower()

    na:
        base = "d_element.name"
        calls = ['replace(" ", "")', 'lower()']

    Zwykłe atrybuty z kropką zostają w base.
    """
	if not isinstance(expr, str):
		return None, []

	s = expr.strip()
	if not s:
		return None, []

	calls = []

	while True:
		m = METHOD_RE.search(s)
		if not m:
			break

		name = m.group(1)
		args = m.group(2)

		calls.append(f"{name}({args})")
		s = s[:m.start()].rstrip()

	calls.reverse()
	return s, calls


def parse_call(call: str):
	if not isinstance(call, str):
		return None, []

	m = CALL_RE.match(call.strip())
	if not m:
		return call.strip(), []

	name = m.group(1).strip().lower()
	args_raw = m.group(2).strip()

	args = re.findall(r"""(['"])(.*?)\1""", args_raw, flags = re.DOTALL)
	args = [a[1] for a in args]

	return name, args


def build_ops_from_calls(calls):
	"""
    Zamienia chain calli na wspólną listę operacji.
    """
	ops = []

	for call in calls:
		name, args = parse_call(call)

		if not name:
			continue

		if name == "replace":
			if len(args) >= 2:
				ops.append(("replace", args[0], args[1], 0, False))

		elif name == "lower":
			ops.append(("lower", None, None, 0, False))

		elif name == "upper":
			ops.append(("upper", None, None, 0, False))

		# Tu później dopinasz kolejne:
		# elif name == "strip":
		#     ops.append(("strip", None, None, 0, False))
		# elif name == "startswith":
		#     ...
		#
		# elif name == "replace_regex":
		#     pat, flags, _ = _compile_regex_spec(args[0])  # jeśli masz taki helper
		#     ops.append(("replace", pat, args[1], flags, True))

	return ops


def apply_string_transforms(text, ops):
	"""
    Wspólny engine transformacji.
    Jeśli dostaje listę/tuple, mapuje po elementach.
    """
	if text is None:
		return None

	def apply_single(val):
		if val is None:
			return None

		# Jeśli nie ma żadnych transformacji, zachowaj typ wejściowy.
		if not ops:
			return val

		s = str(val)

		for kind, pattern, repl, flags, is_regex in ops:
			try:
				if kind == "replace":
					if is_regex:
						s = re.sub(pattern, repl, s, flags = flags)
					else:
						s = s.replace(pattern, repl)

				elif kind == "lower":
					s = s.lower()

				elif kind == "upper":
					s = s.upper()

			except Exception:
				pass

		return s

	if isinstance(text, (list, tuple)):
		return [apply_single(x) for x in text]

	return apply_single(text)


def _walk_attr_chain(cur, rest, allow_z=False):
	"""
    Wspólny walker po atrybutach / itemach, z aliasami dla obiektów z pixmap().
    """
	for attr in rest:
		if cur is None:
			return None

		real_item = cur
		screen_pos = None

		try:
			if hasattr(cur, "pixmap"):
				try:
					real_item = next(
						(it for it in editor.scene.items() if getattr(it, "name", None) == cur.name),
						cur
					)
					screen_pos = editor.scene_to_screen(real_item.pos())
				except Exception:
					real_item = cur
					screen_pos = None

				if attr == "width":
					cur = cur.pixmap().width()
					continue
				if attr == "height":
					cur = cur.pixmap().height()
					continue
				if attr == "offset_x":
					cur = screen_pos.x() if screen_pos is not None else None
					continue
				if attr == "offset_y":
					cur = screen_pos.y() if screen_pos is not None else None
					continue
				if "resource" in attr:
					try:
						cur = ExtractResourceName(cur.pixmap_path).replace(" ", "")
					except Exception:
						cur = None
					continue
				if "pixmap_path" in attr:
					try:
						cur = "Resources/" + cur.pixmap_path.split("/")[-1]
					except Exception:
						cur = None
					continue
				if allow_z and attr == "z":
					try:
						cur = int(cur.zValue())
					except Exception:
						try:
							cur = cur.zValue()
						except Exception:
							cur = None
					continue
				if attr == "page":
					try:
						cur = cur.page_index
					except Exception:
						cur = None
					continue
		except Exception:
			pass

		try:
			cur = getattr(cur, attr)
			continue
		except Exception:
			pass

		try:
			cur = cur[attr]
			continue
		except Exception:
			return None

	return cur


# --- POST-DIRECTIVES (collect from chosen if-blocks) ---
_POST_DIRECTIVE_RE = re.compile(r'\{post:\s*(.*?)\s*\}', flags = re.IGNORECASE | re.DOTALL)

# Allowed post commands parser (whitelist)
_POST_CMD_RE = re.compile(
	r"""global\.(replace|re_sub|replace_regex)\(\s*['"]((?:\\['"]|[^'"])*)['"]\s*,\s*['"]((?:\\['"]|[^'"])*)['"]\s*\)""",
	flags = re.IGNORECASE
)


def process_post_commands(full_text: str, post_commands: list, debug: bool = False):
	"""
    Apply collected post_commands in order to full_text.
    Allowed:
        global.replace('old','new')      -> literal replace across full_text
        global.re_sub('pattern','repl')  -> regex substitution
    """

	if debug:
		print("\n[POST] ===== START process_post_commands =====")
		print(f"[POST] Initial text length: {len(full_text)}")
		print(f"[POST] Commands count: {len(post_commands) if post_commands else 0}")
		print(f"[POST] Raw commands: {post_commands}")

	if not post_commands:
		if debug:
			print("[POST] No commands, returning original text")
			print("[POST] ===== END =====\n")
		return full_text

	full = full_text

	for block_index, block in enumerate(post_commands):
		if debug:
			print(f"\n[POST] ---- BLOCK {block_index} ----")
			print(f"[POST] Raw block: {repr(block)}")

		parts = [p.strip() for p in block.split(';') if p.strip()]

		if debug:
			print(f"[POST] Split parts ({len(parts)}): {parts}")

		for part_index, part in enumerate(parts):
			if debug:
				print(f"\n[POST] Part {part_index}: {repr(part)}")

			m = _POST_CMD_RE.search(part)

			if not m:
				if debug:
					print(f"[POST] SKIPPED (no regex match): {repr(part)}")
				continue

			kind, raw_pattern, raw_repl = m.group(1), m.group(2), m.group(3)

			pattern = raw_pattern.replace("\\'", "'")
			repl = raw_repl.replace("\\'", "'")

			if debug:
				print(f"[POST] kind       = {kind}")
				print(f"[POST] raw_pattern= {repr(raw_pattern)}")
				print(f"[POST] raw_repl   = {repr(raw_repl)}")
				print(f"[POST] pattern    = {repr(pattern)}")
				print(f"[POST] repl       = {repr(repl)}")

			pattern, flags, is_regex = _compile_regex_spec(pattern)

			if debug:
				print(f"[POST] compiled pattern = {repr(pattern)}")
				print(f"[POST] flags            = {flags}")
				print(f"[POST] is_regex         = {is_regex}")

			before = full

			if kind.lower() == 'replace':
				if is_regex:
					try:
						full = re.sub(pattern, repl, full, flags = flags)
						if debug:
							print("[POST] Applied regex replace via re.sub")
					except re.error as e:
						if debug:
							print(f"[POST] REGEX ERROR: {e}")
				else:
					full = full.replace(pattern, repl)
					if debug:
						print("[POST] Applied literal replace")
			else:  # re_sub / replace_regex
				try:
					full = re.sub(pattern, repl, full, flags = flags)
					if debug:
						print("[POST] Applied regex sub")
				except re.error as e:
					if debug:
						print(f"[POST] REGEX ERROR: {e}")

			if debug:
				changed = before != full
				print(f"[POST] Changed: {changed}")
				print(f"[POST] New length: {len(full)}")

				if changed:
					print("[POST] Preview after change:")
					print(full[:300])
					print("...")

	if debug:
		print("\n[POST] ===== END process_post_commands =====")
		print(f"[POST] Final text length: {len(full)}\n")

	return full


class SafeMathEvaluator:
	# Allowed operators
	OPS = {
		ast.Add: op.add,
		ast.Sub: op.sub,
		ast.Mult: op.mul,
		ast.Div: op.truediv,
		ast.USub: op.neg,
		ast.UAdd: op.pos,
	}

	def eval(self, expression: str) -> float:
		node = ast.parse(expression, mode = 'eval').body
		return self._eval(node)

	def _eval(self, node):
		if isinstance(node, ast.Constant):
			if isinstance(node.value, (int, float)):
				return node.value
			raise ValueError("Invalid constant")

		elif isinstance(node, ast.BinOp):
			if type(node.op) not in self.OPS:
				raise ValueError("Operator not allowed")
			return self.OPS[type(node.op)](
				self._eval(node.left),
				self._eval(node.right)
			)

		elif isinstance(node, ast.UnaryOp):
			if type(node.op) not in self.OPS:
				raise ValueError("Unary operator not allowed")
			return self.OPS[type(node.op)](
				self._eval(node.operand)
			)

		else:
			raise ValueError(f"Unsupported expression: {type(node).__name__}")


def parse_size(value_str, base_px):
	if not value_str:
		return base_px

	s = value_str.strip()

	try:
		# Replace percentages with computed values
		def repl(match):
			pct = float(match.group(1))
			return str(base_px * pct / 100.0)

		s = re.sub(r'(\d+(\.\d+)?)%', repl, s)

		evaluator = SafeMathEvaluator()
		result = evaluator.eval(s)

		return int(result)

	except:
		return base_px


def _assert_json_safe(d, path="root"):
	if isinstance(d, dict):
		for k, v in d.items():
			if not isinstance(k, (str, int, float, bool)) and k is not None:
				raise TypeError(f"Non-JSON key at {path}: {k!r} ({type(k)})")
			_assert_json_safe(v, f"{path}.{k}")
	elif isinstance(d, list):
		for i, v in enumerate(d):
			_assert_json_safe(v, f"{path}[{i}]")


def auto_expand_drawindexed_matching(display_items, ini_text):
	_DRAW_BLOCK_RE = re.compile(
		r"(?m)^\s*;\s*(?P<name>.+?)\s*(?:\[(?P<annot>[^\]]+)\])?\s*\r?"
		r"\s*drawindexed\s*=\s*(?P<vals>.+?)\s*$"
	)

	def normalize_name(s: str) -> str:
		return re.sub(r"[^a-z0-9]", "", s.lower())

	def find_base_display_item(san_key: str, display_items):
		san_norm = normalize_name(san_key)

		best = None
		best_len = 0

		for el in display_items:
			el_norm = normalize_name(el.name)

			if san_norm.startswith(el_norm):
				if len(el_norm) > best_len:
					best = el
					best_len = len(el_norm)

		return best

	def variant_order(san_name: str):
		m = re.search(r"(\d+)$", san_name)
		if m:
			return int(m.group(1))
		return 0

	def _sanitize_for_key(s: str) -> str:
		s2 = re.sub(r"\(.+?\)", "", s)
		s2 = re.sub(r"[^A-Za-z0-9]", "", s2)
		return s2.lower()

	def _var_name_from_element(el_name: str) -> str:
		v = re.sub(r"[^A-Za-z0-9]", "", el_name)
		if re.match(r"^\d", v):
			v = "x" + v
		return v

	# -----------------------------
	# 1) FIND ALL DRAW BLOCKS
	# -----------------------------
	matches = []
	for m in _DRAW_BLOCK_RE.finditer(ini_text):
		raw = m.group("name").strip()
		san = _sanitize_for_key(raw)
		vals = m.group("vals").strip()

		matches.append({
			"start": m.start(),
			"end": m.end(),
			"name_raw": raw,
			"annot": m.group("annot"),
			"vals": vals,
			"san": san
		})

	if not matches:
		return ini_text

	# -----------------------------
	# 2) GROUP BY SANITIZED NAME
	# -----------------------------
	groups = {}
	for mi in matches:
		el = find_base_display_item(mi["san"], display_items)

		if not el:
			continue

		base_key = normalize_name(el.name)
		groups.setdefault(base_key, []).append((el, mi))

	# -----------------------------
	# 3) BUILD DISPLAY ITEM MAP
	# -----------------------------
	disp_map = {}
	for el in display_items:
		san = _sanitize_for_key(getattr(el, "name", "") or "")
		disp_map.setdefault(san, []).append(el)

	# -----------------------------
	# 4) MATCH GROUPS TO ELEMENTS
	# -----------------------------
	replacements = []

	for san_key, group_matches in groups.items():

		group_matches.sort(key = lambda pair: variant_order(pair[1]["san"]))

		if san_key not in disp_map:
			continue

		el = disp_map[san_key][0]
		toggles = max(1, getattr(el, "toggles_amount", 1))
		var = _var_name_from_element(el.name)

		draws_for_index = []
		comments_for_index = []

		for el2, mi in group_matches:
			draws_for_index.append(mi["vals"])
			comments_for_index.append(mi["name_raw"])

		if len(draws_for_index) < toggles:
			fallback = draws_for_index[0] if draws_for_index else ""
			while len(draws_for_index) < toggles:
				draws_for_index.append(fallback)
				comments_for_index.append(comments_for_index[0] if comments_for_index else el.name)

		# -----------------------------
		# 5) GENERATE OUTPUT
		# -----------------------------
		out_lines = []

		gen_count = min(toggles, len(group_matches))

		if gen_count < len(group_matches):
			print(
				f"[WARN] DisplayItem '{el.name}' Toggles_Amount={toggles}, but found {len(group_matches)} Variants in INI. Leaving Extra Blocks unchanged.")

		if toggles == 1:
			draw0 = draws_for_index[0]
			comment0 = comments_for_index[0]

			out_lines.append(f"if ${var}")
			out_lines.append(f"\t; {comment0}")
			out_lines.append(f"\tdrawindexed = {draw0}")
			out_lines.append("endif")
			out_lines.append("\n")

		else:
			for idx in range(gen_count):
				draw_for_idx = draws_for_index[idx]
				comment_for_idx = comments_for_index[idx]

				out_lines.append(f"if ${var} == {idx}")
				out_lines.append(f"\t; {comment_for_idx}")
				out_lines.append(f"\tdrawindexed = {draw_for_idx}")
				out_lines.append("endif")
				out_lines.append("\n")
		# -----------------------------
		# 5) GENERATE OUTPUT
		# -----------------------------

		repl_text = "\n".join(out_lines).rstrip("\r\n") + "\n\n"

		# -----------------------------
		# 6) REPLACE ONLY GEN_COUNT BLOCKS -- Compute Robust Start/End Boundaries
		# -----------------------------

		raw_start = group_matches[0][1]["start"]
		raw_end = group_matches[gen_count - 1][1]["end"]

		# Move Start to Beginning of it's Line (so we don't lose 'if ...' line if start was interior)
		nlpos = ini_text.rfind('\n', 0, raw_start)
		if nlpos == -1:
			real_start = 0
		else:
			real_start = nlpos + 1  # Char after previous Newline

		# Move End Forward over any Following CR/LF Characters (Absorb Trailing Blank Lines)
		real_end = raw_end
		while real_end < len(ini_text) and ini_text[real_end] in "\r\n":
			real_end += 1

		# Collapse any Amount of Trailing Whitespace/Newlines by Replacing Range [real_start:real_end)
		# with repl_text which already Ends with exactly Two Newlines.

		replacements.append((real_start, real_end, repl_text))

	# -----------------------------
	# 6) APPLY REPLACEMENTS (Merge Overlapping/Adjacent Ranges, then Apply)
	# -----------------------------
	if not replacements:
		return ini_text

	# Sort Ascending by Start — Merge Overlapping / Touching Ranges while Preserving Order
	replacements.sort(key = lambda x: x[0])

	merged = []
	cur_s = None
	cur_e = None
	cur_texts = []

	for s, e, txt in replacements:
		if cur_s is None:
			cur_s, cur_e, cur_texts = s, e, [txt]
			continue

		# If Next Replacement Starts <= Current End -> Overlap or Touching: Merge
		if s <= cur_e:
			# Extend Range and Append Replacement Text in Order
			cur_e = max(cur_e, e)
			cur_texts.append(txt)
		else:
			# push previous merged
			merged.append((cur_s, cur_e, "".join(cur_texts)))
			cur_s, cur_e, cur_texts = s, e, [txt]

	# Push Last
	if cur_s is not None:
		merged.append((cur_s, cur_e, "".join(cur_texts)))

	# Apply Merged Replacements in Reverse Order so Indexes remain Valid
	merged.sort(key = lambda x: x[0], reverse = True)

	new_text = ini_text
	for s, e, repl in merged:
		# Replace Full Original Span [s:e) with Merged Replacement Text
		new_text = new_text[:s] + repl + new_text[e:]

	return new_text


def safe_scaled(pixmap: QPixmap, w: int, h: int) -> QPixmap:
	"""
    Safely scale a QPixmap. If pixmap is None or null, create a minimal empty Pixmap.
    """
	if pixmap is None or pixmap.isNull():
		pixmap = QPixmap(max(1, w), max(1, h))
	return pixmap.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def _norm_key_token(tok: str):
	tok = tok.strip()
	if (tok.startswith('"') and tok.endswith('"')) or (tok.startswith("'") and tok.endswith("'")):
		return tok[1:-1]
	return tok


def _eval_condition_expr(expr, code, all_code=None, idx=None, all_visuals=None, local_vars=None, visual=None):
	"""
    Bezpieczny evaluator dla prostych wyrażeń:
      - presence:  key  OR  code_elem['Key']  OR  variable.attr (d_element.name)
      - equality:  "literal" == "literal"  OR  dotted == "value"  OR  dotted == dotted
      - negation:  not <expr>
    Zwraca True/False.
    local_vars: dict z lokalnymi zmiennymi pętli (np. {'d_element': DisplayedItem})
    visual: optional referenced visual (existing 'element' in pipeline)
    all_visuals: lista wszystkich display_items
    """
	expr = expr.strip()

	# OR (najniższy priorytet)
	left, right = _split_top_level(expr, " or ")
	if right != "":
		return _eval_condition_expr(left, code, all_code, idx, all_visuals, local_vars, visual) or \
			_eval_condition_expr(right, code, all_code, idx, all_visuals, local_vars, visual)

	# AND (wyższy priorytet)
	left, right = _split_top_level(expr, " and ")
	if right != "":
		return _eval_condition_expr(left, code, all_code, idx, all_visuals, local_vars, visual) and \
			_eval_condition_expr(right, code, all_code, idx, all_visuals, local_vars, visual)

	# not ...
	if expr.startswith("not "):
		return not _eval_condition_expr(expr[4:].strip(), code, all_code, idx, all_visuals, local_vars, visual)

	# literal string equality: "a" == "b"
	m_lit = re.match(r'^\s*["\']([^"\']+)["\']\s*==\s*["\']([^"\']+)["\']\s*$', expr)
	if m_lit:
		return m_lit.group(1) == m_lit.group(2)

	# flexible equality: allow either side to be quoted literal, dotted identifier, or bare token
	m_eq_flex = re.match(r"^(.+?)\s*==\s*(.+)$", expr)
	if m_eq_flex:
		left_tok = m_eq_flex.group(1).strip()
		right_tok = m_eq_flex.group(2).strip()

		def resolve_side(tok):
			# quoted string -> return inner literal
			if (tok.startswith('"') and tok.endswith('"')) or (tok.startswith("'") and tok.endswith("'")):
				return tok[1:-1]
			# numeric literal?
			if re.match(r"^[+-]?\d+$", tok):
				try:
					return int(tok)
				except Exception:
					pass
			# try resolve dotted path or variable name
			try:
				val = _resolve_path_value(tok, local_vars, visual, code, all_visuals, all_code, idx)
			except Exception:
				val = None
			# if _resolve_path_value returned a list, use first element (compat with code.params)
			if isinstance(val, (list, tuple)):
				if len(val) == 0:
					return None
				return val[0]
			# fallback: if nothing resolved, treat bare token as literal string
			if val is None:
				return tok
			return val

		lval = resolve_side(left_tok)
		rval = resolve_side(right_tok)

		if lval is None or rval is None or lval == "" or rval == "":
			return False
		if isinstance(lval, int) and isinstance(rval, int):
			return lval == rval
		return str(lval) == str(rval)

	# --- existing stricter equality (kept for compatibility) ---
	m_eq = re.match(
		r"^(?:code_elem\[['\"]([^'\"]+)['\"]\]|([A-Za-z_][\w\.]*(?:\.replace\([^)]*\))?))\s*==\s*['\"]([^'\"]+)['\"]$",
		expr
	)
	if m_eq:
		key = m_eq.group(1) or m_eq.group(2)
		key = _norm_key_token(key)
		val = m_eq.group(3)

		# dotted: e.g. d_element.name
		if "." in key:
			res = _resolve_path_value(key, local_vars, visual, code, all_visuals, all_code, idx)
			return str(res) == val if res is not None else False

		# code.params
		if code:
			vals = code.params.get(key, None)
			if vals is not None:
				if isinstance(vals, (list, tuple)):
					if idx is None:
						return len(vals) > 0 and str(vals[0]) == val
					return idx < len(vals) and str(vals[idx]) == val
				return str(vals) == val

		# fallback: check visual type_name or name
		if all_visuals:
			for v in all_visuals:
				if getattr(v, "type_name", None) == key or getattr(v, "name", None) == key:
					pass

		if all_code:
			for v in all_code:
				if getattr(v, "type_name", None) == key or getattr(v, "name", None) == key:
					pass
		return False

	# presence: code_elem['Key'] or "Key" or dotted var (d_element.name)
	m_key = re.match(r"^(?:code_elem\[['\"]([^'\"]+)['\"]\]|(.+?))$", expr)
	if m_key:
		key = m_key.group(1) or m_key.group(2)
		key = _norm_key_token(key)

		# dotted: try to resolve path (d_element.name, element.page, etc.)
		if "." in key:
			res = _resolve_path_value(key, local_vars, visual, code, all_visuals, all_code, idx)
			if res is None:
				return False
			# truthiness
			if isinstance(res, (list, tuple)):
				return any(str(x).strip() != "" for x in res)
			return bool(res)

		# code.params presence
		if code:
			vals = code.params.get(key, None)
			if vals is not None:
				if isinstance(vals, (list, tuple)):
					if idx is None:
						return any(str(x).strip() != "" for x in vals)
					return idx < len(vals) and str(vals[idx]).strip() != ""
				return bool(vals)

		# fallback: check any displayed visual with type_name or name == key
		if all_visuals:
			for v in all_visuals:
				if getattr(v, "type_name", None) == key or getattr(v, "name", None) == key:
					return True

		if all_code:
			for v in all_code:
				if getattr(v, "type_name", None) == key or getattr(v, "name", None) == key:
					return True
		return False

	return False


_COND_RE = re.compile(r"\{if\s+([^:}]+?)\s*:\s*([^}]+?)\}")

_COND_PLACEHOLDER_RE = re.compile(
	r"\{([A-Za-z_]\w*(?:\.[A-Za-z_]\w*(?:\.(?:replace|lower|upper)\([^)]*\))?)*)\}"
)
_NUMERIC_CMP_RE = re.compile(
	r"^\s*([+-]?\d+(?:\.\d+)?)\s*(==|!=|<=|>=|<|>)\s*([+-]?\d+(?:\.\d+)?)\s*$"
)


def _split_top_level(s, sep="?"):
	"""
    Split s on first top-level sep (not inside {...} or quotes).
    Returns (left, right) where right is "" if sep not found.
    """
	brace_depth = 0
	in_single = False
	in_double = False
	for i, c in enumerate(s):
		if c == "'" and not in_double:
			in_single = not in_single
		elif c == '"' and not in_single:
			in_double = not in_double
		elif not in_single and not in_double:
			if c == "{":
				brace_depth += 1
			elif c == "}":
				if brace_depth > 0:
					brace_depth -= 1
			elif not in_single and not in_double and brace_depth == 0:
				if s.startswith(sep, i):
					left = s[:i]
					right = s[i + len(sep):]
					return left, right
	return s, ""


def expand_if_blocks(lines, code, all_code, visual, all_visuals, local_vars=None, debug=True):
	"""
    Expand multi-line {if COND: ... } blocks with top-level ternary support.
      - supports len(token) where token resolves via _resolve_path_value
      - resolves {x.y} placeholders inside condition before evaluation
      - decodes escape sequences inside chosen block (so '\t' or '\n' count as content)
    """
	text = "\n".join(lines)
	out_parts = []
	L = len(text)

	def resolve_cond_placeholders(cond_str):
		# quick exit
		if ("{" not in cond_str) and ("len(" not in cond_str):
			return cond_str

		# first: replace len(...) with numeric literal
		def _len_repl(m):
			inner = m.group(1).strip()
			try:
				val = _resolve_path_value(inner, local_vars or {}, visual, code, all_visuals, all_code, idx = None)
			except Exception:
				val = None
			if val is None:
				return "0"
			if isinstance(val, (list, tuple)):
				return str(len(val))
			if isinstance(val, str):
				return str(len(val))
			try:
				return str(len(val))
			except Exception:
				try:
					return str(int(val))
				except Exception:
					return "0"

		cond = re.sub(
			r"len\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*(?:\.(?:replace|lower|upper)\([^)]*\))?)*)\s*\)",
			_len_repl,
			cond_str
		)

		# then resolve {placeholders}
		def _repl(m):
			token = m.group(1)
			try:
				val = _resolve_path_value(token, local_vars or {}, visual, code, all_visuals, all_code, idx = None)
			except Exception:
				return m.group(0)
			if val is None:
				return m.group(0)
			if isinstance(val, (int, float)):
				return str(val)
			if isinstance(val, (list, tuple)):
				if len(val) > 0:
					v0 = val[0]
					return repr(v0) if not isinstance(v0, (int, float)) else str(v0)
				return m.group(0)
			return repr(str(val))

		return _COND_PLACEHOLDER_RE.sub(_repl, cond)

	pos = 0
	while True:
		start = text.find("{if ", pos)
		if start == -1:
			out_parts.append(text[pos:])
			break

		out_parts.append(text[pos:start])

		# find matching closing brace
		i = start
		depth = 0
		matched_end = -1
		while i < L:
			ch = text[i]
			if ch == "{":
				depth += 1
			elif ch == "}":
				depth -= 1
				if depth == 0:
					matched_end = i
					break
			i += 1

		if matched_end == -1:
			out_parts.append(text[start:])
			break

		inner = text[start + 1:matched_end]  # without outer {}
		# find top-level colon separating condition and content
		cond_start = len("if ")
		j = cond_start
		inner_len = len(inner)
		brace_depth = 0
		colon_pos = -1
		in_single = in_double = False
		while j < inner_len:
			c = inner[j]
			if c == "'" and not in_double:
				in_single = not in_single
			elif c == '"' and not in_single:
				in_double = not in_double
			elif not in_single and not in_double:
				if c == "{":
					brace_depth += 1
				elif c == "}":
					if brace_depth > 0:
						brace_depth -= 1
				elif c == ":" and brace_depth == 0:
					colon_pos = j
					break
			j += 1

		if colon_pos == -1:
			out_parts.append(text[start:matched_end + 1])
			pos = matched_end + 1
			continue

		cond_raw = inner[cond_start:colon_pos].strip()
		content = inner[colon_pos + 1:]

		cond_resolved = resolve_cond_placeholders(cond_raw)
		if debug:
			print("IF-DEBUG: raw_cond=", cond_raw)
			print("IF-DEBUG: resolved=", cond_resolved)

		# evaluate condition (numeric first)
		ok = False
		try:
			cond_resolved = smart_cast_expr(cond_resolved)
			mnum = _NUMERIC_CMP_RE.match(cond_resolved)

			if mnum:
				a = float(mnum.group(1));
				op = mnum.group(2);
				b = float(mnum.group(3))
				if op == "==":
					ok = (a == b)
				elif op == "!=":
					ok = (a != b)
				elif op == "<":
					ok = (a < b)
				elif op == ">":
					ok = (a > b)
				elif op == "<=":
					ok = (a <= b)
				elif op == ">=":
					ok = (a >= b)
				if debug:
					print(f"IF-DEBUG: numeric {a} {op} {b} -> {ok}")
			else:
				try:
					ok = _eval_condition_expr(cond_resolved, code, all_code, idx = None, all_visuals = all_visuals,
											  local_vars = local_vars, visual = visual)
					if debug:
						print("IF-DEBUG: fallback eval ->", ok)
				except Exception as e:
					if debug:
						print("IF-DEBUG: eval exception:", e)
					ok = False
		except Exception as e:
			if debug:
				print("IF-DEBUG: exception during condition eval:", e)
			ok = False

		# choose true/false block (support top-level '?')
		true_block, false_block = _split_top_level(content, sep = '?')
		chosen_block = true_block if ok else false_block

		# decode escape sequences so '\t' or '\n' count as content
		try:
			decoded_chosen = (
				chosen_block
				.replace("\\n", "\n")
				.replace("\\t", "\t")
			)
		except Exception:
			decoded_chosen = chosen_block

		if decoded_chosen:
			# collect post directives (they are applied later globally)
			found = _POST_DIRECTIVE_RE.findall(decoded_chosen)
			for cmd in found:
				editor.post_commands.append(cmd.strip())
			# remove post directives from output
			decoded_chosen = _POST_DIRECTIVE_RE.sub('', decoded_chosen)

			inner_lines = decoded_chosen.splitlines()
			# pass post_commands recursively so nested ifs collect into the same list
			expanded_inner_lines = expand_if_blocks(inner_lines, code, all_code, visual, all_visuals,
													local_vars = local_vars, debug = debug)
			out_parts.append("\n".join(expanded_inner_lines))
		else:
			if debug:
				print("IF-DEBUG: condition false and no false-block -> skipping")

		# advance after matched_end
		text = text[matched_end + 1:]
		L = len(text)
		pos = 0

	new_text = "".join(out_parts)
	new_lines = new_text.splitlines()
	return new_lines


def _process_conditionals_in_line(line, code, all_code, idx=None, all_visuals=None, local_vars=None, visual=None):
	"""
    Inline/single-line conditional processor with ternary support.
    Accepts content possibly containing top-level '?' and will return chosen expression (or "")
    """
	out = []
	pos = 0
	L = len(line)

	while pos < L:
		start = line.find("{if ", pos)
		if start == -1:
			out.append(line[pos:])
			break

		out.append(line[pos:start])

		i = start
		depth = 0
		matched_end = -1
		while i < L:
			ch = line[i]
			if ch == "{":
				depth += 1
			elif ch == "}":
				depth -= 1
				if depth == 0:
					matched_end = i
					break
			i += 1

		if matched_end == -1:
			out.append(line[start:])
			break

		inner = line[start + 1:matched_end]

		# find top-level colon
		cond_start = len("if ")
		j = cond_start
		inner_len = len(inner)
		brace_depth = 0
		colon_pos = -1
		in_single = in_double = False
		while j < inner_len:
			c = inner[j]
			if c == "'" and not in_double:
				in_single = not in_single
			elif c == '"' and not in_single:
				in_double = not in_double
			elif not in_single and not in_double:
				if c == "{":
					brace_depth += 1
				elif c == "}":
					if brace_depth > 0:
						brace_depth -= 1
				elif c == ":" and brace_depth == 0:
					colon_pos = j
					break
			j += 1

		if colon_pos == -1:
			out.append(line[start:matched_end + 1])
			pos = matched_end + 1
			continue

		cond_raw = inner[cond_start:colon_pos].strip()
		content = inner[colon_pos + 1:]

		# FIRST: handle len(...) in cond_raw
		def _len_inline_repl(m):
			inner_tok = m.group(1).strip()
			try:
				val = _resolve_path_value(inner_tok, local_vars, visual, code, all_visuals, all_code, idx)
			except Exception:
				val = None
			if val is None:
				return "0"
			if isinstance(val, (list, tuple)):
				return str(len(val))
			if isinstance(val, str):
				return str(len(val))
			try:
				return str(len(val))
			except Exception:
				try:
					return str(int(val))
				except Exception:
					return "0"

		cond_with_len = re.sub(
			r"len\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*(?:\.(?:replace|lower|upper)\([^)]*\))?)*)\s*\)",
			_len_inline_repl,
			cond_raw
		)

		# next: resolve {placeholders} inside condition
		def _replace_cond_placeholder(m):
			token = m.group(1)
			try:
				val = _resolve_path_value(token, local_vars, visual, code, all_visuals, all_code, idx)
			except Exception:
				return m.group(0)
			if val is None:
				return m.group(0)
			if isinstance(val, (int, float)):
				return str(val)
			if isinstance(val, (list, tuple)):
				if len(val) > 0:
					v0 = val[0]
					return repr(v0) if not isinstance(v0, (int, float)) else str(v0)
				return m.group(0)
			return repr(str(val))

		cond_resolved = _COND_PLACEHOLDER_RE.sub(_replace_cond_placeholder, cond_with_len)

		# evaluate
		ok = False
		try:
			cond_resolved = smart_cast_expr(cond_resolved)
			mnum = _NUMERIC_CMP_RE.match(cond_resolved)

			if mnum:
				a = float(mnum.group(1));
				op = mnum.group(2);
				b = float(mnum.group(3))
				if op == "==":
					ok = (a == b)
				elif op == "!=":
					ok = (a != b)
				elif op == "<":
					ok = (a < b)
				elif op == ">":
					ok = (a > b)
				elif op == "<=":
					ok = (a <= b)
				elif op == ">=":
					ok = (a >= b)
			else:
				ok = _eval_condition_expr(cond_resolved, code, all_code, idx, all_visuals, local_vars, visual)
		except Exception:
			ok = False

		# ternary split at top-level '?'
		true_part, false_part = _split_top_level(content, sep = '?')
		chosen = true_part if ok else false_part

		# decode escape sequences so '\t' is not treated as empty
		try:
			chosen_decoded = codecs.decode(chosen, "unicode_escape")
		except Exception:
			chosen_decoded = chosen

		if chosen_decoded:
			out.append(chosen_decoded)

		pos = matched_end + 1

	return "".join(out)


# -------------------------
# Path resolver for dotted tokens
# -------------------------

_NUM_TOKEN_RE = re.compile(r"""(?<![\w.])(['"])(-?\d+(?:\.\d+)?)\1(?![\w.])""")


def smart_cast_expr(expr: str):
	if not isinstance(expr, str):
		return expr

	def repl(m):
		return m.group(2)  # bez cudzysłowów

	return _NUM_TOKEN_RE.sub(repl, expr)


def _resolve_base_value(base, local_vars, visual, code, all_visuals, all_code):
	"""
    Odpowiada za całą starą logikę _resolve_path_value,
    ale bez końcowych transformacji stringowych.
    """
	if not isinstance(base, str):
		return None

	p = base.strip()
	if not p:
		return None

	# specjalny root
	if p == "pages":
		try:
			return getattr(editor, "pages", None)
		except Exception:
			return None

	# 'pages.X' idzie normalnie przez split
	parts = p.split(".")
	head = parts[0]
	rest = parts[1:] if len(parts) > 1 else []

	# custom placeholders / code params, e.g. {Verts.x1}, {Verts}
	params = getattr(code, "params", {}) if code else {}
	if head in params:
		vals = params.get(head, [])

		# {Verts.x1} -> second item (x index is 0-based, same as your current code)
		if rest:
			if len(rest) == 1:
				m = re.fullmatch(r"x(\d+)", rest[0], flags = re.IGNORECASE)
				if m:
					j = int(m.group(1)) - 1
					if isinstance(vals, (list, tuple)):
						return vals[j] if j < len(vals) else None
					return vals if j == 0 else None

			# fallback: if someone references nested attrs on the param value
			if isinstance(vals, (list, tuple)):
				# keep current behavior style: resolve on first item
				return _walk_attr_chain(vals[0], rest, allow_z = False) if vals else None

			return _walk_attr_chain(vals, rest, allow_z = False)

		# {Verts} -> first item, like your block placeholder logic
		if isinstance(vals, (list, tuple)):
			return vals[0] if vals else None
		return vals

	# local var
	if head in (local_vars or {}):
		obj = local_vars[head]
		if not rest:
			return obj
		return _walk_attr_chain(obj, rest, allow_z = False)

	# current visual
	if head == "element":
		if visual is None:
			return None
		if not rest:
			return visual
		return _walk_attr_chain(visual, rest, allow_z = True)

	# code params
	if head == "code_elem" and rest:
		key = rest[0]
		vals = code.params.get(key, []) if code else []

		if isinstance(vals, (list, tuple)):
			return vals
		return vals

	# whole collections
	if head == "display_elements":
		try:
			return sorted(all_visuals, key = lambda e: e.zValue())
		except Exception:
			return all_visuals

	if head == "code_elements":
		return all_code

	# fallback: znajdź po name/type_name w visuals
	try:
		if all_visuals:
			for v in all_visuals:
				if getattr(v, "name", None) == head or getattr(v, "type_name", None) == head:
					if not rest:
						return v
					return _walk_attr_chain(v, rest, allow_z = True)
	except Exception:
		pass

	return None


def _resolve_path_value(path, local_vars, visual, code, all_visuals, all_code, idx=None):
	"""
    path:
        'd_element.name'
        'element.type_name'
        'code_elem.SomeKey'
        'element.name.replace("old","new").lower()'

    Obsługuje chain:
        .replace('a','b')
        .lower()
        .upper()

    Zwraca Python value albo None.
    """
	if not isinstance(path, str):
		return None

	p = path.strip()
	if not p:
		return None

	base, calls = parse_method_chain(p)
	if base is None:
		return None

	value = _resolve_base_value(base, local_vars, visual, code, all_visuals, all_code)
	if value is None:
		return None

	ops = build_ops_from_calls(calls)
	if not ops:
		return value

	return apply_string_transforms(value, ops)


# -------------------------
# FOR-block preprocessor
# -------------------------
def expand_for_blocks(lines, code, visual, display_items, code_elements):
	"""
    Rozwijaj bloki:
      {for var in display_elements}
        ... (może zawierać {var.attr} lub ${var.attr} i {if ...})
      {endfor}

    Zwraca nową listę lines (już rozpisanych).

    DODATEK: obsługa liniowych poleceń "{break}" i "{continue}" — mogą być wynikiem
    inline {if ...: {break}} lub zwykłej linii w bloku.
    """
	for_block_start_re = re.compile(r"^\{for\s+([A-Za-z_]\w*)\s+in\s+(display_elements|code_elements)\}\s*$")
	for_block_end_re = re.compile(r"^\{endfor\}\s*$")

	dotted_curly = re.compile(
		r"\{([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\.(?:replace|lower|upper)\([^)]*\))*)(?:\.x(\d+))?\}"
	)

	dotted_dollar = re.compile(
		r"\$\{([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\.(?:replace|lower|upper)\([^)]*\))*)(?:\.x(\d+))?\}"
	)

	expanded_lines = []
	idx_line = 0
	n = len(lines)

	while idx_line < n:
		l = lines[idx_line]
		m = for_block_start_re.match(l.strip())
		if not m:
			expanded_lines.append(l)
			idx_line += 1
			continue

		loop_var = m.group(1)  # e.g. 'd_element'
		collection = m.group(2)  # 'display_elements' or 'code_elements'

		# gather block
		idx_line += 1
		block = []
		while idx_line < n and not for_block_end_re.match(lines[idx_line].strip()):
			block.append(lines[idx_line])
			idx_line += 1
		# skip endfor if present
		idx_line += 1

		# pick collection
		if collection == "display_elements":
			sorted_items = sorted(display_items, key = lambda e: e.zValue())
			coll = sorted_items or []
		else:
			coll = code_elements or []

		if not coll:
			# skip block entirely when collection empty
			continue

		# expand for each item
		outer_break = False
		for item in coll:
			if outer_break:
				break
			local_vars = {loop_var: item}
			# First: expand multi-line {if ...} blocks inside this block with local_vars context.
			# This ensures conditionals that reference d_element get resolved per-item.
			try:
				block_after_if = expand_if_blocks(
					block,
					code = None,
					all_code = code_elements,
					visual = visual,
					all_visuals = display_items,
					local_vars = local_vars,
					debug = False
				)
			except Exception as e:
				# fallback: if something goes wrong, use original block lines
				print("[DEBUG] expand_if_blocks per-item failed:", e)
				block_after_if = list(block)

			# Now process each line (these lines are already chosen/filtered by ifs).
			skip_to_next_item = False
			for bl_proc in block_after_if:
				# At this point bl_proc is a single line where any {if ...} / ? ternary was already resolved.
				# Do replacements of ${...} and {...} dotted tokens with local_vars context.
				def doll_sub(mobj):
					path = mobj.group(1)
					if "." not in path:
						return mobj.group(0)
					try:
						val = _resolve_path_value(path, local_vars, visual, code, display_items, code_elements,
												  idx = None)
					except Exception as e:
						val = None
						# print("[DEBUG][doll_sub] EXC resolving", path, "err:", e)
					# print(f"[DEBUG] resolve ${ {path} } -> {val!r} (loop_var keys: {list(local_vars.keys())})")
					if val is None:
						return mobj.group(0)
					# If this replacement is inside a condition-like line, quote strings.
					if '{if ' in bl_proc:
						if isinstance(val, (list, tuple)):
							val = val[0] if val else ""
						if isinstance(val, str):
							return '"' + val.replace('"', '\\"') + '"'
					return str(val)

				line_after_dollar = dotted_dollar.sub(doll_sub, bl_proc)

				def curly_sub(mobj):
					path = mobj.group(1)
					if "." not in path:
						return mobj.group(0)
					try:
						val = _resolve_path_value(path, local_vars, visual, code, display_items, code_elements,
												  idx = None)
					except Exception as e:
						val = None

					if val is None:
						return mobj.group(0)
					if '{if ' in bl_proc:
						if isinstance(val, (list, tuple)):
							val = val[0] if val else ""
						if isinstance(val, str):
							return '"' + val.replace('"', '\\"') + '"'
					return str(val)

				line_after_curly = dotted_curly.sub(curly_sub, line_after_dollar)

				# now line_after_curly is final substituted line for this item
				stripped = line_after_curly.strip()

				# handle control directives after substitution
				tokens = stripped.split()

				if tokens and tokens[0] == "{continue}":
					skip_to_next_item = True
					break

				if tokens and tokens[0] == "{break}":
					outer_break = True
					skip_to_next_item = True
					break

				# append the final line
				expanded_lines.append(line_after_curly)

			if skip_to_next_item:
				continue

	return expanded_lines


def snap(v, g):
	return math.floor((v + g * 0.5) / g) * g


class LockedView(QGraphicsView):
	viewChanged = Signal()

	def __init__(self, scene, grid_size=16, major_factor=5, parent=None):
		super().__init__(scene, parent)

		self.grid_size = grid_size
		self.major_factor = major_factor
		self.show_grid = False

		self.base_grid = grid_size  # world units
		self.grid_scale = 1.0  # virtual zoom
		self.grid_min = 0.25
		self.grid_max = 8.0
		self.grid_step = 1.25

		self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
		self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

	def resizeEvent(self, event):
		super().resizeEvent(event)
		self.viewChanged.emit()

	def wheelEvent(self, event):
		if event.modifiers() & Qt.ShiftModifier:
			factor = self.grid_step if event.angleDelta().y() > 0 else 1 / self.grid_step
			new_scale = self.grid_scale * factor

			if self.grid_min <= new_scale <= self.grid_max:
				self.grid_scale = new_scale
				self.viewport().update()
				self.viewChanged.emit()

			event.accept()
		else:
			event.ignore()

	def drawBackground(self, painter, rect):
		super().drawBackground(painter, rect)

		if not self.show_grid:
			return

		painter.save()

		minor = self.base_grid * self.grid_scale
		major = minor * self.major_factor

		minor_pen = QPen(QColor(200, 200, 200, 80), 1)
		major_pen = QPen(QColor(140, 140, 140, 140), 1.5)

		left = rect.left() - (rect.left() % minor)
		top = rect.top() - (rect.top() % minor)

		x = left
		while x < rect.right():
			painter.setPen(major_pen if int(x / minor) % 5 == 0 else minor_pen)
			painter.drawLine(x, rect.top(), x, rect.bottom())
			x += minor

		y = top
		while y < rect.bottom():
			painter.setPen(major_pen if int(y / minor) % 5 == 0 else minor_pen)
			painter.drawLine(rect.left(), y, rect.right(), y)
			y += minor

		painter.restore()

	def scrollContentsBy(self, dx, dy):
		super().scrollContentsBy(dx, dy)
		self.viewChanged.emit()


def load_pixmap_any(path: str, cache: dict) -> QPixmap:
	if not path:
		print(" -> Empty path")
		return QPixmap()

	# Normalize path
	path = os.path.abspath(path)

	# Check file existence
	if not os.path.isfile(path):
		print(" !! FILE DOES NOT EXIST")
		return QPixmap()

	# ---------------- RAM CACHE ----------------
	pix = cache.get(path)
	if pix is not None:
		return pix

	# ---------------- Native Qt load ----------------
	pix = QPixmap(path)

	if not pix.isNull():
		cache[path] = pix
		return pix
	elif not path.lower().endswith(".dds"):
		print(" !! Qt load FAILED")

	# ---------------- DDS via texconv ----------------
	if path.lower().endswith(".dds"):

		if not os.path.isfile(TEXCONV_PATH):
			print(" !! TEXCONV NOT FOUND:", TEXCONV_PATH)
			return QPixmap()

		try:
			with tempfile.TemporaryDirectory() as tmp:
				cmd = [
					TEXCONV_PATH,
					"-ft", "png",
					"-o", tmp,
					path,
				]

				result = subprocess.run(
					cmd,
					stdout = subprocess.PIPE,
					stderr = subprocess.PIPE,
				)

				# Find PNG
				for name in os.listdir(tmp):
					if name.lower().endswith(".png"):
						png_path = os.path.join(tmp, name)

						pix = QPixmap(png_path)

						if not pix.isNull():
							cache[path] = pix
							return pix
						else:
							print(" !! PNG load FAILED")

				print(" !! No PNG produced by texconv")

		except Exception as e:
			print(" !! TEXCONV EXCEPTION:", e)

	# ---------------- Final fallback ----------------
	print(" !! Image Loading Failed")
	return QPixmap()


def ExtractResourceName(text):
	words = re.split(r"[^a-zA-Z0-9]+", text.split('/')[-1].split('.')[0])
	return "".join(w.capitalize() for w in words if w)


class IniHighlighter(QSyntaxHighlighter):
	def __init__(self, parent):
		super().__init__(parent)
		self.rules = []

		# Ifs
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(248, 203, 204))
		section_format.setFontWeight(QFont.Light)
		self.rules.append((r"^\s*if|elif|else if|else|endif", section_format))

		# Section: [Key*]
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(172, 142, 255))
		section_format.setFontWeight(QFont.Bold)
		self.rules.append((r"\[Key\w*]?", section_format))

		# Replace Vals
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(239, 195, 199))
		section_format.setFontWeight(QFont.Light)
		self.rules.append((r"\{[a-zA-Z._]*}?|}", section_format))

		# {For/If/endfor/break/continue/Loop:/EndLoop
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(72, 158, 137))
		section_format.setFontWeight(QFont.Light)
		self.rules.append((r"{for|{if|{endfor}|{break}|{continue}|{Loop:}|{EndLoop}|{skip}", section_format))

		# Section: [CustomShader*]
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(200, 100, 0))
		section_format.setFontWeight(QFont.Bold)
		self.rules.append((r"\[Constants\w*]?", section_format))

		# Section: [Present*]
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(100, 200, 0))
		section_format.setFontWeight(QFont.Bold)
		self.rules.append((r"\[Present\w*]?", section_format))

		# Section: [Resource*]
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(200, 200, 0))
		section_format.setFontWeight(QFont.Bold)
		self.rules.append((r"\[Resource\w*]?", section_format))

		# Section: [CommandList*]
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(100, 200, 100))
		section_format.setFontWeight(QFont.Bold)
		self.rules.append((r"\[CommandList\w*]?", section_format))

		# Section: [CustomShader*]
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(0, 125, 100))
		section_format.setFontWeight(QFont.Bold)
		self.rules.append((r"\[CustomShader\w*]?", section_format))

		# Section: [TextureOverride*]
		section_format = QTextCharFormat()
		section_format.setForeground(QColor(200, 100, 100))
		section_format.setFontWeight(QFont.Bold)
		self.rules.append((r"\[TextureOverride\w*]?", section_format))

		# Declared Variables: global $var
		var_format = QTextCharFormat()
		var_format.setForeground(QColor(0, 100, 200))
		var_format.setFontWeight(QFont.Bold)
		self.rules.append((r"global\s+(?:persist\s+)?\$[A-Za-z_][A-Za-z0-9_]*", var_format))

		# Variables: $var
		var_format = QTextCharFormat()
		var_format.setForeground(QColor(48, 203, 255))
		var_format.setFontWeight(QFont.Bold)
		self.rules.append((r"(?<!global )(?<!persist )\$[A-Za-z_][A-Za-z0-9_]*", var_format))

		# Variables: $var
		var_format = QTextCharFormat()
		var_format.setForeground(QColor(148, 252, 252))
		var_format.setFontWeight(QFont.Bold)
		self.rules.append((r"\$\\[A-Za-z_][A-Za-z0-9_]*(?:\\[A-Za-z_][A-Za-z0-9_]*)*", var_format))

		# IniParams: x1 y2 z3 w4
		var_format = QTextCharFormat()
		var_format.setForeground(QColor(100, 100, 255))
		var_format.setFontWeight(QFont.Bold)
		self.rules.append((r"^[xyzw]\d+", var_format))

		# IniParams: ps-t
		var_format = QTextCharFormat()
		var_format.setForeground(QColor(175, 125, 100))
		var_format.setFontWeight(QFont.Bold)
		self.rules.append((r"^(\s+)?ps-t\d+", var_format))

		# run = ... lines
		run_format = QTextCharFormat()
		run_format.setForeground(QColor(0, 150, 0))
		self.rules.append((r"^\s*run\s*=", run_format))

	def highlightBlock(self, text):
		for pattern, fmt in self.rules:
			for match in re.finditer(pattern, text):
				start, end = match.span()
				self.setFormat(start, end - start, fmt)


# ================= TYPES SYSTEM =================

TYPES_FILE = os.path.join(SAVE_DIR, "Types.json")
TYPES_VERSION = 1


class CodeElement:
	def __init__(self, name, type_name, params=None, ref_visual=None):
		self.name = name
		self.type_name = type_name
		self.params = params or {}
		self.ref_visual = ref_visual  # ← store NAME, not object

	def to_dict(self):
		return {
			"name": self.name,
			"type": self.type_name,
			"params": self.params,
			"ref_visual": self.ref_visual
		}

	@staticmethod
	def from_dict(d):
		return CodeElement(
			d.get("name", "CodeElement"),
			d.get("type", "Visual"),
			d.get("params", {}),
			d.get("ref_visual")
		)


# ---------- Windows VK conversion ----------

user32 = ctypes.windll.user32
MAPVK_VSC_TO_VK_EX = 3


def scancode_to_vk(scancode: int) -> int:
	try:
		return user32.MapVirtualKeyW(scancode, MAPVK_VSC_TO_VK_EX)
	except Exception:
		return 0


VK_NAMES = {
	0x08: "VK_BACK",
	0x09: "VK_TAB",
	0x0D: "VK_RETURN",
	0x10: "VK_SHIFT",
	0x11: "VK_CONTROL",
	0x12: "VK_MENU",
	0x1B: "VK_ESCAPE",
	0x20: "VK_SPACE",
	0x21: "VK_PRIOR",
	0x22: "VK_NEXT",
	0x23: "VK_END",
	0x24: "VK_HOME",
	0x25: "VK_LEFT",
	0x26: "VK_UP",
	0x27: "VK_RIGHT",
	0x28: "VK_DOWN",
	0x2D: "VK_INSERT",
	0x2E: "VK_DELETE",
	# OEM punctuation
	0xBA: "VK_OEM_1",
	0xBB: "VK_OEM_PLUS",
	0xBC: "VK_OEM_COMMA",
	0xBD: "VK_OEM_MINUS",
	0xBE: "VK_OEM_PERIOD",
	0xBF: "VK_OEM_2",
	0xC0: "VK_OEM_3",
	0xDB: "VK_OEM_4",
	0xDC: "VK_OEM_5",
	0xDD: "VK_OEM_6",
	0xDE: "VK_OEM_7",
}


def vk_to_string(vk: int) -> str:
	if vk is None or vk == 0:
		return ""

	if 0x41 <= vk <= 0x5A:
		return chr(vk)

	if 0x30 <= vk <= 0x39:
		return chr(vk)

	if 0x70 <= vk <= 0x87:
		return f"VK_F{vk - 0x6F}"

	if vk == 0x10:
		return "VK_SHIFT"
	if vk == 0x11:
		return "VK_CONTROL"
	if vk == 0x12:
		return "VK_MENU"

	if vk in (0x25, 0x26, 0x27, 0x28):
		return {0x25: "VK_LEFT", 0x26: "VK_UP", 0x27: "VK_RIGHT", 0x28: "VK_DOWN"}[vk]

	if vk in VK_NAMES:
		return VK_NAMES[vk]

	return f"VK_{vk}"


def vk_to_label(vk_token: str) -> str:
	if not vk_token:
		return ""

	if vk_token.startswith("VK_"):
		body = vk_token[3:]

		if len(body) == 1:
			return body

		if body.startswith("F") and body[1:].isdigit():
			return body

		nice = {
			"SPACE": "Space",
			"RETURN": "Enter",
			"TAB": "Tab",
			"BACK": "Backspace",
			"ESCAPE": "Esc",
			"DELETE": "Del",
			"INSERT": "Ins",
			"LEFT": "Left",
			"RIGHT": "Right",
			"UP": "Up",
			"DOWN": "Down",
			"HOME": "Home",
			"END": "End",
			"PRIOR": "Page Up",
			"NEXT": "Page Down",
			"SHIFT": "Shift",
			"CONTROL": "Ctrl",
			"MENU": "Alt",
		}

		return nice.get(body, body.replace("_", " ").title()) + f" ({vk_token})"

	return vk_token


def is_vk_down(vk_code: int) -> bool:
	try:
		return (ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000) != 0
	except Exception:
		return False


# ---------- Key editor ----------

class KeyCaptureEdit(QLineEdit):
	comboChanged = Signal(str)
	finished = Signal(str)
	cleared = Signal()

	def __init__(self, parent=None, eat_events=True):
		super().__init__(parent)
		self.setPlaceholderText("Press keys...")
		self.setReadOnly(True)
		self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

		self._pressed_order = []  # Qt keys, non-modifiers
		self._key_to_sc = {}  # Qt key -> scan code
		self._mods = set()  # {"VK_CONTROL", "VK_MENU", "VK_SHIFT"}

		self.vk = ""
		self._eat_events = eat_events

		self._commit_timer = QTimer(self)
		self._commit_timer.setSingleShot(True)
		self._commit_timer.setInterval(50)  # 🔥 TU
		self._commit_timer.timeout.connect(self._emit_finished_once)
		self._commit_delay_ms = 50

		self._finished_sent = False

	def _reset_finished_guard(self):
		self._finished_sent = False

	def _emit_finished_once(self):
		if self._finished_sent:
			return
		self._finished_sent = True
		self.finished.emit(self.vk)

	def _update_mods_from_state(self, mods):
		if mods & Qt.KeyboardModifier.ControlModifier:
			self._mods.add("VK_CONTROL")
		else:
			self._mods.discard("VK_CONTROL")

		if mods & Qt.KeyboardModifier.AltModifier:
			self._mods.add("VK_MENU")
		else:
			self._mods.discard("VK_MENU")

		if mods & Qt.KeyboardModifier.ShiftModifier:
			self._mods.add("VK_SHIFT")
		else:
			self._mods.discard("VK_SHIFT")

	def _build_parts(self):
		parts = []

		if "VK_CONTROL" in self._mods:
			parts.append("VK_CONTROL")
		if "VK_MENU" in self._mods:
			parts.append("VK_MENU")
		if "VK_SHIFT" in self._mods:
			parts.append("VK_SHIFT")

		for qt_key in self._pressed_order:
			sc = self._key_to_sc.get(qt_key, 0)
			if not sc:
				continue
			vk_num = scancode_to_vk(sc)
			token = vk_to_string(vk_num)
			if token and token not in parts:
				parts.append(token)

		return parts

	def _rebuild(self):
		parts = self._build_parts()
		canonical = " ".join(parts)
		label = " + ".join(vk_to_label(p) for p in parts) if parts else ""

		if canonical != self.vk:
			self.vk = canonical
			self.setText(label)
			self.comboChanged.emit(self.vk)
			self._reset_finished_guard()

		self._commit_timer.stop()
		if canonical:
			self._commit_timer.start(self._commit_delay_ms)

	def _clear_capture(self):
		self._pressed_order.clear()
		self._key_to_sc.clear()
		self._mods.clear()
		self.vk = ""
		self.setText("")
		self.comboChanged.emit(self.vk)
		self.cleared.emit()
		self._reset_finished_guard()
		self._commit_timer.stop()

	def keyPressEvent(self, ev):
		if not isinstance(ev, QKeyEvent):
			super().keyPressEvent(ev)
			return

		if ev.isAutoRepeat():
			if self._eat_events:
				return
			super().keyPressEvent(ev)
			return

		key = ev.key()
		sc = ev.nativeScanCode()

		if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
			self._clear_capture()
			return

		if key == Qt.Key.Key_Shift:
			self._mods.add("VK_SHIFT")
		elif key == Qt.Key.Key_Control:
			self._mods.add("VK_CONTROL")
		elif key == Qt.Key.Key_Alt:
			self._mods.add("VK_MENU")
		elif key == Qt.Key.Key_Meta:
			self._mods.add("VK_MENU")
		else:
			if key not in self._pressed_order:
				self._pressed_order.append(key)
			self._key_to_sc[key] = sc

		# sync from actual modifier state too
		self._update_mods_from_state(ev.modifiers())
		self._rebuild()

		if self._eat_events:
			return
		super().keyPressEvent(ev)

	def keyReleaseEvent(self, ev):
		if not isinstance(ev, QKeyEvent):
			super().keyReleaseEvent(ev)
			return

		if ev.isAutoRepeat():
			if self._eat_events:
				return
			super().keyReleaseEvent(ev)
			return

		key = ev.key()

		if key == Qt.Key.Key_Shift:
			self._mods.discard("VK_SHIFT")
		elif key == Qt.Key.Key_Control:
			self._mods.discard("VK_CONTROL")
		elif key == Qt.Key.Key_Alt:
			self._mods.discard("VK_MENU")
		elif key == Qt.Key.Key_Meta:
			self._mods.discard("VK_MENU")
		else:
			if key in self._pressed_order:
				try:
					self._pressed_order.remove(key)
				except ValueError:
					pass
			self._key_to_sc.pop(key, None)

		self._update_mods_from_state(ev.modifiers())
		self._rebuild()

		if self._eat_events:
			return
		super().keyReleaseEvent(ev)

	def focusInEvent(self, ev):
		super().focusInEvent(ev)

		# seed modifiers when focus is gained
		if is_vk_down(0x11):
			self._mods.add("VK_CONTROL")
		if is_vk_down(0x12):
			self._mods.add("VK_MENU")
		if is_vk_down(0x10):
			self._mods.add("VK_SHIFT")

		self._rebuild()

	def focusOutEvent(self, ev):
		super().focusOutEvent(ev)
		self._commit_timer.stop()
		self._emit_finished_once()


class KeyDelegate(QStyledItemDelegate):
	def createEditor(self, parent, option, index):
		placeholder = index.sibling(index.row(), 0).data()

		if str(placeholder).lower() == "key":
			editor = KeyCaptureEdit(parent)

			editor.comboChanged.connect(lambda _v, e=editor: self.commitData.emit(e))

			editor.finished.connect(lambda _v, e=editor: self._commit_and_close(e))
			editor.cleared.connect(lambda e=editor: self._commit_and_close(e))

			return editor

		return super().createEditor(parent, option, index)

	def _commit_and_close(self, editor):
		if editor is None:
			return

		# Guard against double close/commit
		if not editor.isVisible():
			return

		self.commitData.emit(editor)
		self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)

	def setEditorData(self, editor, index):
		if isinstance(editor, KeyCaptureEdit):
			val = index.data(Qt.ItemDataRole.UserRole) or ""
			editor.vk = val
			editor.setText(vk_to_label(val) if val else "")
			return

		super().setEditorData(editor, index)

	def setModelData(self, editor, model, index):
		if isinstance(editor, KeyCaptureEdit):
			vk = editor.vk or ""
			model.setData(index, vk, Qt.ItemDataRole.EditRole)
			model.setData(index, vk, Qt.ItemDataRole.UserRole)
			return

		super().setModelData(editor, model, index)


class PlaceholderTable(QTableWidget):
	def __init__(self, parent=None):
		super().__init__(0, 4, parent)
		self.setHorizontalHeaderLabels(["Placeholder", "Slot", "Value", "Result"])
		self.horizontalHeader().setStretchLastSection(True)
		self.verticalHeader().setVisible(False)
		self.setEditTriggers(QAbstractItemView.AllEditTriggers)

		# User edits -> update internal data, but do NOT rebuild the table here
		self.cellChanged.connect(self.on_cell_changed)

		# Keep your custom editor for Value column
		self.setItemDelegateForColumn(2, KeyDelegate(self))

		# placeholder -> list[str] (raw values)
		self.values = {}

		# placeholder -> list[str] (matching INI lines)
		self.placeholder_lines = {}

		# preserve placeholder order
		self.placeholder_order = []

		# placeholder -> max count or None
		self.placeholder_max = {}

		# "placeholder_slot" = grouped by placeholder, slots ascending
		# "slot" = all slot 0 rows first, then slot 1, etc.
		self.sort_mode = "placeholder_slot"

		self._updating = False
		self._row_map = []  # visual row -> (placeholder, slot)

	def set_sort_mode(self, mode="placeholder_slot"):
		if mode not in ("placeholder_slot", "slot"):
			mode = "placeholder_slot"
		self.sort_mode = mode
		self.rebuild_table()

	def set_placeholders(self, placeholders, values=None, ini_lines=None):
		"""
        placeholders: dict placeholder -> max_count (int) or None
        values: dict placeholder -> list of prefilled values
        ini_lines: list of INI lines containing placeholders
        """
		self._updating = True
		self.blockSignals(True)

		self.placeholder_lines.clear()
		self.placeholder_order = []
		self.placeholder_max = {}
		self.values = {}

		for name, max_count in (placeholders or {}).items():
			self.placeholder_order.append(name)
			self.placeholder_max[name] = None if max_count is None else int(max_count)

			# collect matching lines for this placeholder
			if ini_lines:
				for line in ini_lines:
					if re.search(rf"\{{{re.escape(name)}(?:\.x\d+)?\}}", line):
						self.placeholder_lines.setdefault(name, []).append(line)

			# normalize values into a list
			raw_vals = []
			if values and name in values:
				v = values[name]
				if isinstance(v, list):
					raw_vals = ["" if x is None else str(x) for x in v]
				elif v is not None and str(v).strip() != "":
					raw_vals = [str(v)]

			# always show at least one slot
			if not raw_vals:
				raw_vals = [""]

			# if the last slot is filled, keep one extra empty slot if allowed
			if raw_vals[-1].strip():
				if self.placeholder_max[name] is None or len(raw_vals) < self.placeholder_max[name]:
					raw_vals.append("")

			# respect max count
			if self.placeholder_max[name] is not None:
				raw_vals = raw_vals[: self.placeholder_max[name]]

			self.values[name] = raw_vals

		self.blockSignals(False)
		self._updating = False

		self.rebuild_table()

	def rebuild_table(self):
		self._updating = True
		self.blockSignals(True)
		self.setSortingEnabled(False)

		rows = []
		for p_index, placeholder in enumerate(self.placeholder_order):
			slot_count = len(self.values.get(placeholder, [""]))
			for slot in range(slot_count):
				rows.append((placeholder, slot, p_index))

		if self.sort_mode == "slot":
			rows.sort(key = lambda x: (x[1], x[2]))
		else:
			rows.sort(key = lambda x: (x[2], x[1]))

		self._row_map = [(p, s) for p, s, _ in rows]
		self.setRowCount(len(self._row_map))

		for row, (placeholder, slot) in enumerate(self._row_map):
			raw_value = self._get_value(placeholder, slot)
			display_value = vk_to_label(raw_value) if isinstance(raw_value, str) and raw_value.startswith(
				"VK_") else str(raw_value)

			# Placeholder (locked)
			p_item = QTableWidgetItem(placeholder)
			p_item.setFlags(p_item.flags() & ~Qt.ItemIsEditable)
			self.setItem(row, 0, p_item)

			# Slot (locked, numeric)
			s_item = QTableWidgetItem(str(slot))
			s_item.setFlags(s_item.flags() & ~Qt.ItemIsEditable)
			s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
			self.setItem(row, 1, s_item)

			# Value (editable)
			v_item = QTableWidgetItem(display_value)
			if isinstance(raw_value, str) and raw_value.startswith("VK_"):
				v_item.setData(Qt.UserRole, raw_value)
			self.setItem(row, 2, v_item)

			# Result (locked)
			result = self.format_result(placeholder, slot, raw_value)
			r_item = QTableWidgetItem(result)
			r_item.setFlags(r_item.flags() & ~Qt.ItemIsEditable)
			self.setItem(row, 3, r_item)

		self.resizeColumnsToContents()
		self.setSortingEnabled(False)

		self.blockSignals(False)
		self._updating = False

	def _get_value(self, placeholder, slot):
		vals = self.values.get(placeholder, [])
		if 0 <= slot < len(vals):
			return vals[slot]
		return ""

	def _set_value(self, placeholder, slot, value):
		vals = self.values.setdefault(placeholder, [""])

		while len(vals) <= slot:
			vals.append("")

		vals[slot] = value

		max_allowed = self.placeholder_max.get(placeholder)
		if max_allowed is not None and len(vals) > max_allowed:
			vals[:] = vals[:max_allowed]

	def _find_insert_row_for_new_slot(self, placeholder, slot):
		"""
        Return visual row index where a new slot row should be inserted.
        This avoids rebuilding the whole table while editing.
        """
		if not self._row_map:
			return 0

		if self.sort_mode == "slot":
			# Keep rows roughly slot-sorted without full rebuild:
			# insert before the first row whose slot is greater than the new one.
			for i, (_, existing_slot) in enumerate(self._row_map):
				if existing_slot > slot:
					return i
			return self.rowCount()

		# placeholder_slot mode:
		# insert after the last row with the same placeholder
		insert_at = None
		for i, (p, _) in enumerate(self._row_map):
			if p == placeholder:
				insert_at = i + 1
		if insert_at is None:
			return self.rowCount()
		return insert_at

	def _insert_slot_row(self, placeholder, slot, value=""):
		"""
        Insert one visual row without rebuilding the whole table.
        """
		insert_at = self._find_insert_row_for_new_slot(placeholder, slot)

		self._updating = True
		self.blockSignals(True)

		self.insertRow(insert_at)
		self._row_map.insert(insert_at, (placeholder, slot))

		p_item = QTableWidgetItem(placeholder)
		p_item.setFlags(p_item.flags() & ~Qt.ItemIsEditable)
		self.setItem(insert_at, 0, p_item)

		s_item = QTableWidgetItem(str(slot))
		s_item.setFlags(s_item.flags() & ~Qt.ItemIsEditable)
		s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
		self.setItem(insert_at, 1, s_item)

		display_value = vk_to_label(value) if isinstance(value, str) and value.startswith("VK_") else str(value)
		v_item = QTableWidgetItem(display_value)
		if isinstance(value, str) and value.startswith("VK_"):
			v_item.setData(Qt.UserRole, value)
		self.setItem(insert_at, 2, v_item)

		result = self.format_result(placeholder, slot, value)
		r_item = QTableWidgetItem(result)
		r_item.setFlags(r_item.flags() & ~Qt.ItemIsEditable)
		self.setItem(insert_at, 3, r_item)

		self.blockSignals(False)
		self._updating = False

	def on_cell_changed(self, row, col):
		if self._updating:
			return

		if row < 0 or row >= len(self._row_map):
			return

		placeholder, slot = self._row_map[row]

		# Only Value column mutates stored data
		if col != 2:
			self.refresh_row(row)
			return

		item = self.item(row, 2)
		if not item:
			return

		raw_value = item.data(Qt.UserRole) or item.text()
		raw_value = "" if raw_value is None else str(raw_value)

		# store data
		self._set_value(placeholder, slot, raw_value)

		# update result for this row only
		self.refresh_row(row)

		# if user filled the last slot, append one more empty slot if allowed
		vals = self.values.get(placeholder, [])
		max_allowed = self.placeholder_max.get(placeholder)

		if raw_value.strip() and slot == len(vals) - 1:
			if max_allowed is None or len(vals) < max_allowed:
				new_slot = len(vals)
				self._set_value(placeholder, new_slot, "")
				self._insert_slot_row(placeholder, new_slot, "")

	def append_slot(self, placeholder, slot_index=None):
		"""
        Manual add of a slot. This does NOT rebuild the whole table.
        """
		max_allowed = self.placeholder_max.get(placeholder)
		vals = self.values.setdefault(placeholder, [""])

		if max_allowed is not None and len(vals) >= max_allowed:
			return

		new_slot = len(vals)
		self._set_value(placeholder, new_slot, "")
		self._insert_slot_row(placeholder, new_slot, "")

	def refresh_row(self, row):
		if row < 0 or row >= len(self._row_map):
			return

		placeholder, slot = self._row_map[row]
		item = self.item(row, 2)
		if not item:
			return

		raw_value = item.data(Qt.UserRole) or item.text()
		raw_value = "" if raw_value is None else str(raw_value)

		result = self.format_result(placeholder, slot, raw_value)

		self._updating = True
		self.blockSignals(True)
		self.setItem(row, 3, QTableWidgetItem(result))
		self.blockSignals(False)
		self._updating = False

	def format_result(self, placeholder, slot, value):
		ref_el = None
		p = self.parent()
		if p and hasattr(p, "ref_element_combo"):
			ref_el = p.ref_element_combo.currentData()

		lines = self.placeholder_lines.get(placeholder, [])
		if not lines:
			return value

		# Use matching line if available, otherwise first one
		line = lines[slot] if slot < len(lines) else lines[-1]

		if ref_el:
			# Common variants
			line = line.replace('{element.name.replace(" ", "")}', ref_el.name.replace(" ", ""))
			line = line.replace("{element.name}", ref_el.name.replace(" ", ""))

			if "{element.width}" in line:
				line = line.replace("{element.width}", str(int(ref_el.pixmap().width())))
			if "{element.height}" in line:
				line = line.replace("{element.height}", str(int(ref_el.pixmap().height())))

			if "{element.offset_x}" in line:
				line = line.replace("{element.offset_x}", str(editor.scene_to_screen(ref_el.pos()).x()))
			if "{element.offset_y}" in line:
				line = line.replace("{element.offset_y}", str(editor.scene_to_screen(ref_el.pos()).y()))

			if "{element.parent_name}" in line:
				line = line.replace("{element.parent_name}", str(ref_el.parent_item.replace(" ", "")))

			if "{element.resource}" in line:
				line = line.replace("{element.resource}", str(ExtractResourceName(ref_el.pixmap_path)).replace(" ", ""))

			if "{element.pixmap_path}" in line:
				line = line.replace("{element.pixmap_path}", str("Resources/" + ref_el.pixmap_path.split("/")[-1]))

			if "{element.z}" in line:
				line = line.replace("{element.z}", str(ref_el.zValue()))

			if "{max_page}" in line:
				pages = getattr(p, "pages", [])
				line = line.replace("{max_page}", str(len(pages)))

			if "{element.page}" in line:
				line = line.replace("{element.page}", str(ref_el.page_index) if ref_el.page_index is not None else "-1")

			if "{element.group}" in line:
				line = line.replace("{element.group}", str(ref_el.group) if ref_el.group is not None else "-1")

			if "{element.toggles_amount}" in line:
				line = line.replace("{element.toggles_amount}", str(ref_el.toggles_amount))

		if value:
			line = re.sub(rf"\{{{re.escape(placeholder)}(?:\.x\d+)?\}}", value, line)

		return line

	def get_values(self):
		data = {}
		for placeholder in self.placeholder_order:
			vals = self.values.get(placeholder, [])
			for slot, val in enumerate(vals):
				if val:
					data.setdefault(placeholder, [])
					while len(data[placeholder]) <= slot:
						data[placeholder].append("")
					data[placeholder][slot] = val
		return data

	def refresh_all_results(self):
		self._updating = True
		self.blockSignals(True)

		for row in range(self.rowCount()):
			if row >= len(self._row_map):
				continue

			placeholder, slot = self._row_map[row]
			item = self.item(row, 2)

			raw_value = ""
			if item:
				raw_value = item.data(Qt.UserRole) or item.text()
				raw_value = "" if raw_value is None else str(raw_value)

			result = self.format_result(placeholder, slot, raw_value)
			self.setItem(row, 3, QTableWidgetItem(result))

		self.blockSignals(False)
		self._updating = False


class CodeElementDialog(QDialog):
	def __init__(self, *, types, displayed_elements, element=None, parent=None):
		super().__init__(parent)
		self.types = [t for t in types if t.get("kind") == "Code"]
		self.visual_types = [t for t in types if t.get("kind") == "Visual"]

		self.displayed_elements = displayed_elements
		self.element = element

		self.setWindowTitle("Code Element")
		self.resize(800, 1000)

		layout = QVBoxLayout(self)

		self.ref_element_combo = QComboBox()
		self.ref_element_combo.addItem("None")  # optional, no reference

		for el in self.displayed_elements:
			self.ref_element_combo.addItem(el.name, userData = el)

		self.name_edit = QLineEdit()
		self.type_combo = QComboBox()
		self.param_table = PlaceholderTable()
		self.param_table.set_sort_mode("slot")

		self.type_combo.currentTextChanged.connect(self.on_type_changed)

		for t in self.types:
			editor.allow_rebuild_ini = False
			self.type_combo.addItem(t["name"])

		layout.addWidget(QLabel("Name"))
		layout.addWidget(self.name_edit)

		layout.addWidget(QLabel("Type"))
		layout.addWidget(self.type_combo)

		layout.addWidget(QLabel("Reference Visual Element"))
		layout.addWidget(self.ref_element_combo)
		self.ref_element_combo.currentIndexChanged.connect(self.on_ref_element_changed)

		layout.addWidget(QLabel("Parameters"))
		layout.addWidget(self.param_table)

		# --- Quick Insert Panel for Visual Elements' CommandLists ---
		layout.addWidget(QLabel("Quick Insert: Visual CommandLists"))
		self.add_quick_insert_panel(layout)

		btns = QHBoxLayout()
		ok = QPushButton("OK")
		cancel = QPushButton("Cancel")
		btns.addStretch()
		btns.addWidget(ok)
		btns.addWidget(cancel)
		layout.addLayout(btns)

		ok.clicked.connect(self.accept)
		cancel.clicked.connect(self.reject)

		if self.element:
			self.load_element(self.element)

	def load_element(self, element: CodeElement):
		# Name
		self.name_edit.setText(element.name or "")

		# Type
		idx = self.type_combo.findText(element.type_name)
		if idx != -1:
			self.type_combo.setCurrentIndex(idx)

		# Reference visual element
		if getattr(element, "ref_visual", None):
			for i in range(self.ref_element_combo.count()):
				el = self.ref_element_combo.itemData(i)
				if el and el.name == element.ref_visual:
					self.ref_element_combo.setCurrentIndex(i)
					break

	def on_type_changed(self, type_name):
		type_def = next((t for t in self.types if t["name"] == type_name), None)
		if not type_def:
			return

		ini = type_def.get("ini_code", "")
		ini_lines = ini.splitlines()  # preserve all lines for placeholder replacement

		placeholders = self.extract_placeholders(ini)
		self.param_table.set_placeholders(
			placeholders,
			self.element.params if self.element else {},
			ini_lines = ini_lines  # <-- pass INI lines to the table
		)

		editor.rebuild_ini()

	def add_quick_insert_panel(self, parent_layout):
		scroll = QScrollArea()
		scroll.setWidgetResizable(True)

		content = QFrame()
		main_layout = QHBoxLayout(content)

		# --- Up: Variables + Resources ---
		left_layout = QVBoxLayout()
		vars_list = QListWidget()
		resources_list = QListWidget()

		# --- Down: CommandLists + CustomShaders ---
		right_layout = QVBoxLayout()
		cmds_list = QListWidget()
		shaders_list = QListWidget()

		left_layout.addWidget(QLabel("Variables"))
		left_layout.addWidget(vars_list)
		left_layout.addWidget(QLabel("Command lists"))
		left_layout.addWidget(cmds_list)

		right_layout.addWidget(QLabel("Resources"))
		right_layout.addWidget(resources_list)
		right_layout.addWidget(QLabel("Custom Shaders"))
		right_layout.addWidget(shaders_list)

		# Add both sides to main layout
		main_layout.addLayout(left_layout)
		main_layout.addLayout(right_layout)

		# Collect all variables, commands, resources, shaders
		all_vars = set()
		all_cmds = set()
		all_resources = set()
		all_shaders = set()

		# for el in self.displayed_elements:
		#     type_def = next((t for t in self.visual_types if t["name"] == el.type_name), None)
		#     if not type_def:
		#         continue
		#
		#     ini = type_def.get("ini_code", "")
		#     #all_vars.update(self.extract_variables(ini))
		#     all_cmds.update(self.extract_commandlists(ini, el.name))
		#
		#     # Placeholder logic for resources and shaders
		#     # You can replace these regexes with your actual parsing rules
		#     all_resources.update(
		#         re.findall(r"\[Resource\w*]?", ini.replace('{element.resource}', ExtractResourceName(el.pixmap_path))))

		ini_text = editor.ini_editor.toPlainText()

		all_vars.update(self.extract_variables(ini_text))
		all_cmds.update(re.findall(r"\[CommandList[a-zA-Z]\w*]?", ini_text))
		all_resources.update(re.findall(r"\[Resource[a-zA-Z]\w*]?", ini_text))
		all_shaders.update(re.findall(r"\[CustomShader[a-zA-Z]\w*]?", ini_text))

		# Populate lists
		for v in sorted(all_vars, key = lambda x: (x.startswith("$"), x)):
			if v.isdigit():  # draw
				label = f"{v} (Vertices Amount taken from Draw)"
			else:
				label = v
			vars_list.addItem(label)

		for r in sorted(all_resources):
			resources_list.addItem(r.replace('[', '').replace(']', ''))
		for c in sorted(all_cmds):
			cmds_list.addItem(c)
		for s in sorted(all_shaders):
			shaders_list.addItem(s)

		# Connect signals for quick insert
		for lst in (vars_list, resources_list, cmds_list, shaders_list):
			lst.itemClicked.connect(lambda i, l=lst: self.insert_param(i.text()))

		scroll.setWidget(content)
		parent_layout.addWidget(scroll)

	# @staticmethod
	# def extract_commandlists(type_ini_code, element_name):
	#    ini = type_ini_code.replace("{element.name}", element_name)
	#    return re.findall(r"^\[(CommandList[^\]\r\n]+)\]", ini, re.MULTILINE)

	@staticmethod
	def extract_variables(type_ini_code):
		globals_ = re.findall(r"global\s*(?:persist)?\s*(\$[a-zA-Z]\w+)", type_ini_code)
		draws = re.findall(r"draw\s*=\s*(\d+)\s*,\s*\d+", type_ini_code)

		return sorted(draws, key = int) + sorted(globals_)

	@staticmethod
	def extract_placeholders(type_ini_code):
		"""
        Parse placeholders and return dict placeholder -> max_count or None.
        If template declares {Name.xN} -> returns int(N).
        If only {Name} is present -> returns None (dynamic/unlimited).
        """
		results = {}
		for name, count in re.findall(r"\{([a-zA-Z_]\w*)(?:\.x(\d+))?\}", type_ini_code):
			if name in ['endfor', 'continue', 'skip', 'EndLoop', 'Loop:', 'max_page']:
				continue
			if count:
				results[name] = int(count)
			else:
				results[name] = None
		return results

	def get_element(self):
		ref = self.ref_element_combo.currentData()
		ref_name = ref.name if ref else None

		return CodeElement(
			self.name_edit.text(),
			self.type_combo.currentText(),
			self.param_table.get_values(),
			ref_visual = ref_name
		)

	def insert_param(self, text):
		table = self.param_table
		row = table.currentRow()

		if row < 0:
			return

		text = text.replace(" (Vertices Amount taken from Draw)", "")

		# find first empty slot
		for col in range(1, table.columnCount()):
			item = table.item(row, col)
			if item is None or not item.text().strip():
				table.setItem(row, col, QTableWidgetItem(text))
				table.setCurrentCell(row, col)
				return

		editor.rebuild_ini()

	def on_ref_element_changed(self, *_):
		"""Update all Result columns in the table when the reference element changes."""
		self.param_table.refresh_all_results()

		editor.rebuild_ini()


class AutoCompleteTextEdit(QTextEdit):
	def __init__(self, completions=None, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.completions = completions or []
		self.popup = QListWidget()

		# --- window flags: try to use ToolTip (nie aktywuje focus) w kompatybilny sposób ---
		try:
			# PyQt6 style
			self.popup.setWindowFlags(Qt.WindowType.ToolTip)
		except Exception:
			# PyQt5 / PySide fallback
			try:
				self.popup.setWindowFlags(Qt.ToolTip)
			except Exception:
				# leave default if not available
				pass

		# --- don't allow popup to grab focus ---
		try:
			self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
		except Exception:
			self.popup.setFocusPolicy(Qt.NoFocus)

		# --- try to set WA_ShowWithoutActivating (kompatybilnie) ---
		wa = getattr(Qt, "WA_ShowWithoutActivating", None)
		if wa is None:
			# Qt.WidgetAttribute.WA_ShowWithoutActivating on some bindings
			wa_container = getattr(Qt, "WidgetAttribute", None)
			if wa_container is not None:
				wa = getattr(wa_container, "WA_ShowWithoutActivating", None)
		if wa is not None:
			try:
				self.popup.setAttribute(wa, True)
			except Exception:
				pass

		self.popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
		self.popup.setSelectionMode(QListWidget.SingleSelection)
		self.popup.itemClicked.connect(self._on_item_clicked)
		self.popup.hide()

	# --- Helpers ---
	def _get_cursor_pos(self):
		r = self.cursorRect()
		return self.mapToGlobal(r.bottomLeft())

	def _find_last_open_brace_index(self, text, pos):
		# find last '{' or '${' before pos that is not closed
		i = pos - 1
		while i >= 0:
			if text[i] == '{':
				return i
			if text[i] == '$' and i - 1 >= 0 and text[i - 1] == '{':
				# handle weird case, prefer '{'
				return i - 1
			i -= 1
		return -1

	def _show_popup_with_prefix(self, prefix):
		self.popup.clear()
		prefix_lower = prefix.lower()
		# items: completions are strings like "{element.name}"
		matches = []
		for c in self.completions:
			inner = c.lstrip("{").lstrip("$").rstrip("}")
			if prefix == "" or inner.lower().startswith(prefix_lower):
				matches.append(c)
		if not matches:
			self.popup.hide()
			return
		for it in matches:
			self.popup.addItem(QListWidgetItem(it))
		self.popup.setCurrentRow(0)
		pos = self._get_cursor_pos()
		self.popup.move(pos)
		self.popup.show()

	def _insert_completion_text(self, text):
		# Replace from last '{' up to cursor with text
		doc_text = self.toPlainText()
		cur = self.textCursor()
		pos = cur.position()
		start = doc_text.rfind('{', 0, pos)
		if start == -1:
			# fallback: just insert at cursor
			cur.insertText(text)
			self.setTextCursor(cur)
			return
		# select range from start to pos and replace
		cur.setPosition(start)
		cur.setPosition(pos, QTextCursor.KeepAnchor)
		cur.removeSelectedText()
		cur.insertText(text)
		self.setTextCursor(cur)

	# --- Popup actions ---
	def _on_item_clicked(self, item):
		if not item:
			return
		self._insert_completion_text(item.text())
		self.popup.hide()

	def keyPressEvent(self, event):
		key = event.key()
		modifiers = event.modifiers()

		# --- Popup visible navigation ---
		if self.popup.isVisible():
			if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
				cur_row = self.popup.currentRow()
				if key == Qt.Key.Key_Up:
					cur_row = max(0, cur_row - 1)
				else:
					cur_row = min(self.popup.count() - 1, cur_row + 1)
				self.popup.setCurrentRow(cur_row)
				return  # consume
			elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
				item = self.popup.currentItem()
				if item:
					self._insert_completion_text(item.text())
				self.popup.hide()
				return  # consume
			elif key in [Qt.Key.Key_Escape, Qt.Key.Key_Space]:
				self.popup.hide()
				# allow QTextEdit to process escape normally
				super().keyPressEvent(event)
				return

		# Ctrl+Space always triggers popup
		if (modifiers & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_Space:
			doc_text = self.toPlainText()
			curpos = self.textCursor().position()
			start = self._find_last_open_brace_index(doc_text, curpos)
			prefix = ""
			# if start != -1 and start + 1 < curpos:
			#    prefix = doc_text[start + 1:curpos]
			#    if prefix.startswith('$'):
			#        prefix = prefix[1:]
			self._show_popup_with_prefix(prefix)
			return

		# normal key handling first
		super().keyPressEvent(event)

		# Show popup after typing certain characters
		txt = event.text()
		if txt == '{':
			self._show_popup_with_prefix("")
		elif txt and (txt.isalnum() or txt in "._$"):
			doc_text = self.toPlainText()
			curpos = self.textCursor().position()
			start = self._find_last_open_brace_index(doc_text, curpos)
			if start != -1:
				prefix = doc_text[start + 1:curpos]
				if prefix.startswith('$'):
					prefix = prefix[1:]
				self._show_popup_with_prefix(prefix)
		else:
			# other chars hide popup if no open brace
			doc_text = self.toPlainText()
			curpos = self.textCursor().position()
			if self._find_last_open_brace_index(doc_text, curpos) == -1:
				self.popup.hide()


# ================= TYPE EDITOR DIALOG =================

class TypeEditorDialog(QDialog):
	def __init__(self, types, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Edit Types")
		self.resize(editor.screen_width, editor.screen_height - 60)
		self.types = json.loads(json.dumps(types))
		self.current = -1

		# ==============================
		# Main Splitter: Left list | Right Panel
		# ==============================
		main_layout = QHBoxLayout(self)
		self.setLayout(main_layout)

		main_splitter = QSplitter(Qt.Horizontal)
		main_layout.addWidget(main_splitter)

		# Left: Template list
		self.list = QListWidget()
		main_splitter.addWidget(self.list)
		self.list.setMinimumWidth(150)
		self.list.setMaximumWidth(200)

		# Right: Editor + Quick Insert
		right_splitter = QSplitter(Qt.Horizontal)
		main_splitter.addWidget(right_splitter)

		# Left of right splitter: Editor Panel
		editor_widget = QFrame()
		editor_panel = QVBoxLayout(editor_widget)
		editor_widget.setLayout(editor_panel)
		right_splitter.addWidget(editor_widget)

		# Editor controls
		self.name_edit = QLineEdit()
		self.kind_combo = QComboBox()
		self.kind_combo.addItems(["Visual", "Code"])
		editor_panel.addWidget(QLabel("Type Kind"))
		editor_panel.addWidget(self.kind_combo)

		placeholders = [
			# element placeholders
			"{element.name}", "{element.offset_x}", "{element.offset_y}",
			"{element.width}", "{element.height}", "{element.resource}",
			"{element.pixmap_path}", "{element.z}", "{element.page}", "{element.group}",
			"{element.toggles_amount}",

			# display/code collections + loop vars
			"display_elements", "code_elements", "d_element", "c_element"
															  "{d_element.name}", "{d_element.offset_x}",
			"{d_element.offset_y}",
			"{d_element.width}", "{d_element.height}", "${d_element.name}", "${d_element.width}",
			"{c_element.name}", "{c_element.type_name}", "{c_element.ref_visual}", "{c_element.params}"

			# code element access patterns
																				   "{code_elem.Key}",
			"{code_elem.SomeKey}", "{code_elem['Key']}", "${code_elem.SomeKey}",

			# screen / meta
			"{screen.width}", "{screen.height}", "{max_page}", "{page}", "{group}",

			# command / constants patterns
			"[Constants]", "[Present]", "[CommandList", "[CustomShader", "[Key", "[TextureOverride",

			# handy variants
			"{parent_name}", "{parent.offset_x}", "{parent.offset_y}",

			# Logic
			"{if", "{not", "{for", "{in", "{endfor}", "{Loop:}", "{EndLoop}"
		]

		# create autocomplete textedit (keeps the variable name self.ini_edit)
		self.ini_edit = AutoCompleteTextEdit(completions = placeholders)
		self.ini_edit.setFont(QFont("Consolas", 10))
		fm = QFontMetrics(self.ini_edit.font())
		self.ini_edit.setTabStopDistance(fm.horizontalAdvance(' ') * 4)
		self.highlighter = IniHighlighter(self.ini_edit.document())
		editor_panel.addWidget(QLabel("Type Name"))
		editor_panel.addWidget(self.name_edit)
		editor_panel.addWidget(QLabel("Ini Code"))
		editor_panel.addWidget(self.ini_edit)

		row = QHBoxLayout()
		self.add_btn = QPushButton("Add")
		self.del_btn = QPushButton("Delete")
		self.reset_btn = QPushButton("Reset Default")
		row.addWidget(self.add_btn)
		row.addWidget(self.del_btn)
		row.addWidget(self.reset_btn)
		editor_panel.addLayout(row)

		buttons = QHBoxLayout()
		ok = QPushButton("OK")
		cancel = QPushButton("Cancel")
		buttons.addStretch()
		buttons.addWidget(ok)
		buttons.addWidget(cancel)
		editor_panel.addLayout(buttons)

		# Right of right splitter: Quick Insert Panel
		self.quick_fields = ["name", "width", "height", "offset_x", "offset_y", "z",
							 "parent_name", "screen.width", "screen.height", "max_page",
							 "page", "group", "toggles_amount", "key"]
		self.quick_insert_widget = self.create_quick_insert_panel()
		right_splitter.addWidget(self.quick_insert_widget)
		self.quick_insert_widget.setMaximumWidth(160)

		# Optional: set initial splitter sizes
		main_splitter.setSizes([200, 600])
		right_splitter.setSizes([400, 200])

		# Populate type list
		for t in self.types:
			self.list.addItem(t["name"])

		# ==============================
		# Signals
		# ==============================
		self.kind_combo.currentTextChanged.connect(self.change_kind)
		self.list.currentRowChanged.connect(self.select)
		self.name_edit.textChanged.connect(self.rename)
		self.ini_edit.textChanged.connect(self.edit_ini)
		self.add_btn.clicked.connect(self.add)
		self.del_btn.clicked.connect(self.delete)
		self.reset_btn.clicked.connect(self.reset)
		ok.clicked.connect(self.accept)
		cancel.clicked.connect(self.reject)

		if self.types:
			self.list.setCurrentRow(0)

	# ==============================
	# Quick Insert Panel
	# ==============================
	def create_quick_insert_panel(self):
		scroll = QScrollArea()
		scroll.setWidgetResizable(True)
		content = QFrame()
		layout = QVBoxLayout(content)
		layout.addWidget(QLabel("Quick Insert:"))

		for field in self.quick_fields:
			btn = QPushButton(f"{{element.{field}}}" if field not in ['max_page', 'key'] else f"{{{field}}}")
			btn.clicked.connect(lambda checked, f=field: self.insert_placeholder(f))
			btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
			layout.addWidget(btn)

		layout.addStretch()
		scroll.setWidget(content)
		return scroll

	def insert_placeholder(self, field_name):
		cursor = self.ini_edit.textCursor()
		cursor.insertText(f"{{element.{field_name}}}" if field_name not in ['max_page', 'key'] else f"{{{field_name}}}")
		self.ini_edit.setTextCursor(cursor)

	# ==============================
	# Editor Logic
	# ==============================
	def change_kind(self, text):
		if self.current < 0: return
		self.types[self.current]["kind"] = text

	def select(self, i):
		self.current = i

		if i < 0 or i > len(self.types):
			return

		t = self.types[i]
		self.name_edit.setText(t["name"])
		self.ini_edit.setPlainText(t["ini_code"])
		self.del_btn.setEnabled(not t.get("is_default", False))
		self.reset_btn.setEnabled(t.get("is_default", False))
		self.kind_combo.setCurrentText(t.get("kind", "Visual"))

	def rename(self, text):
		if self.current < 0: return
		self.types[self.current]["name"] = text
		self.list.item(self.current).setText(text)

	def edit_ini(self):
		if self.current < 0: return
		self.types[self.current]["ini_code"] = self.ini_edit.toPlainText()

	def add(self):
		t = {"name": "NewType", "ini_code": "", "is_default": False, "kind": "Visual"}
		self.types.append(t)
		self.list.addItem(t["name"])
		self.list.setCurrentRow(len(self.types) - 1)

	def delete(self):
		if self.current < 0: return
		if self.types[self.current].get("is_default"): return
		self.types.pop(self.current)
		self.list.takeItem(self.current)
		self.current = -1

	def reset(self):
		if not os.path.isfile('Saves/Defaults.json'):
			defaults = {}
		else:
			with open('Saves/Defaults.json', "r", encoding = "utf-8") as f:
				defaults = json.load(f)

		t = self.types[self.current]
		t["ini_code"] = defaults.get(t["name"], "")
		self.ini_edit.setPlainText(t["ini_code"])

	def get_types(self):
		return self.types


class DisplayedItem(QGraphicsPixmapItem):
	def __init__(self, pixmap, og_pixmap, pixmap_path="", name="Element", template_name=None, type_name='Visual'):
		super().__init__(pixmap)
		self.name = name
		self.type_name = type_name
		self.always_visible = True
		self.page_index = None
		self.group = None  # Index
		self.toggles_amount = 1
		# source_pixmap: pristine original image (never modified)
		self.original_pixmap = og_pixmap
		self.pixmap_path = pixmap_path

		self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
		self.tint_color = QColor(255, 255, 255)
		self.tint_percent = 0
		self.parent_item = None
		self.parent_offset_x = 0
		self.parent_offset_y = 0
		self.children = []
		self.template_name = template_name  # prefab/template inheritance

	def to_dict(self):
		return {
			"name": self.name,
			"type_name": self.type_name,
			"always_visible": self.always_visible,
			"page_index": self.page_index,
			"group": self.group,
			"z": self.zValue(),
			"pixmap_path": self.pixmap_path,
			"toggles_amount": self.toggles_amount,
			"pos": [int(self.pos().x()), int(self.pos().y())],
			"size": [self.pixmap().width(), self.pixmap().height()],
			"tint_color": [self.tint_color.red(), self.tint_color.green(), self.tint_color.blue()],
			"tint_percent": self.tint_percent,
			"parent_name": self.parent_item if self.parent_item else None,
			"parent_offset": [self.parent_offset_x, self.parent_offset_y],
			"children_names": [child.name for child in self.children],
			"template_name": self.template_name,
		}

	def apply_tint(self):
		src = self.original_pixmap

		if self.pixmap_path == '':
			src.fill(QColor(255, 255, 255, 255))

		if not src or src.isNull():
			return

		# Scale to current displayed size
		width = self.pixmap().width() if self.pixmap() else src.width()
		height = self.pixmap().height() if self.pixmap() else src.height()
		result = safe_scaled(src, width, height)

		if self.tint_percent == 0:
			self.setPixmap(result)
			return

		painter = QPainter(result)

		# Tint overlay
		painter.setCompositionMode(QPainter.CompositionMode_Multiply)
		painter.setOpacity(self.tint_percent / 100)
		painter.fillRect(result.rect(), self.tint_color)

		painter.end()
		self.setPixmap(result)

	# Color Picker
	def mousePressEvent(self, event):
		if event.button() == Qt.MouseButton.MiddleButton:
			color = QColorDialog.getColor(initial = self.tint_color)
			if color.isValid():
				self.tint_color = color
				self.apply_tint()
			event.accept()
			return

		super().mousePressEvent(event)

	def mouseDoubleClickEvent(self, event):
		if event.button() == Qt.MouseButton.LeftButton:
			file_name, _ = QFileDialog.getOpenFileName(
				None,
				"Select Image",
				"",
				"Images (*.png *.jpg *.jpeg *.bmp *.webp, *.dds)"
			)

			if file_name:
				pixmap = load_pixmap_any(file_name, editor.pixmap_cache)

				if not pixmap.isNull():
					self.original_pixmap = pixmap.copy()
					self.pixmap_path = file_name
					pixmap_scaled = safe_scaled(self.original_pixmap, int(editor.settings_width_entry.text()),
												int(editor.settings_height_entry.text()))
					self.setPixmap(pixmap_scaled)
					self.apply_tint()  # reapply tint if any
					# editor.settings_width_entry.setText(str(pixmap.width()))
					# editor.settings_height_entry.setText(str(pixmap.height()))

			event.accept()
			return

		super().mouseDoubleClickEvent(event)

	def itemChange(self, change, value):
		"""
        Safe itemChange handler:
        - Move children on ItemPositionChange (before position actually changes)
        - Update inspector fields on ItemPositionHasChanged (after position changed) with signals blocked
        - Keep children stored as list, not generator
        - Sync selection to outliner safely
        """

		# ---------- BEFORE position actually changes: move children by delta ----------
		if change == QGraphicsItem.ItemPositionChange:
			# value is the new position (QPointF)

			try:
				if editor.loading_data:
					return super().itemChange(change, value)

				new_pos = value
				# compute children list (static snapshot)
				children = [it for it in (getattr(editor, "display_items", []) if editor else []) if
							it.parent_item == self.name]

				if children:
					# delta from current pos
					delta = new_pos - self.pos()
					for child in children:
						# move child by same delta (no GUI updates here)
						child.setPos(child.pos() + delta)
			except Exception:
				pass

			# let base class handle whatever it needs
			return super().itemChange(change, value)

		# ---------- AFTER position changed: update inspector fields & parent offsets ----------
		if change == QGraphicsItem.ItemPositionHasChanged:
			# Update inspector fields (only if this is the active item)
			if editor and self == getattr(editor, "active_item", None):
				try:
					# block programmatic reactions
					editor._ui_changing = True
					editor.settings_pos_x_entry.blockSignals(True)
					editor.settings_pos_y_entry.blockSignals(True)

					# convert scene pos to screen coords and write to entries
					screen_point = editor.scene_to_screen(self.pos())
					editor.settings_pos_x_entry.setText(str(int(screen_point.x())))
					editor.settings_pos_y_entry.setText(str(int(screen_point.y())))
				except Exception:
					pass
				finally:
					editor.settings_pos_x_entry.blockSignals(False)
					editor.settings_pos_y_entry.blockSignals(False)
					editor._ui_changing = False

			# Update parent offsets after pos change
			if getattr(self, "parent_item", None):
				try:
					parent = next((elem for elem in (getattr(editor, "display_items", []) if editor else []) if
								   elem.name == self.parent_item), None)
					if parent:
						child_screen = editor.scene_to_screen(self.pos())
						parent_screen = editor.scene_to_screen(parent.pos())
						self.parent_offset_x = child_screen.x() - parent_screen.x()
						self.parent_offset_y = child_screen.y() - parent_screen.y()
						if self.isSelected() and editor:
							# block signals for offset entries as well
							try:
								editor._ui_changing = True
								editor.parent_offset_x_entry.blockSignals(True)
								editor.parent_offset_y_entry.blockSignals(True)
								editor.parent_offset_x_entry.setText(str(int(self.parent_offset_x)))
								editor.parent_offset_y_entry.setText(str(int(self.parent_offset_y)))
							finally:
								editor.parent_offset_x_entry.blockSignals(False)
								editor.parent_offset_y_entry.blockSignals(False)
								editor._ui_changing = False
				except Exception:
					pass

			return super().itemChange(change, value)

		# ---------- Selection sync with outliner ----------
		# If outliner widget click flag is set, it came from outliner -> skip to avoid loop
		if editor and getattr(editor, "outliner_widget_clicked", False):
			editor.outliner_widget_clicked = False
		elif change == QGraphicsItem.ItemSelectedHasChanged:
			# value might be a QVariant/bool - convert to bool
			try:
				sel = bool(value)
			except Exception:
				sel = True if value else False

			# find the corresponding outliner item and set its selection
			if editor:
				try:
					for it in editor.iter_outliner_items():
						# In your earlier code you stored element at role 1; adjust if needed.
						el = it.data(1, Qt.UserRole)
						if el is self:
							it.setSelected(sel)
							break
				except Exception:
					pass

		if change == QGraphicsItem.ItemSelectedChange:
			# value indicates the new selection state (True/False)
			try:
				editor.last_selected = self if value else None
			except Exception:
				pass

		return super().itemChange(change, value)


class Template:
	def __init__(self, name, type_name, pixmap, width=None, height=None, path=None, tint_percent=0, extends=None):
		self.name = name
		self.type_name = type_name
		self.pixmap = pixmap
		self.width = width
		self.height = height
		self.path = path
		self.tint_percent = tint_percent
		self.extends = extends  # support simple inheritance key

	def to_dict(self):
		return {
			"name": self.name,
			"type": self.type_name,
			"width": self.width,
			"height": self.height,
			"path": self.path,
			"tint_percent": self.tint_percent,
			"extends": self.extends,
		}

	@staticmethod
	def from_dict(d, pixmap):
		return Template(
			d["name"], d.get("type", "Visual"), pixmap, d.get("width"), d.get("height"), d.get("path"),
			d.get("tint_percent", 0), d.get("extends")
		)


class ResizableFrame(QWidget):
	BORDER = 8  # pixels for resize hit area

	def __init__(self, parent=None, child_widget: QWidget | None = None):
		super().__init__(parent)
		self.setMouseTracking(True)

		# child widget inside frame (editor)
		self.child = child_widget
		if self.child:
			self.child.setParent(self)
			self.child.setGeometry(0, 0, self.width(), self.height())

		# state
		self._press_pos = None  # QPoint (global)
		self._press_rect = None  # QRect (frame geometry at press)
		self._mode = None  # "move" or "resize" or None
		self._dir = None  # resize direction string
		self.setMinimumSize(120, 40)

	def _is_over_child_widget(self, local_pos: QPoint) -> bool:
		w = self.childAt(local_pos)
		return w is not None and w is not self

	def set_child(self, w: QWidget):
		self.child = w
		w.setParent(self)
		w.setGeometry(0, 0, self.width(), self.height())

	def resizeEvent(self, ev):
		# ensure child always fills
		if self.child:
			self.child.setGeometry(0, 0, self.width(), self.height())
		super().resizeEvent(ev)

	# ---------- helpers ----------
	def _in_border(self, pos: QPoint) -> bool:
		r = self.rect()
		x, y, w, h = pos.x(), pos.y(), r.width(), r.height()
		bw = self.BORDER
		return x <= bw or x >= w - bw or y <= bw or y >= h - bw

	def _cursor_dir(self, pos: QPoint):
		r = self.rect()
		x, y, w, h = pos.x(), pos.y(), r.width(), r.height()
		bw = self.BORDER
		left = x <= bw
		right = x >= w - bw
		top = y <= bw
		bottom = y >= h - bw
		if top and left: return "topleft"
		if top and right: return "topright"
		if bottom and left: return "bottomleft"
		if bottom and right: return "bottomright"
		if left: return "left"
		if right: return "right"
		if top: return "top"
		if bottom: return "bottom"
		return None

	# ---------- mouse events (Qt6-safe) ----------
	def mousePressEvent(self, event):
		if event.button() != Qt.MouseButton.LeftButton:
			return super().mousePressEvent(event)

		local_pos = event.position().toPoint()
		global_pos = event.globalPosition().toPoint()

		if self._in_border(local_pos):
			# start resizing
			self._mode = "resize"
			self._dir = self._cursor_dir(local_pos)
		else:
			# start moving
			self._mode = "move"
			self._dir = None

		self._press_pos = global_pos
		self._press_rect = QRect(self.geometry())
		# inform main window not to auto-move while user is manipulating
		main = self.window()
		if main is not None:
			setattr(main, "ini_frame_user_manipulating", True)

		event.accept()

	def mouseMoveEvent(self, event):
		local_pos = event.position().toPoint()
		if self._mode == "resize" and self._press_pos and self._press_rect:
			delta = event.globalPosition().toPoint() - self._press_pos
			geom = QRect(self._press_rect)

			# horizontal
			if "left" in (self._dir or ""):
				new_left = geom.left() + delta.x()
				new_width = geom.right() - new_left + 1
				if new_width >= self.minimumWidth():
					geom.setLeft(new_left)
			elif "right" in (self._dir or ""):
				geom.setRight(geom.right() + delta.x())

			# vertical
			if "top" in (self._dir or ""):
				new_top = geom.top() + delta.y()
				new_height = geom.bottom() - new_top + 1
				if new_height >= self.minimumHeight():
					geom.setTop(new_top)
			elif "bottom" in (self._dir or ""):
				geom.setBottom(geom.bottom() + delta.y())

			# enforce minimum
			if geom.width() < self.minimumWidth():
				geom.setWidth(self.minimumWidth())
			if geom.height() < self.minimumHeight():
				geom.setHeight(self.minimumHeight())

			self.setGeometry(geom)
			event.accept()
			return

		if self._mode == "move" and self._press_pos and self._press_rect:
			delta = event.globalPosition().toPoint() - self._press_pos
			new_tl = self._press_rect.topLeft() + delta
			self.move(new_tl)
			event.accept()
			return

		# not manipulating — update cursor depending on hover
		if self._is_over_child_widget(local_pos):
			self.setCursor(Qt.CursorShape.ArrowCursor)
			return super().mouseMoveEvent(event)

		direction = self._cursor_dir(local_pos)

		if direction in ("topleft", "bottomright"):
			self.setCursor(Qt.CursorShape.SizeFDiagCursor)
		elif direction in ("topright", "bottomleft"):
			self.setCursor(Qt.CursorShape.SizeBDiagCursor)
		elif direction in ("left", "right"):
			self.setCursor(Qt.CursorShape.SizeHorCursor)
		elif direction in ("top", "bottom"):
			self.setCursor(Qt.CursorShape.SizeVerCursor)
		else:
			self.setCursor(Qt.CursorShape.ArrowCursor)
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):
		self._mode = None
		self._dir = None
		self._press_pos = None
		self._press_rect = None
		main = self.window()
		if main is not None:
			setattr(main, "ini_frame_user_manipulating", False)
		event.accept()


def expand_visual_ini(el, ini, debug=False):
	lines = ini.splitlines()

	def apply_visual_and_globals(line: str) -> str:
		"""Szybkie zastąpienia prostych pól z visual/editor (legacy helper)."""
		visual = el  # alias
		# visual-specific replacements
		if visual:
			try:
				line = line.replace("{element.name}", visual.name.replace(' ', ''))
			except Exception:
				pass

			try:
				# pozycja (x,y) — metoda lub właściwość
				x_val = None
				y_val = None
				if hasattr(visual, "x") and callable(getattr(visual, "x")):
					x_val = visual.x()
				elif hasattr(visual, "x"):
					x_val = getattr(visual, "x")
				if hasattr(visual, "y") and callable(getattr(visual, "y")):
					y_val = visual.y()
				elif hasattr(visual, "y"):
					y_val = getattr(visual, "y")
				if x_val is not None:
					line = line.replace("{element.offset_x}", str(editor.scene_to_screen(visual.pos()).x()))
				if y_val is not None:
					line = line.replace("{element.offset_y}", str(editor.scene_to_screen(visual.pos()).y()))

			except Exception:
				pass

			try:
				# pixmap() może być QPixmap; zabezpieczamy
				w = None
				h = None
				if hasattr(visual, "pixmap") and callable(getattr(visual, "pixmap")):
					pm = visual.pixmap()
					if pm is not None:
						if hasattr(pm, "width") and callable(pm.width):
							w = pm.width()
						elif hasattr(pm, "width"):
							w = pm.width
						if hasattr(pm, "height") and callable(pm.height):
							h = pm.height()
						elif hasattr(pm, "height"):
							h = pm.height
				# fallback: jeżeli pixmap() nie istnieje, spróbuj pixmap_path lub width/height atrybutów
				if w is None:
					try:
						# jeżeli masz zapis width/height w visual bez pixmap()
						if hasattr(visual, "width"):
							w = int(getattr(visual, "width"))
					except Exception:
						w = None
				if h is None:
					try:
						if hasattr(visual, "height"):
							h = int(getattr(visual, "height"))
					except Exception:
						h = None

				if w is not None:
					line = line.replace("{element.width}", str(int(w)))
				if h is not None:
					line = line.replace("{element.height}", str(int(h)))
			except Exception:
				pass

			try:
				if hasattr(visual, "pixmap_path"):
					rp = visual.pixmap_path
					if rp:
						line = line.replace("{element.resource}", ExtractResourceName(rp).replace(' ', ''))
						line = line.replace("{element.pixmap_path}", 'Resources/' + rp.split('/')[-1])
			except Exception:
				pass

			try:
				# z-index / zValue
				z = None
				if hasattr(visual, "zValue") and callable(getattr(visual, "zValue")):
					z = visual.zValue()
				elif hasattr(visual, "z"):
					z = getattr(visual, "z")
				if z is not None:
					line = line.replace("{element.z}", str(int(z)))
			except Exception:
				pass

			try:
				# page index / group
				page_idx = None
				if hasattr(visual, "page_index"):
					page_idx = getattr(visual, "page_index")
				elif hasattr(visual, "page"):
					page_idx = getattr(visual, "page")
				line = line.replace("{element.page}", str(page_idx) if page_idx is not None else '-1')
			except Exception:
				line = line.replace("{element.page}", '-1')

			try:
				group = getattr(visual, "group", None)
				line = line.replace("{element.group}", str(group) if group is not None else '-1')
			except Exception:
				line = line.replace("{element.group}", '-1')

			try:
				toggles = getattr(visual, "toggles_amount", None)
				if toggles is None:
					toggles = getattr(visual, "toggles", None)
				if toggles is None:
					toggles = 1
				line = line.replace("{element.toggles_amount}", str(int(toggles)))
			except Exception:
				line = line.replace("{element.toggles_amount}", "1")

		# editor/global replacements
		try:
			line = line.replace("{screen.width}", str(int(editor.screen_width)))
		except Exception:
			pass

		try:
			line = line.replace("{screen.height}", str(int(editor.screen_height)))
		except Exception:
			pass

		try:
			line = line.replace("{max_page}", str(len(editor.pages)))
		except Exception:
			# fallback: 1
			line = line.replace("{max_page}", "1")

		return line

	for idx, line in enumerate(lines):
		try:
			lines[idx] = apply_visual_and_globals(line)

		except Exception as e:
			if debug:
				print(f"[VISUAL][{line}] apply_visual_and_globals error: {e}")

	# najpierw for i if bloki
	lines = expand_for_blocks(
		lines,
		None,
		el,
		editor.display_items,
		getattr(editor, "code_elements", [])
	)

	lines = expand_if_blocks(
		lines,
		code = None,
		all_code = editor.code_elements,
		visual = el,
		all_visuals = editor.display_items,
		local_vars = None,
		debug = False
	)

	out_lines = []

	# { ... } matcher
	placeholder_re = re.compile(r"\{([^}]+)\}")

	def _curly_sub(m):
		token = m.group(1).strip()

		# 1. normal resolve
		try:
			val = _resolve_path_value(
				token,
				local_vars = None,
				visual = el,
				code = None,
				all_visuals = editor.display_items,
				all_code = editor.code_elements,
				idx = None
			)
		except Exception as e:
			if debug:
				print(f"[VISUAL] resolve fail {{{token}}}: {e}")
			return m.group(0)

		if val is None:
			return m.group(0)

		if isinstance(val, (list, tuple)):
			if not val:
				return m.group(0)
			val = val[0]

		val = str(val)

		if debug:
			print(f"[VISUAL] {{{token}}} -> {val}")

		return val

	for ln, raw in enumerate(lines):
		line = raw

		# apply quick visual/global replacements BEFORE placeholder regex resolution

		if debug:
			print(f"[VISUAL][{ln}] RAW: {raw}")

		# inline ifs
		try:
			line = _process_conditionals_in_line(
				line,
				code = None,
				all_code = editor.code_elements,
				idx = None,
				all_visuals = editor.display_items,
				local_vars = None,
				visual = el
			)
		except Exception as e:
			if debug:
				print(f"[VISUAL][{ln}] inline-if error: {e}")

		# placeholder replace (resolves more complex paths like element.some.prop or code lookups)

		line = placeholder_re.sub(_curly_sub, line)

		if debug:
			print(f"[VISUAL][{ln}] OUT: {line}")
			print("-" * 50)

		out_lines.append(line)

	full = "\n".join(out_lines)

	return full


def merge_generated_block(original, generated):
	block = f"{GEN_START}\n{generated}\n{GEN_END}"

	if GEN_START in original and GEN_END in original:
		return re.sub(
			rf"{re.escape(GEN_START)}.*?{re.escape(GEN_END)}",
			block,
			original,
			flags = re.S
		)

	return original.rstrip() + "\n\n" + block + "\n"


# ============== Undo / Redo Commands ==============
class PropertyCommand(QUndoCommand):
	def __init__(self, target, prop_name, old_value, new_value, text=None):
		super().__init__(text or f"Change {prop_name}")
		self.target = target
		self.prop_name = prop_name
		self.old = old_value
		self.new = new_value

	def _get_editor(self):
		return getattr(self.target, "editor", None)

	def undo(self):
		editor = self._get_editor()
		if editor:
			editor._ui_changing = True

		try:
			setattr(self.target, self.prop_name, self.old)
		except Exception:
			try:
				self.target[self.prop_name] = self.old
			except Exception:
				pass

		if editor:
			editor._ui_changing = False

	def redo(self):
		editor = self._get_editor()
		if editor:
			editor._ui_changing = True

		try:
			setattr(self.target, self.prop_name, self.new)
		except Exception:
			try:
				self.target[self.prop_name] = self.new
			except Exception:
				pass

		if editor:
			editor._ui_changing = False

	def id(self):
		try:
			h = hash((id(self.target), self.prop_name))
			return int(h & 0x7FFFFFFF)
		except Exception:
			return 0

	def mergeWith(self, other):
		if not isinstance(other, PropertyCommand):
			return False
		if other.target is not self.target or other.prop_name != self.prop_name:
			return False
		self.new = other.new
		return True


class TransformCommand(QUndoCommand):
	def __init__(self, item, old_pos, old_size, new_pos, new_size, text="Transform"):
		super().__init__(text)
		self.item = item

		def norm_pos(p):
			try:
				return (float(p.x()), float(p.y()))
			except Exception:
				try:
					return (float(p[0]), float(p[1]))
				except Exception:
					return (0.0, 0.0)

		def norm_size(s):
			try:
				return (int(s[0]), int(s[1]))
			except Exception:
				return (0, 0)

		self.old_pos = norm_pos(old_pos)
		self.old_size = norm_size(old_size)
		self.new_pos = norm_pos(new_pos)
		self.new_size = norm_size(new_size)

	def _get_editor(self):
		return getattr(self.item, "editor", None)

	def apply(self, pos, size):
		try:
			x, y = float(pos[0]), float(pos[1])
			try:
				self.item.setPos(QPointF(x, y))
			except Exception:
				self.item.setPos(x, y)
		except Exception:
			pass

		try:
			if hasattr(self.item, "original_pixmap"):
				w = max(1, int(size[0]))
				h = max(1, int(size[1]))
				pix = safe_scaled(self.item.original_pixmap, w, h)
				self.item.setPixmap(pix)

				if hasattr(self.item, "apply_tint"):
					self.item.apply_tint()
		except Exception:
			pass

	def undo(self):
		editor = self._get_editor()
		if editor:
			editor._ui_changing = True

		self.apply(self.old_pos, self.old_size)

		if editor:
			editor._ui_changing = False

	def redo(self):
		editor = self._get_editor()
		if editor:
			editor._ui_changing = True

		self.apply(self.new_pos, self.new_size)

		if editor:
			editor._ui_changing = False


class AddRemoveCommand(QUndoCommand):
	"""Add or remove an item from a scene/list."""

	def __init__(self, editor, item, adding=True, text=None):
		super().__init__(text or ("Add Item" if adding else "Remove Item"))
		self.editor = editor
		self.item = item
		self.adding = adding

	def undo(self):
		if self.adding:
			if self.item.scene():
				self.item.scene().removeItem(self.item)
			if self.item in self.editor.display_items:
				try:
					self.editor.display_items.remove(self.item)
				except Exception:
					pass
		else:
			if not self.item.scene():
				self.editor.scene.addItem(self.item)
			if self.item not in self.editor.display_items:
				self.editor.display_items.append(self.item)
		try:
			self.editor.rebuild_outliner()
			self.editor.rebuild_ini()
		except Exception:
			pass

	def redo(self):
		if self.adding:
			if not self.item.scene():
				self.editor.scene.addItem(self.item)
			if self.item not in self.editor.display_items:
				self.editor.display_items.append(self.item)
		else:
			if self.item.scene():
				self.item.scene().removeItem(self.item)
			if self.item in self.editor.display_items:
				try:
					self.editor.display_items.remove(self.item)
				except Exception:
					pass
		try:
			self.editor.rebuild_outliner()
			self.editor.rebuild_ini()
		except Exception:
			pass


class BatchCommand(QUndoCommand):
	"""Container for several commands executed together."""

	def __init__(self, text="Batch"):
		super().__init__(text)
		self.cmds = []

	def add(self, cmd):
		self.cmds.append(cmd)

	def undo(self):
		for c in reversed(self.cmds):
			c.undo()

	def redo(self):
		for c in self.cmds:
			c.redo()


# ===================================================

class OutlinerTree(QTreeWidget):
	def __init__(self, display_items, editor, rebuild_callback=None):
		super().__init__()
		self.display_items = display_items
		self.editor = editor
		self.rebuild_callback = rebuild_callback

		self.setHeaderHidden(True)
		self.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.setDragEnabled(True)
		self.setAcceptDrops(True)
		self.setDragDropMode(QAbstractItemView.InternalMove)
		self.setDefaultDropAction(Qt.MoveAction)
		self.setIndentation(12)
		self.setContextMenuPolicy(Qt.CustomContextMenu)
		self.customContextMenuRequested.connect(self.on_context_menu)

	def debug_z_tree(self, label="Z-DEBUG"):
		print("\n" + "=" * 40)
		print(label)
		print("=" * 40)

		seen_z = {}

		def walk(item, depth=0):
			indent = "  " * depth
			role = item.data(0, Qt.UserRole)

			if role == "ELEMENT":
				el = item.data(1, Qt.UserRole)
				if el:
					z = el.zValue()
					print(f"{indent}[EL] {el.name} | z={z}")

					if z in seen_z:
						print(f"  ⚠️ DUPLICATE Z: {z} also used by {seen_z[z]}")
					else:
						seen_z[z] = el.name
			else:
				print(f"{indent}[{role}] {item.text(0)}")

			for i in range(item.childCount()):
				walk(item.child(i), depth + 1)

		for i in range(self.topLevelItemCount()):
			walk(self.topLevelItem(i))

		if seen_z:
			zs = sorted(seen_z.keys())
			print("\nZ RANGE:", zs[0], "->", zs[-1])
			print("COUNT:", len(zs))

			# check gaps
			expected = list(range(int(zs[0]), int(zs[-1]) + 1))
			missing = set(expected) - set(zs)
			if missing:
				print("⚠️ MISSING Z VALUES:", sorted(missing))

		print("=" * 40 + "\n")

	# ------------------------- Drop Event -------------------------
	def dropEvent(self, event):
		"""
        Minimal pre-validation, allow Qt to perform the drop, then always
        synchronise the model from the tree using a deterministic routine.
        """
		# defensive pos getter
		try:
			pos = event.position().toPoint()
		except Exception:
			pos = event.pos()

		selected = self.selectedItems()
		source_item = selected[0] if selected else self.currentItem()
		if not source_item:
			event.ignore()
			return

		source_type = source_item.data(0, Qt.UserRole)
		target_item = self.itemAt(pos)
		drop_pos = self.dropIndicatorPosition()  # AboveItem, BelowItem, OnItem, OnViewport

		# find roots (assume layout: 0 = ROOT_ALWAYS, 1 = ROOT_PAGES)
		root_always = self.topLevelItem(0) if self.topLevelItemCount() > 0 else None
		root_pages = self.topLevelItem(1) if self.topLevelItemCount() > 1 else None

		# ----------------------------
		# PRE-DROP VALIDATION
		# ----------------------------

		# minimal sanity check: ensure we are dragging a known role
		source_type = source_item.data(0, Qt.UserRole)
		if source_type not in ("PAGE", "GROUP", "ELEMENT"):
			# let Qt ignore unknown drags
			event.ignore()
			return

		# PAGE: only reorder inside root_pages and only as Above/Below (not OnItem)
		if source_type == "PAGE":
			if root_pages is None:
				event.ignore()
				return

			# If user tries to drop ON a page (which leads to nesting) — reject
			if drop_pos == QAbstractItemView.OnItem:
				event.ignore()
				return

			# allow only Above/Below a page that is a direct child of root_pages,
			# or dropping onto the Pages root (OnViewport/OnItem over root handled separately)
			if drop_pos in (QAbstractItemView.AboveItem, QAbstractItemView.BelowItem):
				if not target_item or target_item.parent() != root_pages:
					event.ignore()
					return
			else:
				# other positions (OnViewport or unknown) -> reject
				event.ignore()
				return

		# GROUP: allow only dropping onto a PAGE, onto ROOT_ALWAYS, or viewport (map to ROOT_ALWAYS)
		elif source_type == "GROUP":
			# Group MUST be dropped onto PAGE or ROOT_ALWAYS only
			if not target_item:
				event.ignore()
				return

			if self.dropIndicatorPosition() != QAbstractItemView.OnItem:
				event.ignore()
				return

			target_type = target_item.data(0, Qt.UserRole)

			# forbid dropping onto Pages root or anything else
			if target_type not in ("PAGE", "ROOT_ALWAYS"):
				event.ignore()
				return
		elif source_type == 'ELEMENT':
			if target_item:
				target_type = target_item.data(0, Qt.UserRole)
				parent_of_target = target_item.parent()

				# forbid dropping onto Pages root or anything else
				if target_type == "ROOT_PAGES":
					event.ignore()
					return
				if drop_pos in (QAbstractItemView.AboveItem, QAbstractItemView.BelowItem):
					if parent_of_target and parent_of_target.data(0, Qt.UserRole) == "ROOT_PAGES":
						# user tried to drop an element at the same level as pages -> reject
						event.ignore()
						return

		# let Qt perform the actual tree mutation
		super().dropEvent(event)

		# After Qt has mutated the tree, perform a full authoritative sync:
		try:
			self._sync_all_from_tree()
		except Exception as e:
			# make sure we never leave model inconsistent; at least update z order
			try:
				root_pages = self._find_top("ROOT_PAGES")
				if root_pages:
					self.editor.pages = [root_pages.child(i).text(0) for i in range(root_pages.childCount())]
			except Exception:
				pass
			try:
				self._update_all_elements()
			except Exception:
				pass
			print("[WARN] dropEvent sync failed:", e)

		# update UI
		if self.rebuild_callback:
			self.rebuild_callback()

		# self.debug_z_tree("AFTER DROP")
		editor.rebuild_ini()

	def _update_all_elements(self):
		"""Walk tree and update z-values for elements (keeps existing el.group/int values)."""
		# zValue
		z_index = 0
		for root_idx in range(self.topLevelItemCount()):
			root = self.topLevelItem(root_idx)
			z_index = self._update_z_recursive(root, z_index)

	def _update_z_recursive(self, tree_item, start_index):
		node_type = tree_item.data(0, Qt.UserRole)
		if node_type == "ELEMENT":
			el = tree_item.data(1, Qt.UserRole)
			if el:
				el.setZValue(start_index)
				start_index += 1
		for i in range(tree_item.childCount()):
			start_index = self._update_z_recursive(tree_item.child(i), start_index)
		return start_index

	def _find_top(self, role_name):
		for i in range(self.topLevelItemCount()):
			it = self.topLevelItem(i)
			if it.data(0, Qt.UserRole) == role_name:
				return it
		return None

	def _sync_all_from_tree(self):
		"""
        Rebuild editor.pages, editor.groups, and element fields from the current
        tree structure. Deterministic and authoritative — tree is source of truth.
        """
		# find roots
		root_always = self._find_top("ROOT_ALWAYS")
		root_pages = self._find_top("ROOT_PAGES")

		# 1) Rebuild pages list from tree (order matters)
		new_pages = []
		if root_pages:
			for i in range(root_pages.childCount()):
				new_pages.append(root_pages.child(i).text(0))
		# Replace editor.pages (keep exactly what tree shows)
		self.editor.pages = new_pages

		# 2) Rebuild groups mapping: "ROOT_ALWAYS" -> list, and per-page index -> list
		new_groups = {}
		# Always root groups
		if root_always:
			new_groups["ROOT_ALWAYS"] = []
			for i in range(root_always.childCount()):
				ch = root_always.child(i)
				if ch.data(0, Qt.UserRole) == "GROUP":
					new_groups["ROOT_ALWAYS"].append(ch.text(0))

		# Per-page groups
		if root_pages:
			for pidx in range(root_pages.childCount()):
				page_item = root_pages.child(pidx)
				lst = []
				for j in range(page_item.childCount()):
					ch = page_item.child(j)
					if ch.data(0, Qt.UserRole) == "GROUP":
						lst.append(ch.text(0))
				new_groups[pidx] = lst

		# Ensure every page index in editor.pages has an entry
		for i in range(len(self.editor.pages)):
			new_groups.setdefault(i, self.editor.groups.get(i, []))

		new_groups.setdefault("ROOT_ALWAYS", self.editor.groups.get("ROOT_ALWAYS", []))

		# replace editor.groups atomically
		self.editor.groups = new_groups

		# 3) Walk the tree and assign page_index, group index, and compute z-values.
		# We'll number z-values in the visual stacking order as they appear in the tree.
		z_index = 0

		def recurse_assign(parent, parent_type, page_index=None, current_group_idx=None):
			nonlocal z_index
			for i in range(parent.childCount()):
				ch = parent.child(i)
				ctype = ch.data(0, Qt.UserRole)
				if ctype == "GROUP":
					# lookup group index in the new_groups for this parent
					gname = ch.text(0)
					key = "ROOT_ALWAYS" if parent_type == "ROOT_ALWAYS" else page_index
					groups_list = self.editor.groups.get(key, [])
					try:
						gidx = groups_list.index(gname)
					except ValueError:
						# append as last resort
						self.editor.groups.setdefault(key, [])
						self.editor.groups[key].append(gname)
						gidx = len(self.editor.groups[key]) - 1
					# recurse into group with new current_group_idx
					recurse_assign(ch, parent_type, page_index, gidx)
				elif ctype == "ELEMENT":
					el = ch.data(1, Qt.UserRole)
					if el:
						# set element fields deterministically
						el.always_visible = (parent_type == "ROOT_ALWAYS")
						el.page_index = None if parent_type == "ROOT_ALWAYS" else page_index
						el.group = current_group_idx
						# set z in the order we visit elements
						try:
							el.setZValue(z_index)
						except Exception:
							pass
						z_index += 1
				else:
					# generic container node, just recurse
					recurse_assign(ch, parent_type, page_index, current_group_idx)

		# Assign for ROOT_ALWAYS
		if root_always:
			recurse_assign(root_always, "ROOT_ALWAYS", None, None)

		# Assign for each page
		if root_pages:
			for pidx in range(root_pages.childCount()):
				page_item = root_pages.child(pidx)
				recurse_assign(page_item, "PAGE", pidx, None)

		# last step: ensure any elements not present in the tree keep their z-order (rare)
		# Also, update any UI elements that depend on pages/groups
		# (caller will normally rebuild the outliner / UI)

	def _sync_tree_element_to_model(self, tree_item, parent_type, page_index=None):
		"""
        Sync a single subtree starting at tree_item into element model fields.
        Used for page reorders where we already know page index.
        """

		# helper recurse
		def recurse(ch, current_group_idx=None):
			if ch.data(0, Qt.UserRole) == "GROUP":
				gname = ch.text(0)
				key = "ROOT_ALWAYS" if parent_type == "ROOT_ALWAYS" else page_index
				groups_list = self.editor.groups.setdefault(key, [])
				try:
					gidx = groups_list.index(gname)
				except ValueError:
					groups_list.append(gname)
					gidx = len(groups_list) - 1
				# recurse children with new group idx
				for i in range(ch.childCount()):
					recurse(ch.child(i), gidx)
			elif ch.data(0, Qt.UserRole) == "ELEMENT":
				el = ch.data(1, Qt.UserRole)
				if el:
					el.always_visible = parent_type == "ROOT_ALWAYS"
					el.page_index = None if parent_type == "ROOT_ALWAYS" else page_index
					el.group = current_group_idx
			else:
				for i in range(ch.childCount()):
					recurse(ch.child(i), current_group_idx)

		recurse(tree_item, None)

	def get_brush(self, role, theme="Dark"):
		if theme in ("Light", "l", "true"):
			mapping = {
				"PAGE": QBrush(QColor("#0077CC")),
				"GROUP": QBrush(QColor("#CC0055")),
				"ELEMENT": QBrush(QColor("#000000")),
				"ROOT": QBrush(QColor("#CC7700")),
			}
		else:
			mapping = {
				"PAGE": QBrush(QColor("#00CFFF")),
				"GROUP": QBrush(QColor("#FF4480")),
				"ELEMENT": QBrush(QColor("#FFFFFF")),
				"ROOT": QBrush(QColor("#FFAA00")),
			}
		return mapping.get(role, QBrush(QColor("#FFFFFF")))

	# ------------------------- Rebuild Outliner -------------------------
	def rebuild_outliner(self):
		self.blockSignals(True)
		self.clear()

		root_always = QTreeWidgetItem(["AlwaysVisible"])
		root_always.setData(0, Qt.UserRole, "ROOT_ALWAYS")
		root_always.setFont(0, QFont())
		root_always.setForeground(0, self.get_brush("ROOT", cfg.get("theme", "Dark")))
		root_always.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
		self.addTopLevelItem(root_always)

		root_pages = QTreeWidgetItem(["Pages"])
		root_pages.setData(0, Qt.UserRole, "ROOT_PAGES")
		root_pages.setFont(0, QFont())
		root_pages.setForeground(0, self.get_brush("ROOT", cfg.get("theme", "Dark")))
		root_pages.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
		self.addTopLevelItem(root_pages)

		# ELEMENTS
		always_items = [el for el in self.display_items if
						getattr(el, "always_visible", False) or getattr(el, "page_index", None) is None]
		page_items = [el for el in self.display_items if not getattr(el, "always_visible", False)]

		always_items.sort(key = lambda e: e.zValue())
		page_items.sort(key = lambda e: e.zValue())

		# add always-visible items and groups under the AlwaysVisible root
		self._add_items_to_parent(always_items, root_always, parent_type = "ROOT_ALWAYS")

		# PAGES
		for page_idx, page_name in enumerate(self.editor.pages):
			page_item = QTreeWidgetItem([page_name])
			page_item.setData(0, Qt.UserRole, "PAGE")
			page_item.setData(1, Qt.UserRole, page_idx)
			PAGE_FONT = QFont()
			PAGE_FONT.setBold(True)
			page_item.setFont(0, PAGE_FONT)
			page_item.setForeground(0, self.get_brush("PAGE", cfg.get("theme", "Dark")))
			page_item.setFlags(
				Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
			)
			page_item.setCheckState(0, Qt.Checked)
			root_pages.addChild(page_item)

			items = [el for el in self.display_items if el.page_index == page_idx]
			items.sort(key = lambda e: e.zValue())
			self._add_items_to_parent(items, page_item, parent_type = "PAGE", page_index = page_idx)

		self.expandAll()
		self.blockSignals(False)

	def _add_items_to_parent(self, items, parent_item, parent_type="PAGE", page_index=None):
		key = "ROOT_ALWAYS" if parent_type == "ROOT_ALWAYS" else page_index
		groups_for_parent = self.editor.groups.get(key, [])

		for gid, group_name in enumerate(groups_for_parent):
			group_item = QTreeWidgetItem([group_name])
			group_item.setFont(0, QFont())
			group_item.setForeground(0, self.get_brush("GROUP", cfg.get("theme", "Dark")))
			group_item.setFlags(
				Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable |
				Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
			)
			group_item.setCheckState(0, Qt.Checked)
			group_item.setData(0, Qt.UserRole, "GROUP")
			group_item.setData(1, Qt.UserRole, gid)
			parent_item.addChild(group_item)

			group_elements = [el for el in items if getattr(el, "group", None) == gid]
			self._add_elements(group_elements, group_item)

		# Add Un:Grouped Elements
		ungrouped = [el for el in items if getattr(el, "group", None) is None]
		self._add_elements(ungrouped, parent_item)

	def _add_elements(self, elements, parent_item):
		for el in elements:
			el_item = QTreeWidgetItem([el.name])
			el_item.setFont(0, QFont())
			el_item.setForeground(0, self.get_brush("ELEMENT", cfg.get("theme", "Dark")))
			el_item.setFlags(
				Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled
			)
			state = Qt.Checked if getattr(el, "isVisible", lambda: True)() else Qt.Unchecked
			el_item.setCheckState(0, state)
			el_item.setData(0, Qt.UserRole, "ELEMENT")
			el_item.setData(1, Qt.UserRole, el)
			parent_item.addChild(el_item)

			if el.name in (item.name for item in editor.scene.selectedItems()):
				el_item.setSelected(True)

	# ------------------------- Context Menu -------------------------
	def on_context_menu(self, pos: QPoint):
		item = self.itemAt(pos)
		menu = QMenu(self)

		if item is None:
			menu.addAction("Add Page", self.add_page)
		else:
			item_type = item.data(0, Qt.UserRole)
			if item_type == "PAGE":
				menu.addAction("Add Group", lambda: self.add_group(item))
				menu.addAction("Delete Page", lambda: self.delete_page(item))
			elif item_type == "ROOT_ALWAYS":
				menu.addAction("Add Group", lambda: self.add_group(item))
			elif item_type == "GROUP":
				menu.addAction("Delete Group", lambda: self.delete_group(item))

		menu.exec(self.viewport().mapToGlobal(pos))

	# ------------------------- Page / Group Operations -------------------------
	def add_page(self):
		name, ok = QInputDialog.getText(self, "Add Page", "Page name:")
		if not ok or not name:
			return
		self.editor.pages.append(name)
		# ensure groups mapping has an entry for the new page
		new_index = len(self.editor.pages) - 1
		self.editor.groups.setdefault(new_index, [])
		self.rebuild_outliner()

	def add_group(self, parent):
		gname, ok = QInputDialog.getText(self, "Add Group", "Group name:")
		if not ok or not gname:
			return

		parent_type = parent.data(0, Qt.UserRole)
		if parent_type == "PAGE":
			page_index = parent.data(1, Qt.UserRole)
			self.editor.groups.setdefault(page_index, [])
			if gname not in self.editor.groups[page_index]:
				self.editor.groups[page_index].append(gname)
		else:
			# default to ROOT_ALWAYS if parent is not a page (be safe)
			self.editor.groups.setdefault("ROOT_ALWAYS", [])
			if gname not in self.editor.groups["ROOT_ALWAYS"]:
				self.editor.groups["ROOT_ALWAYS"].append(gname)

		self.rebuild_outliner()

	def delete_page(self, page_item):
		page_index = page_item.data(1, Qt.UserRole)
		self.editor.pages.pop(page_index)
		# remove groups for this page (shift keys of pages after it)
		if page_index in self.editor.groups:
			del self.editor.groups[page_index]
		# shift any page-indexed groups down by 1
		new_groups = {}
		for k, v in list(self.editor.groups.items()):
			if isinstance(k, int):
				new_k = k if k < page_index else (k - 1)
				new_groups[new_k] = v
			else:
				new_groups[k] = v
		self.editor.groups = new_groups

		# update element page indices and keep group indices consistent (shift where needed)
		for el in self.display_items:
			if el.page_index is None:
				continue
			if el.page_index == page_index:
				el.page_index = 0
				el.group = None
			elif el.page_index > page_index:
				el.page_index -= 1

		self.rebuild_outliner()

	def delete_group(self, group_item):
		parent = group_item.parent()
		if not parent:
			# safety fallback: just remove from UI and rebuild
			parent.removeChild(group_item)
			self.rebuild_outliner()
			return

		group_name = group_item.text(0)
		parent_type = parent.data(0, Qt.UserRole)
		if parent_type == "PAGE":
			page_index = parent.data(1, Qt.UserRole)
			lst = self.editor.groups.get(page_index, [])
			if group_name in lst:
				removed_idx = lst.index(group_name)
				lst.remove(group_name)
				# clear group assignment from elements that referenced it and adjust other indices
				for el in self.display_items:
					if getattr(el, "page_index", None) == page_index:
						if getattr(el, "group", None) == removed_idx:
							el.group = None
						elif getattr(el, "group", None) is not None and el.group > removed_idx:
							el.group -= 1
		else:
			lst = self.editor.groups.get("ROOT_ALWAYS", [])
			if group_name in lst:
				removed_idx = lst.index(group_name)
				lst.remove(group_name)
				for el in self.display_items:
					if getattr(el, "always_visible", False):
						if getattr(el, "group", None) == removed_idx:
							el.group = None
						elif getattr(el, "group", None) is not None and el.group > removed_idx:
							el.group -= 1

		self.rebuild_outliner()

	def find_item_for_element(self, el):
		def walk(parent):
			for i in range(parent.childCount()):
				child = parent.child(i)
				if child.data(0, Qt.UserRole) == "ELEMENT" and child.data(1, Qt.UserRole) is el:
					return child
				found = walk(child)
				if found:
					return found
			return None

		for i in range(self.topLevelItemCount()):
			found = walk(self.topLevelItem(i))
			if found:
				return found
		return None

	def select_element(self, el, make_current=False):
		"""Select element in Outliner. If make_current=True set current/scroll (only once at the end)."""
		item = self.find_item_for_element(el)
		if not item:
			return False
		item.setSelected(True)
		if make_current:
			self.setCurrentItem(item)
			self.scrollToItem(item)
		return True

	def deselect_element(self, el):
		"""Remove selection without changing currentItem/focus."""
		item = self.find_item_for_element(el)
		if not item:
			return False
		item.setSelected(False)
		return True


class TemplatelistWidget(QListWidget):
	def mousePressEvent(self, event):
		# Use event.position() and convert to QPoint
		pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
		item = self.itemAt(pos)
		if item and item.isSelected():
			# Deselect if already selected
			self.clearSelection()
			# Emit selection changed manually
			self.itemSelectionChanged.emit()
		else:
			super().mousePressEvent(event)


def _sanitize_for_key(s: str) -> str:
	if s is None:
		return ""
	s2 = re.sub(r"\(.+?\)", "", s)  # remove parentheses content
	s2 = re.sub(r"[^A-Za-z0-9]", "", s2)  # remove non-alnum
	return s2.lower()


def _variant_order_from_name(s: str) -> int:
	if not s:
		return 0
	m = re.search(r"(\d+)$", s)
	return int(m.group(1)) if m else 0


def _find_if_blocks_with_positions(text: str):
	lines = text.splitlines(keepends = True)

	blocks = []
	in_if = False
	buf = []
	start_pos = 0
	pos = 0

	for line in lines:
		ls = line.strip().lower()

		if ls.startswith("if "):
			if not in_if:
				in_if = True
				buf = [line]
				start_pos = pos
			else:
				# nested IF — traktujemy jako zwykłą linię
				buf.append(line)

		elif ls.startswith("endif") and in_if:
			buf.append(line)
			end_pos = pos + len(line)

			block_text = "".join(buf)
			blocks.append((start_pos, end_pos, block_text))

			in_if = False
			buf = []

		elif in_if:
			buf.append(line)

		pos += len(line)

	return blocks


def find_drawindexed_blocks(ini_text: str):
	SECTION_ORDER = [
		"Namespace", "Constants", "Present", "Key",
		"TextureOverride", "ShaderOverride", "CommandList",
		"CustomShader", "Resource"
	]

	def default_classify(header_name: str):
		if not header_name:
			return "Other"
		for base in SECTION_ORDER:
			if header_name.startswith(base):
				return base
		return "Other"

	# headers
	header_re = re.compile(r'(?m)^\[([^\]]+)\]\s*$')
	headers = []
	for m in header_re.finditer(ini_text):
		name = m.group(1)
		kind = default_classify(name)
		headers.append((m.start(), name, kind))
	headers.sort(key = lambda x: x[0])

	def header_for_pos(pos):
		last = None
		for p, name, kind in headers:
			if p <= pos:
				last = (name, kind)
			else:
				break
		return last or ("<GLOBAL>", "GLOBAL")

	blocks_by_header = {}

	# helper: extend end by at most one newline sequence (\r\n or \n)
	def extend_end_one_newline(end_idx: int):
		if end_idx >= len(ini_text):
			return end_idx
		c = ini_text[end_idx]
		if c == '\r':
			if end_idx + 1 < len(ini_text) and ini_text[end_idx + 1] == '\n':
				return end_idx + 2
			return end_idx + 1
		if c == '\n':
			return end_idx + 1
		return end_idx

	used_ranges = []

	# 1) if...endif blocks (use your scanner which respects line endings)
	for start, end, block_text in _find_if_blocks_with_positions(ini_text):
		# only care if contains drawindexed
		if not re.search(r'(?im)^\s*drawindexed\s*=', block_text):
			continue

		header_name, header_kind = header_for_pos(start)

		# try to find comment inside block (line starting with ;)
		cm = re.search(r'(?m)^\s*;\s*(.+?)\s*$', block_text)
		if cm:
			comment = cm.group(1).strip()
		else:
			# fallback: check single line directly above the `if` in original text
			before = ini_text[:start].splitlines()
			comment = ""
			if before:
				last = before[-1].strip()
				if last.startswith(";"):
					comment = last[1:].strip()

		# draw line inside block
		dm = re.search(r'(?im)^\s*drawindexed\s*=\s*(.+?)\s*$', block_text)
		draw = dm.group(1).strip() if dm else ""

		cond_m = re.match(r'(?im)^\s*if\s+([^\r\n]+)', block_text)
		condition = cond_m.group(1).strip() if cond_m else ""

		# extend end by at most one newline so replacement removes that trailing newline too
		end2 = extend_end_one_newline(end)

		key = (header_name, header_kind)
		blocks_by_header.setdefault(key, []).append({
			"start": start, "end": end2, "text": ini_text[start:end2],
			"comment": comment, "draw": draw, "condition": condition,
			"is_if_block": True
		})

		used_ranges.append((start, end2))

	# sort and merge used_ranges for efficient lookup
	used_ranges.sort()
	merged = []
	for a, b in used_ranges:
		if not merged or a > merged[-1][1]:
			merged.append([a, b])
		else:
			merged[-1][1] = max(merged[-1][1], b)
	used_ranges = [(x, y) for x, y in merged]

	def is_in_used(pos):
		for a, b in used_ranges:
			if pos >= a and pos < b:
				return True
			if pos < a:
				break
		return False

	# 2) simple ;comment + drawindexed outside if-blocks
	simple_re = re.compile(
		r'^[ \t]*;\s*(?P<comment>.+?)\s*\r?\n[ \t]*(?:drawindexed\s*=\s*)(?P<draw>.+)\s*$',
		flags = re.IGNORECASE | re.MULTILINE
	)

	for m in simple_re.finditer(ini_text):
		s = m.start()
		if is_in_used(s):
			continue

		start = s
		end = m.end()
		# extend end by at most one newline (same strategy)
		end2 = extend_end_one_newline(end)

		header_name, header_kind = header_for_pos(start)
		block_text = ini_text[start:end2]
		comment = (m.group("comment") or "").strip()
		draw = (m.group("draw") or "").strip()
		condition = ""

		key = (header_name, header_kind)
		blocks_by_header.setdefault(key, []).append({
			"start": start, "end": end2, "text": block_text,
			"comment": comment, "draw": draw, "condition": condition,
			"is_if_block": False
		})

	# sort blocks by start within each header, compute san + variant_index
	for k, lst in list(blocks_by_header.items()):
		lst.sort(key = lambda x: x["start"])
		for b in lst:
			raw = b.get("comment") or b.get("draw") or ""
			san_raw = _sanitize_for_key(raw)
			san_base = re.sub(r"\d+$", "", san_raw)
			b["san"] = san_base or san_raw or "unknown"
			b["_order_key"] = _variant_order_from_name(san_raw)
		groups = defaultdict(list)
		for b in lst:
			groups[b["san"]].append(b)
		for san, bls in groups.items():
			bls.sort(key = lambda x: x["_order_key"])
			for idx, bb in enumerate(bls):
				bb["variant_index"] = idx

	return blocks_by_header


def _normalize_saved_edits_vidx(d):
	# Walk: filename -> header -> san -> vidx_map
	for fname, headers in list(d.items()):
		if not isinstance(headers, dict):
			continue
		for hname, sans in list(headers.items()):
			if not isinstance(sans, dict):
				continue
			for san, vidx_map in list(sans.items()):
				if not isinstance(vidx_map, dict):
					continue

				new_map = {}
				for k, v in vidx_map.items():
					try:
						ik = int(k)  # "0" -> 0
					except Exception:
						ik = k
					new_map[ik] = v

				d[fname][hname][san] = new_map


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _norm_text(s: str) -> str:
	return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def _strip_comment_prefix(line: str) -> str:
	s = (line or "").strip()
	if s.startswith(";"):
		return s[1:].strip()
	return s


def _sanitize_key(s: str) -> str:
	s = (s or "")
	s = re.sub(r"\(.+?\)", "", s)
	s = re.sub(r"[^A-Za-z0-9_/.\-]+", "", s)
	return s.strip().lower()


def _section_name_from_header(header_key) -> str:
	if isinstance(header_key, (tuple, list)) and header_key:
		return str(header_key[0])
	return str(header_key or "<GLOBAL>")


def _make_uid() -> str:
	import uuid
	return uuid.uuid4().hex[:12]


# ------------------------------------------------------------
# DrawIndexed parser (you already have this in your project)
# ------------------------------------------------------------
# Keep your existing find_drawindexed_blocks(ini_text) as-is.
# Expected block dict fields:
#   start, end, text, comment, draw, condition, san, variant_index, etc.
#
# def find_drawindexed_blocks(ini_text: str) -> dict:
#     ...


# ------------------------------------------------------------
# Texture parser
# ------------------------------------------------------------

@dataclass
class TextureBlock:
	uid: str
	header_key: tuple
	start: int
	end: int
	text: str
	comment: str
	key: str
	value: str
	condition: str = ""
	raw_text: str = ""

	@property
	def san(self) -> str:
		return _sanitize_key(self.key or self.value or self.comment or "texture")


TEXTURE_SUFFIXES = (
	"normalmap",
	"lightmap",
	"specular",
	"emissive",
	"albedo",
	"basecolor",
	"diffuse",
	"normal",
	"light",
)

TEXTURE_SUFFIX_RE = re.compile(
	r"(?i)^(.*?)(?:"
	r"NormalMap|LightMap|Specular|Emissive|BaseColor|Albedo|Diffuse|Normal|Light"
	r")$"
)

TEXTURE_SLOT_RE = re.compile(r"^(?:ps|vs|gs|hs|ds|cs)-t\d+\b", re.I)
BIND_RE = re.compile(r"^\s*([^;#\[\]=:]+?)\s*(=|:)\s*(.+?)\s*$")


def _normalize_text(s: str) -> str:
	return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def _is_valid_texture_section(section_name: str) -> bool:
	s = (section_name or "").strip().lower()
	return s.startswith("textureoverride") or s.startswith("commandlist")


def _strip_resource_prefix(s: str) -> str:
	s = (s or "").strip()
	s = s.replace("\\", "/")
	s = re.sub(r"(?i)^resource[:/\\]*", "", s)
	s = re.sub(r"(?i)^resource", "", s)
	return s.strip("/\\")


def _extract_semantic(name: str) -> str:
	s = _strip_resource_prefix(name).replace("\\", "/")
	last = s.split("/")[-1].strip()

	low = last.lower()
	if low.endswith("normalmap") or low.endswith("normal"):
		return "NormalMap"
	if low.endswith("lightmap") or low.endswith("light"):
		return "LightMap"
	if low.endswith("diffuse") or low.endswith("albedo") or low.endswith("basecolor"):
		return "Diffuse"
	if low.endswith("specular"):
		return "Specular"
	if low.endswith("emissive"):
		return "Emissive"
	return ""


def _extract_part_from_resource(name: str) -> str:
	"""
    Examples:
      ResourceKokomiHeadDiffuse     -> KokomiHead
      ResourceKokomiHeadLightMap    -> KokomiHead
      Resource/KokomiHead/Diffuse   -> KokomiHead
      Resource\\KokomiHead\\NormalMap -> KokomiHead
    """
	s = _strip_resource_prefix(name)
	if not s:
		return ""

	s = s.replace("\\", "/").strip("/")
	if not s:
		return ""

	parts = [p for p in s.split("/") if p]

	# path style: Resource/KokomiHead/Diffuse -> KokomiHead
	if len(parts) >= 2:
		last_sem = _extract_semantic(parts[-1])
		if last_sem:
			return parts[-2].strip()

	last = parts[-1]

	# camelcase suffix style: KokomiHeadDiffuse -> KokomiHead
	m = TEXTURE_SUFFIX_RE.match(last)
	if m:
		base = m.group(1).strip("_- .")
		if base:
			return base

	# fallback: if last itself is just a semantic word, use parent folder if present
	if last.lower() in {x.lower() for x in TEXTURE_SUFFIXES} and len(parts) >= 2:
		return parts[-2].strip()

	return last.strip()


def _line_is_texture_binding(line: str) -> bool:
	s = (line or "").strip()
	if not s or s.startswith(";") or s.startswith("#"):
		return False

	m = BIND_RE.match(s)
	if not m:
		return False

	key = m.group(1).strip().lower()
	value = m.group(3).strip().lower()

	# ❌ skip non-texture commands
	if key.startswith(("run", "ib", "vb", "draw", "dispatch")):
		return False

	# ✅ only real texture slots
	if TEXTURE_SLOT_RE.match(key):
		return True

	# optional fallback (resource but still texture-like)
	if "resource" in value:
		return True

	return False


def _parse_kv(line: str):
	m = BIND_RE.match(line or "")
	if not m:
		return None
	return m.group(1).strip(), m.group(3).strip()


def _build_neighbor_window(lines, start_idx: int, end_idx: int, pad: int = 10) -> str:
	left = max(0, start_idx - pad)
	right = min(len(lines), end_idx + pad)
	chunk = lines[left:right]
	while chunk and not chunk[0].strip():
		chunk.pop(0)
	while chunk and not chunk[-1].strip():
		chunk.pop()
	return "\n".join(chunk).rstrip("\n")


def find_texture_blocks(ini_text: str):
	text = _normalize_text(ini_text)
	lines = text.split("\n")

	blocks_by_header = defaultdict(list)

	current_section = "<GLOBAL>"
	current_group = []
	current_group_part = None
	current_group_semantics = []

	def flush_group():
		nonlocal current_group, current_group_part, current_group_semantics

		if not current_group:
			current_group_part = None
			current_group_semantics = []
			return

		valid_semantics = {"Diffuse", "NormalMap", "LightMap"}

		sem_set = {s for s in current_group_semantics if s}
		has_valid = bool(sem_set & valid_semantics)

		if len(current_group) < 2 or not has_valid:
			# skip trash groups
			current_group = []
			current_group_part = None
			current_group_semantics = []
			return

		# All texture bindings for one part, even if they are not perfectly adjacent.
		line_indices = [idx for idx, _ in current_group]
		start_idx = min(line_indices)
		end_idx = max(line_indices) + 1

		core_lines = [line for _, line in current_group]
		core_text = "\n".join(core_lines).strip("\n")
		preview_text = _build_neighbor_window(lines, start_idx, end_idx, pad = 10)

		first_key, first_value = _parse_kv(current_group[0][1])
		part = current_group_part or _extract_part_from_resource(first_value) or _extract_part_from_resource(
			first_key) or first_key or first_value or "Texture"

		semantics = []
		seen = set()
		for sem in current_group_semantics:
			if sem and sem not in seen:
				seen.add(sem)
				semantics.append(sem)

		if len(current_group) == 1:
			summary = part
		else:
			if semantics:
				summary = f"{part}"
			else:
				summary = part

		block = {
			"uid": _make_uid(),
			"header_key": (current_section, "texture"),
			"start": start_idx,
			"end": end_idx,
			"text": preview_text,  # what you show in the editor
			"core_text": core_text,  # actual grouped lines
			"part": part,
			"summary": summary,
			"semantics": semantics,
			"entries": [],
			"key": first_key or "",
			"value": first_value or "",
			"comment": "",
			"condition": "",
		}

		for idx, line in current_group:
			parsed = _parse_kv(line)
			if not parsed:
				continue
			k, v = parsed
			block["entries"].append({
				"line_index": idx,
				"key": k,
				"value": v,
				"semantic": _extract_semantic(v or k),
				"line": line,
			})

		blocks_by_header[(current_section, "texture")].append(block)

		current_group = []
		current_group_part = None
		current_group_semantics = []

	for i, line in enumerate(lines):
		s = line.strip()

		sec = re.fullmatch(r"\[([^\]]+)\]", s)
		if sec:
			flush_group()
			current_section = sec.group(1).strip()
			continue

		if not _is_valid_texture_section(current_section):
			continue

		if not s:
			flush_group()
			continue

		if not _line_is_texture_binding(line):
			# ignore non-texture lines inside the section
			continue

		kv = _parse_kv(line)
		if not kv:
			continue

		key, value = kv
		part = _extract_part_from_resource(value) or _extract_part_from_resource(key) or key or value or "Texture"
		semantic = _extract_semantic(value or key)

		# group by shared Part
		if current_group_part is None:
			current_group_part = part

		# if the part changes, close previous group and start a new one
		if part != current_group_part and current_group:
			flush_group()
			current_group_part = part

		current_group.append((i, line))
		current_group_semantics.append(semantic)

	flush_group()

	return dict(blocks_by_header)


# ------------------------------------------------------------
# Texture page
# ------------------------------------------------------------

class TextureEditorPage(QWidget):
	"""
    Textures/resource bindings editor page.
    Stores edits under:
      saved_edits[filename]["__textures__"][header_name][uid] = {...}
    """

	def __init__(self, ini_text, parent=None, filename=None, saved_edits=None):
		super().__init__(parent)

		if saved_edits is None or filename == "":
			saved_edits = {}

		self.parent = parent
		self.filename = filename
		self.ini_text = ini_text
		self.saved_edits = saved_edits

		self.blocks_by_header = find_texture_blocks(self.ini_text)
		self.header_keys = sorted(self.blocks_by_header.keys(), key = lambda x: (x[0] != "<GLOBAL>", x[0].lower()))

		self._build_ui()

		if self.header_keys:
			self.header_list.setCurrentRow(0)
			self.update_block_list(0)

		if self.parent is not None:
			setattr(self.parent, "texture_dialog", self)

	def _split_outer_if_block(self, text: str):
		text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		lines = text.split("\n")

		if len(lines) < 3:
			return False, "", text

		first = lines[0].strip()
		last = lines[-1].strip().lower()

		if not first.lower().startswith("if ") or last != "endif":
			return False, "", text

		cond = first[3:].strip()
		body = "\n".join(lines[1:-1]).strip("\n")
		return True, cond, body

	def _apply_condition_to_raw_text(self, raw_text: str, cond: str) -> str:
		raw_text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		cond = (cond or "").strip()

		is_if, old_cond, body = self._split_outer_if_block(raw_text)

		if cond:
			if not cond.startswith("$"):
				cond = "$" + cond

			if is_if:
				return f"if {cond}\n{body}\nendif"

			return f"if {cond}\n{raw_text}\nendif"

		return body if is_if else raw_text

	def _find_selected_line_range(self, lines, selected_text: str):
		selected_text = (selected_text or "").replace("\u2029", "\n").strip("\n")
		if not selected_text:
			return None

		sel_lines = [l.strip() for l in selected_text.split("\n") if l.strip()]
		if not sel_lines:
			return None

		n = len(lines)
		m = len(sel_lines)

		for i in range(n - m + 1):
			chunk = [lines[i + j].strip() for j in range(m)]
			if chunk == sel_lines:
				return i, i + m, sel_lines

		return None

	def wrap_selected_with_if(self):
		import textwrap

		text = self.raw_block_edit.toPlainText().replace("\r\n", "\n").replace("\r", "\n")
		cur = self.raw_block_edit.textCursor()

		# fallback: brak zaznaczenia
		if not cur.hasSelection():
			raw = text.strip("\n")
			if not raw:
				return
			self.raw_block_edit.setPlainText(
				self._apply_condition_to_raw_text(raw, self.condition_edit.text())
			)
			return

		selected = cur.selectedText().replace("\u2029", "\n").strip("\n")
		if not selected:
			return

		lines = text.split("\n")
		sel_info = self._find_selected_line_range(lines, selected)

		# fallback jeśli nie znaleziono dokładnego matcha
		if not sel_info:
			wrapped = self._apply_condition_to_raw_text(selected, self.condition_edit.text())
			cur.insertText(wrapped)
			return

		sel_start, sel_end, sel_lines = sel_info

		cond = self.condition_edit.text().strip()

		# znajdź istniejący IF
		def find_if_block():
			for i in range(len(lines)):
				if lines[i].strip().lower().startswith("if "):
					depth = 0
					for j in range(i, len(lines)):
						s = lines[j].strip().lower()
						if s.startswith("if "):
							depth += 1
						elif s == "endif":
							depth -= 1
							if depth == 0:
								return i, j
			return None

		if_block = find_if_block()

		# jeśli brak IF → wrap normalny
		if not if_block:
			wrapped = self._apply_condition_to_raw_text(selected, cond)
			cur.insertText(wrapped)
			return

		if_start, if_end = if_block

		# jeśli już w IF → nic nie rób
		if if_start < sel_start < if_end:
			return

		body_indent = ""
		for i in range(if_start + 1, if_end):
			if lines[i].strip():
				body_indent = re.match(r"\s*", lines[i]).group(0)
				break
		if not body_indent:
			body_indent = "\t"

		moved = textwrap.dedent("\n".join(sel_lines)).split("\n")
		moved = [body_indent + l if l.strip() else "" for l in moved]

		new_lines = lines[:]

		# usuń zaznaczenie
		for i in range(sel_end - 1, sel_start - 1, -1):
			del new_lines[i]

		insert_at = if_start + 1

		new_lines[insert_at:insert_at] = moved + [""]

		self.raw_block_edit.setPlainText("\n".join(new_lines).rstrip("\n"))

	def _build_ui(self):
		layout = QVBoxLayout(self)

		layout.addWidget(QLabel("Section (Header)"))
		self.header_list = QListWidget()
		for name, kind in self.header_keys:
			label = f"{name}" if name != "<GLOBAL>" else "<GLOBAL>"
			it = QListWidgetItem(label)
			it.setData(Qt.UserRole, (name, kind))
			self.header_list.addItem(it)
		layout.addWidget(self.header_list)

		layout.addWidget(QLabel("Texture Blocks"))
		self.block_list = QListWidget()
		self.block_list.setSelectionMode(QAbstractItemView.SingleSelection)
		layout.addWidget(self.block_list)

		mono = QFont("Consolas")
		mono.setPointSize(10)
		self.block_list.setFont(mono)

		# fields
		row1 = QHBoxLayout()
		row1.addWidget(QLabel("Key"))
		self.key_edit = QLineEdit()
		row1.addWidget(self.key_edit)
		row1.addWidget(QLabel("Value"))
		self.value_edit = QLineEdit()
		row1.addWidget(self.value_edit)
		layout.addLayout(row1)

		row2 = QHBoxLayout()
		# row2.addWidget(QLabel("Comment"))
		self.comment_edit = QLineEdit()
		# row2.addWidget(self.comment_edit)
		row2.addWidget(QLabel("Condition"))
		self.condition_edit = QLineEdit()
		row2.addWidget(self.condition_edit)
		layout.addLayout(row2)

		layout.addWidget(QLabel("Neighboring Lines / Raw Binding"))
		self.raw_block_edit = QTextEdit()
		self.raw_block_edit.setFont(mono)
		self.raw_block_edit.setPlaceholderText("Editable")
		layout.addWidget(self.raw_block_edit)

		# Buttons
		self.btn_wrap_if = QPushButton("Wrap Selected / Move If")
		self.btn_wrap_if.clicked.connect(self.wrap_selected_with_if)
		self.btn_move_up = QPushButton("Move Up")
		self.btn_move_down = QPushButton("Move Down")
		self.btn_copy = QPushButton("Duplicate")
		self.btn_delete = QPushButton("Delete")
		self.btn_add = QPushButton("Add New")
		# self.btn_apply = QPushButton("Apply Edits")
		# self.btn_close = QPushButton("Close")

		self.btn_move_up.clicked.connect(self.move_selected_up)
		self.btn_move_down.clicked.connect(self.move_selected_down)
		self.btn_copy.clicked.connect(self.duplicate_selected)
		self.btn_delete.clicked.connect(self.delete_selected)
		self.btn_add.clicked.connect(self.add_new_entry)
		# self.btn_apply.clicked.connect(self.apply_edits_to_parent)
		# self.btn_close.clicked.connect(self._close_request)

		row = QHBoxLayout()
		row.addWidget(self.btn_wrap_if)
		row.addWidget(self.btn_move_up)
		row.addWidget(self.btn_move_down)
		row.addWidget(self.btn_copy)
		row.addWidget(self.btn_delete)
		row.addWidget(self.btn_add)
		# row.addWidget(self.btn_apply)
		# row.addWidget(self.btn_close)
		layout.addLayout(row)

		self.header_list.currentRowChanged.connect(self.update_block_list)
		self.block_list.currentRowChanged.connect(self.load_block_fields)

	# ---------------- saved_edits helpers ----------------

	def _textures_root(self):
		self.saved_edits.setdefault(self.filename, {})
		self.saved_edits[self.filename].setdefault("__textures__", {})
		return self.saved_edits[self.filename]["__textures__"]

	def _get_header_edits(self, header_name):
		if not self.filename:
			return {}
		return self.saved_edits.get(self.filename, {}).get("__textures__", {}).get(header_name, {})

	def _ensure_header_slot(self, header_name, uid):
		self.saved_edits.setdefault(self.filename, {})
		self.saved_edits[self.filename].setdefault("__textures__", {})
		self.saved_edits[self.filename]["__textures__"].setdefault(header_name, {})
		self.saved_edits[self.filename]["__textures__"][header_name].setdefault(uid, {})
		return self.saved_edits[self.filename]["__textures__"][header_name][uid]

	# ---------------- UI list ----------------

	def update_block_list(self, idx):
		self.block_list.clear()
		if idx < 0 or idx >= len(self.header_keys):
			return
		header_key = self.header_keys[idx]
		self.populate_and_reapply(header_key)

	def _label_for_block(self, b, header_key):
		name, kind = header_key
		uid = b.get("uid", "unknown")
		header_edits = self._get_header_edits(name)
		edited = uid in header_edits

		part = b.get("part") or b.get("summary") or b.get("key", "Texture")
		flag = "* " if edited else ""
		return f"{flag}{part} | {uid}"

	def populate_and_reapply(self, header_key):
		if isinstance(header_key, list):
			header_key = tuple(header_key)

		self.block_list.clear()
		blist = self.blocks_by_header.get(header_key, [])

		name, kind = header_key
		for b in blist:
			uid = b.get("uid")
			header_edits = self._get_header_edits(name)
			part = b.get("part") or b.get("summary") or b.get("key", "Texture")

			if uid in header_edits:
				label = f"* {part} | {uid}"
			else:
				label = f"{part} | {uid}"

			it = QListWidgetItem(label)
			it.setData(Qt.UserRole, (header_key, b))
			self.block_list.addItem(it)

		if blist:
			self.block_list.setCurrentRow(0)

	# ---------------- load/save fields ----------------

	def load_block_fields(self, idx):
		if idx < 0:
			self.key_edit.clear()
			self.value_edit.clear()
			self.comment_edit.clear()
			self.condition_edit.clear()
			self.raw_block_edit.clear()
			return

		item = self.block_list.item(idx)
		header_key, block = item.data(Qt.UserRole)

		name, kind = header_key
		uid = block.get("uid")
		header_edits = self._get_header_edits(name)
		ed = header_edits.get(uid, {})

		self.key_edit.setText(ed.get("key", block.get("key", "")))
		self.value_edit.setText(ed.get("value", block.get("value", "")))
		self.comment_edit.setText(ed.get("comment", block.get("comment", "")))
		self.condition_edit.setText(ed.get("condition", block.get("condition", "")))

		raw_text = ed.get("raw_text", "")
		if not raw_text.strip():
			raw_text = block.get("text", "")  # +-10 lines around the grouped block

		self.raw_block_edit.setPlainText(raw_text.rstrip("\n"))

	def _extract_core_texture_block_from_preview(self, preview_text: str, block: dict) -> str:
		preview_text = _normalize_text(preview_text).strip("\n")
		if not preview_text.strip():
			return block.get("core_text", "") or block.get("text", "") or ""

		core_text = (block.get("core_text", "") or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		if not core_text:
			return preview_text

		if core_text in preview_text:
			return core_text

		preview_lines = preview_text.split("\n")
		core_lines = core_text.split("\n")

		# line-wise exact match fallback
		for i in range(len(preview_lines) - len(core_lines) + 1):
			chunk = preview_lines[i:i + len(core_lines)]
			if [c.strip() for c in chunk] == [c.strip() for c in core_lines]:
				return "\n".join(chunk).strip("\n")

		return core_text

	def save_changes_local(self):
		idx = self.block_list.currentRow()
		if idx < 0:
			return

		it = self.block_list.item(idx)
		header_key, block = it.data(Qt.UserRole)

		name, kind = header_key
		uid = block.get("uid")

		slot = self._ensure_header_slot(name, uid)
		slot.update({
			"key": self.key_edit.text().strip(),
			"value": self.value_edit.text().strip(),
			"comment": self.comment_edit.text().strip(),
			"condition": self.condition_edit.text().strip(),
			"raw_text": self.raw_block_edit.toPlainText().strip("\n"),
			"summary": f"{self.key_edit.text().strip()} -> {self.value_edit.text().strip()}",
		})

		it.setText(self._label_for_block(block, header_key))

	# ---------------- block render/apply ----------------

	def _split_outer_if(self, text: str):
		raw = _norm_text(text).strip("\n")
		lines = raw.split("\n")
		if len(lines) < 3:
			return False, "", text or ""

		first = lines[0].strip()
		last = lines[-1].strip().lower()

		if not first.lower().startswith("if ") or last != "endif":
			return False, "", text or ""

		cond = first[3:].strip()
		body = "\n".join(lines[1:-1]).strip("\n")
		return True, cond, body

	def _apply_condition_to_raw_text(self, raw_text: str, cond: str) -> str:
		raw_text = _norm_text(raw_text).strip("\n")
		cond = (cond or "").strip()

		is_if, old_cond, body = self._split_outer_if(raw_text)

		if cond:
			if not cond.startswith("$"):
				cond = "$" + cond
			if is_if:
				return f"if {cond}\n{body}\nendif"
			return f"if {cond}\n{raw_text}\nendif"

		return body if is_if else raw_text

	def _normalize_binding_text(self, text: str) -> str:
		text = _norm_text(text).rstrip("\n")
		if not text:
			return ""
		return text + "\n\n"

	def _build_effective_texture_block(self, block, ed=None):
		ed = ed or {}

		key = (ed.get("key", block.get("key", "")) or "").strip()
		value = (ed.get("value", block.get("value", "")) or "").strip()
		comment = (ed.get("comment", block.get("comment", "")) or "").strip()
		cond = (ed.get("condition", block.get("condition", "")) or "").strip()
		raw_text = (ed.get("raw_text", "") or "").strip("\n")

		if raw_text.strip():
			core = self._extract_core_texture_block_from_preview(raw_text, block)
			core = _normalize_text(core).strip("\n")
			if cond:
				if not cond.startswith("$"):
					cond = "$" + cond
				core = f"if {cond}\n{core}\nendif"
			return self._normalize_binding_text(core)

		if not key:
			key = block.get("key", "")
		if not value:
			value = block.get("value", "")

		lines = []
		if cond:
			if not cond.startswith("$"):
				cond = "$" + cond
			lines.append(f"if {cond}")
			if comment:
				lines.append(f"    ; {comment}")
			lines.append(f"    {key} = {value}")
			lines.append("endif")
		else:
			if comment:
				lines.append(f"; {comment}")
			lines.append(f"{key} = {value}")

		return self._normalize_binding_text("\n".join(lines))

	# ---------------- editing operations ----------------

	def _selected_header_and_index(self):
		idx = self.block_list.currentRow()
		if idx < 0:
			return None, None, None
		item = self.block_list.item(idx)
		if not item:
			return None, None, None
		header_key, block = item.data(Qt.UserRole)
		header_key = tuple(header_key)
		return idx, header_key, block

	def duplicate_selected(self):
		idx, header_key, block = self._selected_header_and_index()
		if block is None:
			return

		name, kind = header_key
		blist = self.blocks_by_header.get(header_key, [])
		pos = next((i for i, b in enumerate(blist) if b.get("uid") == block.get("uid")), -1)
		if pos < 0:
			return

		clone = copy.deepcopy(block)
		clone["uid"] = _make_uid()

		# saved edits duplicate
		header_edits = self._get_header_edits(name)
		if block.get("uid") in header_edits:
			self._ensure_header_slot(name, clone["uid"])
			self.saved_edits[self.filename]["__textures__"][name][clone["uid"]] = copy.deepcopy(
				header_edits[block["uid"]])

		blist.insert(pos + 1, clone)
		self._renumber_variant_indices(header_key)
		self.populate_and_reapply(header_key)
		self.block_list.setCurrentRow(pos + 1)

	def move_selected_up(self):
		idx, header_key, block = self._selected_header_and_index()
		if block is None:
			return

		blist = self.blocks_by_header.get(header_key, [])
		pos = next((i for i, b in enumerate(blist) if b.get("uid") == block.get("uid")), -1)
		if pos <= 0:
			return

		blist[pos - 1], blist[pos] = blist[pos], blist[pos - 1]
		self._renumber_variant_indices(header_key)
		self.populate_and_reapply(header_key)
		self.block_list.setCurrentRow(pos - 1)

	def move_selected_down(self):
		idx, header_key, block = self._selected_header_and_index()
		if block is None:
			return

		blist = self.blocks_by_header.get(header_key, [])
		pos = next((i for i, b in enumerate(blist) if b.get("uid") == block.get("uid")), -1)
		if pos < 0 or pos >= len(blist) - 1:
			return

		blist[pos + 1], blist[pos] = blist[pos], blist[pos + 1]
		self._renumber_variant_indices(header_key)
		self.populate_and_reapply(header_key)
		self.block_list.setCurrentRow(pos + 1)

	def delete_selected(self):
		idx, header_key, block = self._selected_header_and_index()
		if block is None:
			return

		if isinstance(header_key, list):
			header_key = tuple(header_key)

		blist = self.blocks_by_header.get(header_key, [])
		pos = next((i for i, b in enumerate(blist) if b.get("uid") == block.get("uid")), -1)
		if pos < 0:
			return

		name, kind = header_key
		uid = block.get("uid")

		# remove edits if any
		if self.filename:
			tex_root = self.saved_edits.get(self.filename, {}).get("__textures__", {})
			if name in tex_root and uid in tex_root[name]:
				del tex_root[name][uid]

		del blist[pos]
		self._renumber_variant_indices(header_key)
		self.populate_and_reapply(header_key)

	def add_new_entry(self):
		cur_row = self.header_list.currentRow()
		if cur_row < 0:
			return
		header_key = self.header_keys[cur_row]
		header_name, header_kind = header_key

		new_block = {
			"uid": _make_uid(),
			"header_key": header_key,
			"start": 0,
			"end": 0,
			"text": "",
			"comment": "",
			"key": "ps-t0",
			"value": "Resource...",
			"condition": "",
			"raw_text": "",
			"san": _sanitize_key("ps-t0"),
			"variant_index": 0,
		}

		self.blocks_by_header.setdefault(header_key, []).append(new_block)
		self._renumber_variant_indices(header_key)

		self.populate_and_reapply(header_key)
		self.block_list.setCurrentRow(self.block_list.count() - 1)

	def _renumber_variant_indices(self, header_key):
		blist = self.blocks_by_header.get(header_key, [])
		counts = defaultdict(int)
		for b in blist:
			san = b.get("san", _sanitize_key(b.get("key", "")))
			b["san"] = san
			b["variant_index"] = counts[san]
			counts[san] += 1

	# ---------------- close/apply ----------------

	def _close_request(self):
		self.parent = self.parent  # no-op, explicit
		self.hide()

	def apply_edits_to_parent(self):
		self.save_changes_local()

		if not (self.parent and hasattr(self.parent, "ini_editor")):
			QMessageBox.warning(self, "No parent", "Parent editor not available.")
			return

		if "editor" in globals() and editor:
			try:
				editor.allow_alert = False
				editor.rebuild_ini(False)
			except Exception:
				pass

		base_text = self.parent.ini_editor.toPlainText()
		new_text = self._apply_texture_edits_to_ini(base_text)
		self.parent.ini_editor.setPlainText(new_text)
		self.refresh_from_ini(new_text)

	def _apply_texture_edits_to_ini(self, base_text: str) -> str:
		"""
        Rebuilds texture lines by replacing the original texture binding spans.
        Keeps unrelated text intact.
        """
		base_text = _norm_text(base_text)
		current_blocks = find_texture_blocks(base_text)

		# flatten current file blocks in source order
		all_blocks = []
		for header_key, blist in current_blocks.items():
			for b in blist:
				all_blocks.append((b["start"], b["end"], header_key, b))

		if not all_blocks:
			return base_text

		all_blocks.sort(key = lambda x: x[0], reverse = True)

		text = base_text
		for s, e, header_key, b in all_blocks:
			header_name, header_kind = header_key
			ed = self._get_header_edits(header_name).get(b["uid"], {})
			new_block = self._build_effective_texture_block(b, ed)
			text = text[:s] + new_block + text[e:]

		return text

	def refresh_from_ini(self, new_ini_text: str):
		self.ini_text = new_ini_text
		self.blocks_by_header = find_texture_blocks(self.ini_text)
		self.header_keys = sorted(self.blocks_by_header.keys(), key = lambda x: (x[0] != "<GLOBAL>", x[0].lower()))

		prev_data = None
		cur_row = self.header_list.currentRow()
		if 0 <= cur_row < self.header_list.count():
			prev_data = self.header_list.item(cur_row).data(Qt.UserRole)

		self.header_list.blockSignals(True)
		self.header_list.clear()

		for name, kind in self.header_keys:
			label = f"{name}" if name != "<GLOBAL>" else "<GLOBAL>"
			it = QListWidgetItem(label)
			it.setData(Qt.UserRole, (name, kind))
			self.header_list.addItem(it)

		if prev_data:
			for i in range(self.header_list.count()):
				if self.header_list.item(i).data(Qt.UserRole) == prev_data:
					self.header_list.setCurrentRow(i)
					break
		elif self.header_keys:
			self.header_list.setCurrentRow(0)

		self.header_list.blockSignals(False)

		sel = self.header_list.currentRow()
		if sel >= 0:
			key = self.header_list.item(sel).data(Qt.UserRole)
			self.populate_and_reapply(key)


# ------------------------------------------------------------
# Combined tabbed dialog
# ------------------------------------------------------------

class BindingsEditorDialog(QDialog):
	"""
    Tab 1: DrawIndexed (your current class, moved into QWidget)
    Tab 2: Textures
    """

	def __init__(self, ini_text, parent=None, filename=None, saved_edits=None):
		super().__init__(parent)

		if saved_edits is None or filename == "":
			saved_edits = {}

		self.setWindowTitle("Bindings Editor")
		self.resize(1100, 760)

		self.parent = parent
		self.filename = filename
		self.ini_text = ini_text
		self.saved_edits = saved_edits

		layout = QVBoxLayout(self)

		self.tabs = QTabWidget()
		layout.addWidget(self.tabs)

		# Tab 1: your existing DrawIndexed page
		self.draw_page = DrawIndexedPage(self.ini_text, parent = self.parent, filename = self.filename,
										 saved_edits = self.saved_edits)
		self.tabs.addTab(self.draw_page, "DrawIndexed")

		# Tab 2: textures
		self.texture_page = TextureEditorPage(self.ini_text, parent = self.parent, filename = self.filename,
											  saved_edits = self.saved_edits)
		self.tabs.addTab(self.texture_page, "Textures")

		# bottom row
		btn_row = QHBoxLayout()
		self.btn_apply_all = QPushButton("Apply")
		self.btn_close = QPushButton("Close")
		btn_row.addWidget(self.btn_apply_all)
		btn_row.addWidget(self.btn_close)
		layout.addLayout(btn_row)

		self.btn_apply_all.clicked.connect(self.apply_all)
		self.btn_close.clicked.connect(self.accept)

		if self.parent is not None:
			setattr(self.parent, "bindings_dialog", self)

	def apply_all(self):
		# DrawIndexed page must expose apply_edits_to_parent()
		if hasattr(self.draw_page, "apply_edits_to_parent"):
			self.draw_page.apply_edits_to_parent()

		if hasattr(self.texture_page, "apply_edits_to_parent"):
			self.texture_page.apply_edits_to_parent()

		# refresh both pages from current ini text
		if hasattr(self.parent, "ini_editor"):
			new_text = self.parent.ini_editor.toPlainText()
			if hasattr(self.draw_page, "refresh_from_ini"):
				self.draw_page.refresh_from_ini(new_text)
			if hasattr(self.texture_page, "refresh_from_ini"):
				self.texture_page.refresh_from_ini(new_text)


# -------------------- Dialog class --------------------
class DrawIndexedPage(QWidget):
	def __init__(self, ini_text, parent=None, filename=None, saved_edits=None):
		super().__init__(parent)

		if saved_edits is None or filename == "":
			saved_edits = {}

		self.setWindowTitle("Conditions Editor")
		self.resize(800, 600)

		self.parent = parent
		self.filename = filename
		self.ini_text = ini_text

		# JSON-safe structure:
		# saved_edits[filename][header_name][san][vidx] = {...}
		self.saved_edits = saved_edits

		# parse blocks
		self.blocks_by_header = find_drawindexed_blocks(self.ini_text)
		self.header_keys = sorted(self.blocks_by_header.keys(), key = lambda x: (x[0] != "<GLOBAL>", x[0].lower()))

		# --- UI ---
		layout = QVBoxLayout(self)

		layout.addWidget(QLabel("Section (Header)"))
		self.header_list = QListWidget()
		for name, kind in self.header_keys:
			label = f"{name}" if name != "<GLOBAL>" else "<GLOBAL>"
			it = QListWidgetItem(label)
			it.setData(Qt.UserRole, (name, kind))
			self.header_list.addItem(it)
		layout.addWidget(self.header_list)

		layout.addWidget(QLabel("DrawIndexed Blocks"))
		self.block_list = QListWidget()
		self.block_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
		layout.addWidget(self.block_list)

		self.create_conditions_btn = QPushButton("Create Comments-based Conditions for Selected")
		layout.addWidget(self.create_conditions_btn)
		self.create_conditions_btn.clicked.connect(self.create_conditions_from_comments)

		mono = QFont("Consolas")
		mono.setPointSize(10)
		self.block_list.setFont(mono)

		layout.addWidget(QLabel("Comment"))
		self.comment_edit = QLineEdit()
		layout.addWidget(self.comment_edit)
		layout.addWidget(QLabel("DrawIndexed"))
		self.draw_edit = QLineEdit()
		layout.addWidget(self.draw_edit)
		layout.addWidget(QLabel("Condition (if)"))

		def extract_variables(code, blocks_by_header):

			# -------- globals --------

			globals_found = set(re.findall(
				r"global (?:persist )?(\$[a-zA-Z]\w+)",
				code
			))

			# -------- comments → vars --------

			def sanitize(s):

				s = s or ""

				s = re.sub(r"\(.+?\)", "", s)

				s = re.sub(r"[^A-Za-z0-9]", "", s)

				return s

			def remove_digits(s):

				return re.sub(r"\d+$", "", s)

			comment_vars = set()

			for blocks in blocks_by_header.values():

				for b in blocks:

					name = b.get("comment") or b.get("draw") or ""

					san = sanitize(name)

					base = remove_digits(san)

					if not base:
						continue

					var = base.capitalize()

					if var[0].isdigit():
						var = "x" + var

					comment_vars.add("$" + var)

			# -------- merge --------

			return sorted(
				globals_found | comment_vars
			)

		self.condition_edit = AutoCompleteTextEdit(
			extract_variables(
				editor.ini_editor.toPlainText(),
				self.blocks_by_header
			)
		)

		self.condition_edit.setPlainText("")
		self.condition_edit.setFixedHeight(24)

		self.highlighter = IniHighlighter(self.condition_edit.document())

		layout.addWidget(self.condition_edit)

		self.raw_block_edit = QTextEdit()
		self.raw_block_edit.setFont(mono)
		self.raw_block_edit.setPlaceholderText("Editable")
		layout.addWidget(QLabel("Neighboring Lines"))
		layout.addWidget(self.raw_block_edit)

		self.btn_wrap_if = QPushButton("Wrap Selected / Move If")
		self.btn_wrap_if.clicked.connect(self.wrap_selected_with_if)

		row = QHBoxLayout()
		# self.save_btn = QPushButton("Save Changes (local)")
		# self.apply_btn = QPushButton("Apply Edits")
		# self.close_btn = QPushButton("Close")
		# row.addWidget(self.save_btn)
		row.addWidget(self.btn_wrap_if)
		# row.addWidget(self.apply_btn)
		# row.addWidget(self.close_btn)

		layout.addLayout(row)

		self.header_list.currentRowChanged.connect(self.update_block_list)
		self.block_list.currentRowChanged.connect(self.load_block_fields)
		# self.save_btn.clicked.connect(self.save_changes_local)
		# self.apply_btn.clicked.connect(self.apply_edits_to_parent)
		# self.close_btn.clicked.connect(self.accept)

		if self.header_keys:
			self.header_list.setCurrentRow(0)
			self.update_block_list(0)

		if self.parent is not None:
			setattr(self.parent, "bindings_dialog", self)

	def _extract_core_block_from_preview(self, preview_text: str, block: dict) -> str:
		preview_text = (preview_text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		if not preview_text.strip():
			return block.get("text", "") or ""

		# 1) Jeśli oryginalny blok dalej siedzi w preview 1:1, bierz go bez kombinowania
		original = (block.get("text", "") or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		if original and original in preview_text:
			return original

		lines = preview_text.split("\n")

		# 2) Szukaj drawindexed z aktualnego bloku
		draw = (block.get("draw", "") or "").strip()
		draw_norm = re.sub(r"\s+", " ", draw).lower()

		def line_is_draw_match(line: str) -> bool:
			s = re.sub(r"\s+", " ", (line or "").strip()).lower()
			if not s.startswith("drawindexed"):
				return False
			# akceptuj zarówno samą wartość, jak i pełną linię
			if draw_norm:
				return draw_norm in s
			return True

		# 3) Jeśli jest komentarz, to użyj go jako dodatkowego haka
		comment = (block.get("comment", "") or "").strip().lower()

		best_start = None
		best_end = None

		for i, line in enumerate(lines):
			if not line_is_draw_match(line):
				continue

			start = i

			# jeśli bezpośrednio nad draw jest komentarz, weź go też
			if start > 0 and lines[start - 1].strip().startswith(";"):
				start -= 1

			# spróbuj złapać otaczający IF tylko jeśli faktycznie jest częścią tego fragmentu
			j = start - 1
			while j >= 0:
				s = lines[j].strip().lower()

				if re.fullmatch(r"\[[^\]]+\]", lines[j].strip()):
					break
				if s.startswith("if "):
					start = j
					break
				if s == "endif":
					break
				if s.startswith(";") and comment and comment not in s:
					break
				if s.startswith("drawindexed"):
					break

				j -= 1

			end = i + 1

			# jeśli zaczęliśmy od IF, to domknij go do matching endif
			if lines[start].strip().lower().startswith("if "):
				depth = 0
				for k in range(start, len(lines)):
					s = lines[k].strip().lower()
					if s.startswith("if "):
						depth += 1
					elif s == "endif":
						depth -= 1
						if depth == 0:
							end = k + 1
							break

			best_start = start
			best_end = end
			break

		if best_start is not None:
			return "\n".join(lines[best_start:best_end]).strip("\n")

		# 4) Fallback: zwróć sam preview, ale to już ostatnia deska ratunku
		return preview_text

	def _extract_neighboring_lines(self, text: str, start: int, end: int, pad: int = 10) -> str:
		text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
		if not text:
			return ""

		lines = text.split("\n")

		# mapowanie char offset -> indeks linii
		line_starts = []
		pos = 0
		for line in lines:
			line_starts.append(pos)
			pos += len(line) + 1

		def char_to_line_index(char_pos: int) -> int:
			if char_pos <= 0:
				return 0
			lo, hi = 0, len(line_starts) - 1
			while lo <= hi:
				mid = (lo + hi) // 2
				if line_starts[mid] <= char_pos:
					lo = mid + 1
				else:
					hi = mid - 1
			return max(0, min(hi, len(lines) - 1))

		def is_boundary_line(line: str) -> bool:
			s = (line or "").strip()
			if not s:
				return False

			ls = s.lower()

			# nowa sekcja
			if re.fullmatch(r"\[[^\]]+\]", s):
				return True

			# nowy blok logiczny
			if ls.startswith("if "):
				return True

			if ls.startswith("else "):
				return True

			if ls.startswith("elif "):
				return True

			if ls.startswith("endif"):
				return True

			# nowy blok DrawIndexed / komentarz
			if s.startswith(";"):
				return True

			if ls.startswith("drawindexed"):
				return True

			return False

		start_line = char_to_line_index(start)
		end_line = char_to_line_index(max(start, end - 1))

		left = max(0, start_line - pad)
		right = min(len(lines), end_line + pad + 1)

		# utnij z lewej na pierwszym obcym bloku
		for i in range(start_line - 1, left - 1, -1):
			if is_boundary_line(lines[i]):
				left = i + 1
				break

		# utnij z prawej na pierwszym obcym bloku
		for i in range(end_line + 1, right):
			if is_boundary_line(lines[i]):
				right = i
				break

		window = lines[left:right]

		# usuń puste brzegi
		while window and not window[0].strip():
			window.pop(0)
		while window and not window[-1].strip():
			window.pop()

		if not window:
			window = lines[start_line:end_line + 1]

		return "\n".join(window).rstrip("\n")

	def _normalize_cond_key(self, cond: str) -> str:
		cond = (cond or "").strip()
		if cond.lower().startswith("if "):
			cond = cond[3:].strip()
		if cond.startswith("$"):
			cond = cond[1:].strip()
		return re.sub(r"\s+", " ", cond).lower()

	def _find_outer_if_block(self, lines, preferred_cond: str = ""):
		"""
        Zwraca (if_start, endif_end, normalized_cond) dla pierwszego pasującego IF.
        Najpierw próbuje znaleźć IF z condition_edit, potem bierze pierwszy IF w tekście.
        """
		preferred = self._normalize_cond_key(preferred_cond)

		def scan(match_preferred_first: bool):
			for start in range(len(lines)):
				first = lines[start].strip()
				if not first.lower().startswith("if "):
					continue

				cond = self._normalize_cond_key(first[3:])
				if match_preferred_first and preferred and cond != preferred:
					continue

				depth = 0
				for end in range(start, len(lines)):
					s = lines[end].strip().lower()
					if s.startswith("if "):
						depth += 1
					elif s == "endif":
						depth -= 1
						if depth == 0:
							return start, end, cond
			return None

		return scan(True) or scan(False)

	def _find_selected_line_range(self, lines, selected_text: str):
		"""
        Próbuje znaleźć zaznaczony tekst jako zakres linii w całym buforze.
        Zwraca (start, end, selected_lines) albo None.
        """
		selected_text = (selected_text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u2029", "\n")
		selected_text = selected_text.strip("\n")
		if not selected_text:
			return None

		sel_lines = selected_text.split("\n")

		while sel_lines and not sel_lines[0].strip():
			sel_lines.pop(0)
		while sel_lines and not sel_lines[-1].strip():
			sel_lines.pop()

		if not sel_lines:
			return None

		n = len(lines)
		m = len(sel_lines)

		for i in range(n - m + 1):
			chunk = lines[i:i + m]
			if [c.strip() for c in chunk] == [s.strip() for s in sel_lines]:
				return i, i + m, sel_lines

		if m == 1:
			target = sel_lines[0].strip()
			for i, line in enumerate(lines):
				if line.strip() == target:
					return i, i + 1, sel_lines

		return None

	def wrap_selected_with_if(self):
		import textwrap

		text = self.raw_block_edit.toPlainText().replace("\r\n", "\n").replace("\r", "\n")
		cur = self.raw_block_edit.textCursor()

		# Bez zaznaczenia: zachowaj stare zachowanie jako fallback
		if not cur.hasSelection():
			raw = text.strip("\n")
			if not raw:
				return
			self.raw_block_edit.setPlainText(
				self._apply_condition_to_raw_text(raw, self.condition_edit.toPlainText())
			)
			return

		selected = cur.selectedText().replace("\u2029", "\n").strip("\n")
		if not selected:
			return

		lines = text.split("\n")
		sel_info = self._find_selected_line_range(lines, selected)

		# Jeśli nie umiemy znaleźć zaznaczenia jako linii, zrób fallback
		if not sel_info:
			wrapped = self._apply_condition_to_raw_text(selected, self.condition_edit.toPlainText())
			cur.beginEditBlock()
			cur.insertText(wrapped)
			cur.endEditBlock()
			return

		sel_start, sel_end, sel_lines = sel_info

		# Szukamy istniejącego IF, do którego mamy wpiąć zaznaczenie
		outer = self._find_outer_if_block(lines, self.condition_edit.toPlainText())

		# Jeśli nie ma IF-a, wracamy do zwykłego wrapa
		if not outer:
			wrapped = self._apply_condition_to_raw_text(selected, self.condition_edit.toPlainText())
			cur.beginEditBlock()
			cur.insertText(wrapped)
			cur.endEditBlock()
			return

		if_start, if_end, _ = outer

		# Jeśli zaznaczenie już jest wewnątrz tego IF-a, nic nie rób
		if if_start < sel_start and sel_end < if_end:
			return

		# Wcięcie bierzemy z pierwszej niepustej linii body
		body_indent = ""
		for i in range(if_start + 1, if_end):
			if lines[i].strip():
				body_indent = re.match(r"\s*", lines[i]).group(0)
				break
		if not body_indent:
			body_indent = "\t"

		# Dedent zaznaczenia, potem wklej z wcięciem body
		moved_block = textwrap.dedent("\n".join(sel_lines)).strip("\n")
		moved_lines = moved_block.split("\n")
		moved_lines = [
			(body_indent + ln if ln.strip() else "")
			for ln in moved_lines
		]

		new_lines = lines[:]

		# Usuwamy zaznaczenie od końca
		for i in range(sel_end - 1, sel_start - 1, -1):
			del new_lines[i]

		# Jeśli zaznaczenie było przed IF-em, indeks IF-a się przesuwa
		removed_before = (sel_end - sel_start) if sel_end <= if_start else 0
		new_if_start = if_start - removed_before

		insert_at = new_if_start + 1

		# Wstawiamy zaznaczony blok na początek body IF-a, przed komentarzem / drawindexed
		insertion = moved_lines + [""]
		new_lines[insert_at:insert_at] = insertion

		self.raw_block_edit.setPlainText("\n".join(new_lines).rstrip("\n"))

	def _split_outer_if_block(self, text: str):
		"""
        Zwraca:
          (is_if_block, condition, body)
        Obsługuje prosty blok:
          if ...
              ...
          endif
        """
		raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		lines = raw.split("\n")

		if len(lines) < 3:
			return False, "", text or ""

		first = lines[0].strip()
		last = lines[-1].strip().lower()

		if not first.lower().startswith("if ") or last != "endif":
			return False, "", text or ""

		cond = first[3:].strip()
		body = "\n".join(lines[1:-1]).strip("\n")
		return True, cond, body

	def _apply_condition_to_raw_text(self, raw_text: str, cond: str) -> str:
		"""
        Jedno miejsce prawdy:
          - jeśli cond istnieje -> if/wstaw albo podmień istniejący if
          - jeśli cond puste -> usuń if, jeśli był
        """
		raw_text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		cond = (cond or "").strip()

		is_if, old_cond, body = self._split_outer_if_block(raw_text)

		if cond:
			if not cond.startswith("$"):
				cond = "$" + cond
			if is_if:
				return f"if {cond}\n{body}\nendif"
			return f"if {cond}\n{raw_text}\nendif"

		# brak cond -> unwrap, jeśli blok był if-em
		return body if is_if else raw_text

	def _strip_outer_if(self, text: str) -> str:
		text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		lines = text.split("\n")

		if len(lines) >= 3 and lines[0].strip().lower().startswith("if ") and lines[-1].strip().lower() == "endif":
			return "\n".join(lines[1:-1]).strip("\n")

		return text

	def _build_effective_block(self, block, ed=None):
		"""
        Buduje finalny tekst bloku:
          1) raw_text jest tylko podglądem / oknem
          2) z raw_text wyciągamy właściwy blok
          3) condition działa tylko raz
          4) gdy raw_text puste, składamy blok z comment/draw/condition
        """
		ed = ed or {}

		comment = (ed.get("comment", block.get("comment", "")) or "").strip()
		draw = (ed.get("draw", block.get("draw", "")) or "").strip()
		cond = (ed.get("condition", block.get("condition", "")) or "").strip()
		raw_text = (ed.get("raw_text", "") or "").strip("\n")

		if raw_text.strip():
			core = self._extract_core_block_from_preview(raw_text, block)
			core = self._strip_outer_if(core).strip("\n")
			return self._normalize_block_text(self._apply_condition_to_raw_text(core, cond))

		if cond and not cond.startswith("$"):
			cond = "$" + cond

		lines = []
		if cond:
			lines.append(f"if {cond}")
			if comment:
				lines.append(f"    ; {comment}")
			lines.append(f"    drawindexed = {draw}")
			lines.append("endif")
		else:
			if comment:
				lines.append(f"; {comment}")
			lines.append(f"drawindexed = {draw}")

		return self._normalize_block_text("\n".join(lines))

	def _normalize_block_text(self, text: str) -> str:
		text = (text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
		if not text:
			return ""
		return text + "\n\n"

	def _get_block_and_edit(self, idx=None):
		if idx is None:
			idx = self.block_list.currentRow()
		if idx < 0:
			return None, None, None, None, None

		it = self.block_list.item(idx)
		if not it:
			return None, None, None, None, None

		header_key, block = it.data(Qt.UserRole)
		if isinstance(header_key, list):
			header_key = tuple(header_key)

		name, kind = header_key
		san = block.get("san")
		vidx = block.get("variant_index", 0)
		header_edits = self._get_header_edits(name, san)
		ed = header_edits.get(vidx, {})
		return header_key, block, ed, san, vidx

	def _compose_fallback_block(self, block, ed):
		comment = (ed.get("comment", block.get("comment", "")) if ed else block.get("comment", ""))
		draw = (ed.get("draw", block.get("draw", "")) if ed else block.get("draw", ""))
		cond = (ed.get("condition", block.get("condition", "")) if ed else block.get("condition", ""))

		comment = (comment or "").strip()
		draw = (draw or "").strip()
		cond = (cond or "").strip()

		if draw.lower().startswith("drawindexed"):
			draw = draw.split("=", 1)[1].strip()

		lines = []
		if cond:
			if not cond.lower().startswith("$"):
				cond = "$" + cond
			lines.append(f"if {cond}")
			if comment:
				lines.append(f"    ; {comment}")
			lines.append(f"    drawindexed = {draw}")
			lines.append("endif")
		else:
			if comment:
				lines.append(f"; {comment}")
			lines.append(f"drawindexed = {draw}")

		return self._normalize_block_text("\n".join(lines))

	def _load_raw_from_selected(self):
		idx = self.block_list.currentRow()
		if idx < 0:
			return

		_, block, ed, _, _ = self._get_block_and_edit(idx)
		if block is None:
			return

		raw_text = (ed.get("raw_text", "") if ed else "").strip("\n")
		if not raw_text:
			raw_text = block.get("text", "")

		self.raw_block_edit.setPlainText(raw_text)
		self.preview_edit.setPlainText(
			self._compose_fallback_block(block, ed) if not raw_text.strip() else self._normalize_block_text(raw_text))

	def _wrap_selection_with_if(self):
		cur = self.raw_block_edit.textCursor()

		if cur.hasSelection():
			selected = cur.selectedText().replace("\u2029", "\n")
		else:
			selected = self.raw_block_edit.toPlainText()

		selected = selected.strip("\n")
		if not selected:
			return

		cond = self.condition_edit.toPlainText().strip() or "$Var"
		if not cond.lower().startswith("$"):
			cond = "$" + cond

		wrapped = f"if {cond}\n{selected}\nendif"
		cur.beginEditBlock()
		if cur.hasSelection():
			cur.insertText(wrapped)
		else:
			self.raw_block_edit.setPlainText(wrapped)
		cur.endEditBlock()

		self.preview_edit.setPlainText(self._normalize_block_text(self.raw_block_edit.toPlainText()))

	def _unwrap_if_block(self):
		text = self.raw_block_edit.toPlainText().replace("\r\n", "\n").replace("\r", "\n").strip("\n")
		lines = text.split("\n")
		if len(lines) >= 3 and lines[0].strip().lower().startswith("if ") and lines[-1].strip().lower().startswith(
				"endif"):
			text = "\n".join(lines[1:-1]).strip("\n")
			self.raw_block_edit.setPlainText(text)
			self.preview_edit.setPlainText(self._normalize_block_text(text))

	def create_conditions_from_comments(self):

		items = self.block_list.selectedItems()

		if not items:
			QMessageBox.information(self, "No selection", "No blocks selected.")
			return

		# ---------- helpers ----------

		def sanitize(s):

			s = s or ""

			s = re.sub(r"\(.+?\)", "", s)

			s = re.sub(r"[^A-Za-z0-9]", "", s)

			return s.lower()

		def remove_digits(s):

			return re.sub(r"\d+$", "", s)

		def is_autogen(cond, var):

			if not cond:
				return False

			cond = cond.strip()

			if cond == f"${var}":
				return True

			return bool(
				re.fullmatch(
					rf"\${re.escape(var)}\s*==\s*\d+",
					cond
				)
			)

		def autogen_index(cond, var):

			cond = cond.strip()

			if cond == f"${var}":
				return 0

			m = re.fullmatch(
				rf"\${re.escape(var)}\s*==\s*(\d+)",
				cond
			)

			if m:
				return int(m.group(1))

			return None

		# ---------- group selected ----------

		groups = {}

		for it in items:
			header_key, b = it.data(Qt.UserRole)

			name_raw = b.get("comment") or b.get("draw") or ""

			san = b.get("san") or sanitize(name_raw)

			base = remove_digits(san)

			key = (tuple(header_key), base)

			groups.setdefault(key, []).append(b)

		changed = []

		# ---------- process groups ----------

		for (header_key, base), selected_blocks in groups.items():

			header_name, header_kind = header_key

			# variable name

			var = re.sub(r"[^A-Za-z0-9]", "", base)

			if not var:
				var = "var"

			if var[0].isdigit():
				var = "x" + var

			var = var.capitalize()

			# ---------- find ALL blocks in header ----------

			all_blocks = []

			for b in self.blocks_by_header.get(header_key, []):

				if b.get("san") == base:
					all_blocks.append(b)

			# ---------- detect existing autogen ----------

			existing_indices = set()

			for b in all_blocks:

				san = b.get("san")

				vidx = b.get("variant_index", 0)

				header_edits = self._get_header_edits(header_name, san)

				cond = header_edits.get(vidx, {}).get(
					"condition",
					b.get("condition", "")
				)

				idx = autogen_index(cond, var)

				if idx is not None:
					existing_indices.add(idx)

			# ---------- assign ----------

			for b in selected_blocks:

				san = b.get("san")

				vidx = b.get("variant_index", 0)

				slot = self._ensure_header_slot(header_name, san)

				existing_draw = slot.get(
					vidx,
					{}
				).get(
					"draw",
					b.get("draw", "")
				)

				existing_comment = slot.get(
					vidx,
					{}
				).get(
					"comment",
					b.get("comment", "")
				)

				# current condition

				current_cond = slot.get(
					vidx,
					{}
				).get(
					"condition",
					b.get("condition", "")
				)

				# don't overwrite manual

				if current_cond and not is_autogen(current_cond, var):
					continue

				# next index

				if not existing_indices:

					cond = f"${var}"

					existing_indices.add(0)

				else:

					next_i = max(existing_indices) + 1

					cond = f"${var} == {next_i}"

					existing_indices.add(next_i)

				slot[vidx] = {

					"comment": existing_comment,

					"draw": existing_draw,

					"condition": cond

				}

				changed.append(
					(header_key, san, vidx)
				)

			# ------------------------
			# Normalize bare "$Var" to "$Var == 0" when there are multiple autogen indices
			# (this fixes the case: first got "if $Bow", second got "if $Bow == 1" but first
			#  wasn't updated to "if $Bow == 0")
			# ------------------------

			# ensure we operate on the actual saved slot dict
			slot = self._ensure_header_slot(header_name, base)

			# collect autogen entries: index -> (vidx, cond)
			auto_entries = {}

			# include blocks known from file
			for b2 in all_blocks:
				vid = b2.get("variant_index", 0)
				cond = slot.get(vid, {}).get("condition", b2.get("condition", ""))
				idx = autogen_index(cond, var)
				if idx is not None:
					auto_entries[idx] = (vid, cond)

			# also include any entries only present in saved edits (slot)
			for vid, val in list(slot.items()):
				cond = val.get("condition", "")
				idx = autogen_index(cond, var)
				if idx is not None:
					auto_entries[idx] = (vid, cond)

			# if more than one autogen index exists, convert bare "$Var" -> "$Var == 0"
			if len(auto_entries) > 1 and 0 in auto_entries:
				vid0, cond0 = auto_entries[0]
				if cond0.strip() == f"${var}":
					slot.setdefault(vid0, {})
					slot[vid0]['condition'] = f"${var} == 0"

		# ---------- refresh ----------

		cur_row = self.header_list.currentRow()

		if 0 <= cur_row < self.header_list.count():
			key = self.header_list.item(cur_row).data(Qt.UserRole)

			self.populate_and_reapply(key)

		editor.statusBar().showMessage(f"Updated {len(changed)} If Block(s).", 3000)
		# QMessageBox.information(

	#
	#    self,
	#
	#    "Conditions created",
	#
	#    f"Updated {len(changed)} block(s)."
	#
	# )

	# --- helpers for saved_edits ---

	def _get_header_edits(self, header_name, san):
		if not self.filename:
			return {}

		return self.saved_edits \
			.get(self.filename, {}) \
			.get(header_name, {}) \
			.get(san, {})

	def _ensure_header_slot(self, header_name, san):
		self.saved_edits.setdefault(self.filename, {})
		self.saved_edits[self.filename].setdefault(header_name, {})
		self.saved_edits[self.filename][header_name].setdefault(san, {})
		return self.saved_edits[self.filename][header_name][san]

	# --- UI helpers ---

	def update_block_list(self, idx):
		self.block_list.clear()
		if idx < 0 or idx >= len(self.header_keys):
			return
		header_key = self.header_keys[idx]
		self.populate_and_reapply(header_key)

	def _label_for_block(self, b, header_key):
		name, kind = header_key
		san = b.get("san", "unknown")
		vidx = b.get("variant_index", 0)

		header_edits = self._get_header_edits(name, san)

		edited = vidx in header_edits
		if edited:
			ed = header_edits[vidx]
			comment = ed.get("comment", b.get("comment", ""))
			draw = ed.get("draw", b.get("draw", ""))
			cond = ed.get("condition", b.get("condition", ""))
		else:
			comment = b.get("comment", "")
			draw = b.get("draw", "")
			cond = b.get("condition", "")

		flag = "* " if edited else ""
		if_flag = "if " if cond else ""

		# skróć komentarz żeby nie rozjeżdżał listy
		if len(comment) > 25:
			comment = comment[:22] + "..."

		return f"{flag}{if_flag}{cond + ' | ' if cond else ''}{comment} -> {draw} | {san}[{vidx}]"

	def load_block_fields(self, idx):
		if idx < 0:
			self.comment_edit.clear()
			self.draw_edit.clear()
			self.condition_edit.clear()
			self.raw_block_edit.clear()
			return

		item = self.block_list.item(idx)
		header_key, block = item.data(Qt.UserRole)

		name, kind = header_key
		san = block.get("san")
		vidx = block.get("variant_index", 0)

		header_edits = self._get_header_edits(name, san)
		ed = header_edits.get(vidx, {})

		raw_draw = (ed.get("draw", block.get("draw", "")) or "").strip()
		if raw_draw.lower().startswith("drawindexed"):
			raw_draw = raw_draw.split("=", 1)[1].strip()

		self.comment_edit.setText(ed.get("comment", block.get("comment", "")))
		self.draw_edit.setText(raw_draw)

		# condition bierze się z editów albo z bloku
		self.condition_edit.setText(ed.get("condition", block.get("condition", "")))

		# raw text: jeśli było zapisane, bierzemy je; jeśli nie, używamy oryginalnego bloku
		raw_text = ed.get("raw_text", "") or ""

		if not raw_text.strip():
			raw_text = self._extract_neighboring_lines(
				self.ini_text,
				block.get("start", 0),
				block.get("end", 0),
				pad = 10
			)

		self.raw_block_edit.setPlainText(raw_text.rstrip("\n"))

	# --- local save ---

	def save_changes_local(self):
		idx = self.block_list.currentRow()
		if idx < 0:
			return

		it = self.block_list.item(idx)
		header_key, block = it.data(Qt.UserRole)

		name, kind = header_key
		san = block.get("san")
		vidx = block.get("variant_index", 0)

		raw_draw = self.draw_edit.text().strip()
		if raw_draw.lower().startswith("drawindexed"):
			raw_draw = raw_draw.split("=", 1)[1].strip()

		raw_text = self.raw_block_edit.toPlainText().strip("\n")
		cond = self.condition_edit.toPlainText().strip()

		slot = self._ensure_header_slot(name, san)
		slot[vidx] = {
			"comment": self.comment_edit.text().strip(),
			"draw": raw_draw,
			"condition": cond,
			"raw_text": raw_text
		}

		it.setText(self._label_for_block(block, header_key))

	# --- apply edits to parent INI ---

	def apply_edits_to_parent(self):
		self.save_changes_local()

		if not (self.parent and hasattr(self.parent, "ini_editor")):
			QMessageBox.warning(self, "No parent", "Parent editor not available.")
			return

		if editor:
			editor.allow_alert = False
			editor.rebuild_ini(False)

		base_text = self.parent.ini_editor.toPlainText()
		current_blocks = find_drawindexed_blocks(base_text)
		replacements = []

		for header_key, blist in current_blocks.items():
			header_name, header_kind = header_key

			for b in blist:
				san = b.get("san")
				vidx = b.get("variant_index", 0)

				header_edits = self._get_header_edits(header_name, san)
				if vidx not in header_edits:
					continue

				ed = header_edits[vidx]
				new_text = self._build_effective_block(b, ed)
				replacements.append((b["start"], b["end"], new_text))

		replacements.sort(key = lambda x: x[0], reverse = True)

		new_text = base_text
		for s, e, repl in replacements:
			new_text = new_text[:s] + repl + new_text[e:]

		self.parent.ini_editor.setPlainText(new_text)
		self.refresh_from_ini(new_text)

	# --- refresh dialog ---

	def refresh_from_ini(self, new_ini_text: str):
		self.ini_text = new_ini_text
		self.blocks_by_header = find_drawindexed_blocks(self.ini_text)
		self.header_keys = sorted(self.blocks_by_header.keys(), key = lambda x: (x[0] != "<GLOBAL>", x[0].lower()))

		prev_data = None
		cur_row = self.header_list.currentRow()
		if 0 <= cur_row < self.header_list.count():
			prev_data = self.header_list.item(cur_row).data(Qt.UserRole)

		self.header_list.blockSignals(True)
		self.header_list.clear()

		for name, kind in self.header_keys:
			label = f"{name}" if name != "<GLOBAL>" else "<GLOBAL>"
			it = QListWidgetItem(label)
			it.setData(Qt.UserRole, (name, kind))
			self.header_list.addItem(it)

		if prev_data:
			for i in range(self.header_list.count()):
				if self.header_list.item(i).data(Qt.UserRole) == prev_data:
					self.header_list.setCurrentRow(i)
					break
		elif self.header_keys:
			self.header_list.setCurrentRow(0)

		self.header_list.blockSignals(False)

		sel = self.header_list.currentRow()
		if sel >= 0:
			key = self.header_list.item(sel).data(Qt.UserRole)
			self.populate_and_reapply(key)

	# --- populate block list ---

	def populate_and_reapply(self, header_key):
		if isinstance(header_key, list):
			header_key = tuple(header_key)

		self.block_list.clear()
		blist = self.blocks_by_header.get(header_key, [])

		name, kind = header_key

		for b in blist:
			san = b.get("san")
			vidx = b.get("variant_index", 0)

			header_edits = self._get_header_edits(name, san)

			if vidx in header_edits:
				ed = header_edits[vidx]
				label = f"* {'if ' + ed.get('condition') + ' | ' if ed.get('condition', None) else ''}{ed.get('comment', '')} -> {ed.get('draw', '')} | {san}[{vidx}]"
			else:
				label = self._label_for_block(b, header_key)

			it = QListWidgetItem(label)
			it.setData(Qt.UserRole, (header_key, b))
			self.block_list.addItem(it)

		if blist:
			self.block_list.setCurrentRow(0)


class CursorOverlay(QLabel):
	def __init__(self, parent=None):
		super().__init__(parent)

		self.setWindowFlags(
			Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
		)
		self.setAttribute(Qt.WA_TransparentForMouseEvents)
		self.setAttribute(Qt.WA_ShowWithoutActivating)

		self.setStyleSheet("""
            QLabel {
                background-color: rgba(30, 30, 30, 200);
                color: white;
                padding: 4px 8px;
                border-radius: 6px;
                font-size: 10pt;
            }
        """)

		self.hide()

	def update_text(self, text, global_pos):
		self.setText(text)
		self.adjustSize()

		# lekkie przesunięcie żeby nie zasłaniać kursora
		self.move(global_pos + QPoint(12, 12))

		if not self.isVisible():
			self.show()


class MenuEditor(QMainWindow):
	def __init__(self):
		super().__init__()
		self.setWindowTitle(f"Menu Creator V{VERSION} - by Nurarihyon")

		screen = QGuiApplication.primaryScreen()
		screen_size = screen.size()
		self.screen_width = screen_size.width()
		self.screen_height = screen_size.height()

		main_widget = QWidget()
		self.setCentralWidget(main_widget)
		main_layout = QHBoxLayout(main_widget)

		self.cursor_overlay = CursorOverlay()

		self.types = []
		self.code_elements = []
		self.post_commands = []

		self.saved_edits = {}
		self.saved_edits.setdefault('', {})

		self.pixmap_cache = {}
		self.loading_data = False

		self.auto_if = True

		# ---------------- UNDO/REDO ----------------
		self.allow_rebuild_ini = True
		self.allow_alert = True

		# w __init__ po stworzeniu undo_stack:
		self.undo_stack = QUndoStack(self)
		# connect using lambda to be safe (omija potrzebę @Slot)
		self.undo_stack.indexChanged.connect(lambda idx: self._on_undo_index_changed(idx))

		self._undo_action = self.undo_stack.createUndoAction(self, "Undo")
		self._undo_action.setShortcut(QKeySequence.Undo)
		self.addAction(self._undo_action)

		self._redo_action = self.undo_stack.createRedoAction(self, "Redo")
		# pozwól na Ctrl+Y oraz systemowy Redo
		self._redo_action.setShortcuts(QKeySequence.Redo)
		self.addAction(self._redo_action)

		# małe stany pomocnicze
		self._ui_changing = False  # blokada przy programowych ustawieniach widgetów
		self._field_start_values = {}  # przechowuje "old" dla suwaka/fokusów

		self.pages = []
		self.groups = {"ROOT_ALWAYS": []}

		self.load_types()

		self.ini_original_text = ''
		self.current_ini_path = None
		self.current_template_image_path = ''

		# ---------------- DATA ----------------
		self.keybinds = KeyBindingsManager()

		self.current_pixmap = None
		self.templates = []
		self.display_items = []
		self.last_selected = None
		self.active_item = None

		# editing state
		self.edit_mode = None
		self.edit_items = []
		self.start_item_states = {}
		self.item_mouse_offsets = []
		self.start_pos = None
		self.lock_x = False
		self.lock_z = False
		self.lock_aspect = False
		self.grid_size = 16

		if cfg.get('first_run', 1) == 1:
			QTimer.singleShot(200, self.show_welcome)
			save_config(cfg)

		# ---------------- LEFT PANEL ----------------
		self.left_panel = QWidget()
		self.left_panel.setMaximumWidth(280)
		left_layout = QVBoxLayout(self.left_panel)

		self.element_name_input = QLineEdit()
		self.element_name_input.setPlaceholderText("Template Element Name")
		left_layout.addWidget(self.element_name_input)

		self.type_combo = QComboBox()
		self.refresh_type_combo(False)
		left_layout.addWidget(self.type_combo)

		btn = QPushButton("Edit Types")
		btn.clicked.connect(self.open_type_editor)
		left_layout.addWidget(btn)

		self.select_image_button = QPushButton("Select Image")
		self.select_image_button.clicked.connect(self.select_image)
		left_layout.addWidget(self.select_image_button)

		self.image_path_label = QLabel("No Image Selected")
		left_layout.addWidget(self.image_path_label)

		self.width_input = QLineEdit()
		self.width_input.setPlaceholderText("Width (px)")
		left_layout.addWidget(self.width_input)

		self.height_input = QLineEdit()
		self.height_input.setPlaceholderText("Height (px)")
		left_layout.addWidget(self.height_input)

		self.add_template_button = QPushButton("➕ Create Template Element")
		self.add_template_button.clicked.connect(self.add_template_element)
		left_layout.addWidget(self.add_template_button)

		self.delete_template_button = QPushButton("❌ Delete Selected Template")
		self.delete_template_button.clicked.connect(self.delete_selected_template_element)
		left_layout.addWidget(self.delete_template_button)

		self.update_template_button = QPushButton("✏️ Update Selected Template")
		self.update_template_button.clicked.connect(self.update_selected_template)
		left_layout.addWidget(self.update_template_button)

		self.add_to_display_button = QPushButton("➕ Add Selected Template to Display")
		self.add_to_display_button.clicked.connect(self.add_selected_template_to_display)
		left_layout.addWidget(self.add_to_display_button)

		self.template_list_widget = TemplatelistWidget()
		self.template_list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
		self.template_list_widget.itemSelectionChanged.connect(self.on_template_selection_changed)
		left_layout.addWidget(QLabel("Templates:"))
		left_layout.addWidget(self.template_list_widget)

		left_layout.addWidget(QLabel("Code Elements"))

		self.code_list = QListWidget()
		left_layout.addWidget(self.code_list)

		row = QHBoxLayout()
		add_btn = QPushButton("Add")
		edit_btn = QPushButton("Edit")
		del_btn = QPushButton("Delete")
		row.addWidget(add_btn)
		row.addWidget(edit_btn)
		row.addWidget(del_btn)
		left_layout.addLayout(row)

		add_btn.clicked.connect(self.add_code_element)
		edit_btn.clicked.connect(self.edit_code_element)
		del_btn.clicked.connect(self.delete_code_element)

		self.template_tint_slider = QSlider(Qt.Horizontal)
		self.template_tint_slider.setRange(0, 100)
		self.template_tint_slider.valueChanged.connect(self.update_selected_template_tint)
		left_layout.addWidget(QLabel("Tint % (Template):"))
		left_layout.addWidget(self.template_tint_slider)

		self.save_layout_button = QPushButton("💾 Save Custom Layout")
		self.save_layout_button.clicked.connect(self.save_custom_layout)
		left_layout.addWidget(self.save_layout_button)

		self.load_layout_button = QPushButton("📂 Load Custom Layout")
		self.load_layout_button.clicked.connect(self.load_custom_layout)
		left_layout.addWidget(self.load_layout_button)

		# ---------------- Restore Snapshot ----------------
		btn_restore = QPushButton("🔄 Load Project Data")
		btn_nuke = QPushButton("💣 New Project")

		snapshot_row = QHBoxLayout()

		snapshot_row.addWidget(btn_restore)
		snapshot_row.addWidget(btn_nuke)

		left_layout.addLayout(snapshot_row)

		# ---------------- Config Settings ----------------

		self.config_button = QPushButton("⚙ Settings / Config")
		self.config_button.clicked.connect(open_config_editor)  # Twoja funkcja UI
		left_layout.addWidget(self.config_button)

		def list_snapshots() -> list[str]:
			"""Return list of available snapshot names (without extension)."""
			if not os.path.exists(SNAPSHOT_DIR):
				return []
			files = os.listdir(SNAPSHOT_DIR)
			# tylko pliki JSON typu snapshot (np. snapshot_*.json)
			snapshots = []
			for f in files:
				snapshots.append(f[:-5])  # strip .json
			snapshots.sort()
			return snapshots

		def restore_snapshot_dialog():
			snapshots = list_snapshots()  # zwraca listę dostępnych snapshotów (nazwy/pliki)
			if not snapshots:
				QMessageBox.information(self, "No Snapshots", "No snapshots available to restore.")
				return

			dialog = QDialog(self)
			dialog.setWindowTitle("Restore Snapshot")
			layout = QVBoxLayout(dialog)

			layout.addWidget(QLabel("Select snapshot to restore:"))

			# Combobox z listą snapshotów
			combo = QComboBox()
			combo.addItems(snapshots)
			layout.addWidget(combo)

			layout.addWidget(QLabel("Select sections to restore:"))
			cb_templates = QCheckBox("Templates")
			cb_displayed = QCheckBox("Displayed Items")
			cb_code = QCheckBox("Code Elements")
			cb_types = QCheckBox("Types (non-default only)")
			cb_groups = QCheckBox("Groups")
			cb_pages = QCheckBox("Pages")

			layout.addWidget(cb_templates)
			layout.addWidget(cb_displayed)
			layout.addWidget(cb_code)
			layout.addWidget(cb_types)
			layout.addWidget(cb_groups)
			layout.addWidget(cb_pages)

			btn_restore_snap = QPushButton("Restore Selected")
			layout.addWidget(btn_restore_snap)

			def on_restore():
				sections = []
				if cb_templates.isChecked(): sections.append("templates")
				if cb_displayed.isChecked(): sections.append("display_items")
				if cb_code.isChecked(): sections.append("code_elements")
				if cb_types.isChecked(): sections.append("types")
				if cb_groups.isChecked(): sections.append("groups")
				if cb_pages.isChecked(): sections.append("pages")

				if not sections:
					QMessageBox.warning(dialog, "Nothing selected", "No sections selected to restore.")
					return

				snapshot_name = combo.currentText()
				try:
					# load snapshot content (returns dict)
					data = self.load_snapshot(snapshot_name)
				except Exception as e:
					QMessageBox.warning(dialog, "Error", f"Failed to load snapshot:\n{e}")
					return

				if not isinstance(data, dict):
					QMessageBox.warning(dialog, "Error", "Snapshot data invalid or corrupt.")
					return

				# Przywracanie sekcji selektywnie
				if "templates" in sections and "templates" in data:
					self.templates.clear()
					self.template_list_widget.clear()
					for t in data.get("templates", []):
						try:
							# attempt to load the original pixmap if path exists, otherwise create fallback pixmap
							pixmap = None
							path = t.get("path") or t.get("pixmap_path") or ""
							if path and os.path.exists(path):
								try:
									pixmap = load_pixmap_any(path, self.pixmap_cache)
								except Exception:
									pixmap = None

							if pixmap is None:
								# fallback size from saved template or sensible default
								w = int(t.get("width", 100))
								h = int(t.get("height", 50))
								pixmap = QPixmap(w, h)

							# make sure pixmap has expected size
							# pixmap = safe_scaled(pixmap, int(t.get("width", pixmap.width())),
							#                                                 int(t.get("height", pixmap.height())))

							tmpl = Template.from_dict(t, pixmap)
							self.templates.append(tmpl)
							self.template_list_widget.addItem(tmpl.name)
						except Exception as e:
							print("[WARN] failed to restore template:", e)
							# continue restoring others

				if "display_items" in sections and "display_items" in data:
					for item in list(self.display_items):
						try:
							self.scene.removeItem(item)
						except Exception:
							pass
					self.display_items.clear()
					for d in data.get("display_items", []):
						try:
							item = self._deserialize_display_item(d)
							# restore page_index/group if present (normalize happens in _load_layout_data, but we do best-effort)
							item.page_index = d.get("page_index", d.get("page", None))
							item.group = d.get("group", d.get("group_index", None))
							self.scene.addItem(item)
							self.display_items.append(item)
						except Exception as ex:
							print("[WARN] failed to deserialize display item:", ex)
					# re-resolve parents if any
					try:
						self._resolve_item_parents(self.display_items, data.get("display_items", []))
					except Exception:
						pass

				if "code_elements" in sections and "code_elements" in data:
					self.code_elements.clear()
					for ce in data.get("code_elements", []):
						try:
							self.code_elements.append(CodeElement.from_dict(ce))
						except Exception:
							print("[WARN] failed to load code element", ce)
					self.refresh_code_list()

				if "types" in sections and "types" in data:
					# Restore only non-default types
					restored_types = [t for t in data.get("types", []) if not t.get("default", False)]
					# keep default types that exist currently
					self.types = [t for t in self.types if t.get("default", False)] + restored_types

				# pages/groups/ini/ifs maybe should also be restored if present in snapshot
				if "pages" in sections and "pages" in data:
					try:
						self.pages = list(data.get("pages", []))
					except Exception:
						pass
				if "groups" in sections and "groups" in data:
					try:
						self.groups = self.deserialize_groups_from_save(data.get("groups", {}))
					except Exception:
						pass
				if "ini" in data and data.get("ini"):
					try:
						self.load_ini_file(data.get("ini"))
					except Exception:
						pass
				if "ifs" in data:
					try:
						# be defensive: data["ifs"] might be dict
						if isinstance(data.get("ifs"), dict):
							_normalize_saved_edits_vidx(data.get("ifs"))
							self.saved_edits = data.get("ifs")
						else:
							self.saved_edits = {}
					except Exception:
						pass

				try:
					self.rebuild_outliner()
					self.rebuild_ini()
				except Exception:
					pass

				self.statusBar().showMessage(f"[INFO] Snapshot '{snapshot_name}' restored for: {', '.join(sections)}",
											 3000)
				# QMessageBox.information(dialog, "Done",
				#                        f"Snapshot '{snapshot_name}' restored for: {', '.join(sections)}")
				# dialog.accept()

			btn_restore_snap.clicked.connect(on_restore)
			dialog.exec()

		def start_from_scratch_dialog():
			dialog = QDialog(self)
			dialog.setWindowTitle("Start from Scratch")
			layout = QVBoxLayout(dialog)

			layout.addWidget(QLabel("Optional snapshot name (will be used as prefix):"))
			snapshot_name_input = QLineEdit()
			snapshot_name_input.setPlaceholderText("Enter snapshot name (optional)")
			layout.addWidget(snapshot_name_input)

			layout.addWidget(QLabel("Select sections to clear:"))

			cb_templates = QCheckBox("Templates")
			cb_displayed = QCheckBox("Displayed Items")
			cb_code = QCheckBox("Code Elements")
			cb_types = QCheckBox("Types (non-default only)")
			cb_groups = QCheckBox("Groups")
			cb_pages = QCheckBox("Pages")

			layout.addWidget(cb_templates)
			layout.addWidget(cb_displayed)
			layout.addWidget(cb_code)
			layout.addWidget(cb_types)
			layout.addWidget(cb_groups)
			layout.addWidget(cb_pages)

			cb_backup = QCheckBox("Backup current state before clearing")
			cb_backup.setChecked(True)
			layout.addWidget(cb_backup)

			btn_clear = QPushButton("Clear Selected")
			layout.addWidget(btn_clear)

			def on_clear():
				sections = []
				if cb_templates.isChecked(): sections.append("templates")
				if cb_displayed.isChecked(): sections.append("display_items")
				if cb_code.isChecked(): sections.append("code_elements")
				if cb_types.isChecked(): sections.append("types")
				if cb_groups.isChecked(): sections.append("groups")
				if cb_pages.isChecked(): sections.append("pages")

				if not sections:
					QMessageBox.warning(dialog, "Nothing selected", "No sections selected to clear.")
					return

				if cb_backup.isChecked():
					name_prefix = snapshot_name_input.text().strip()
					if name_prefix:
						snap_name = f"{name_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
					else:
						snap_name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
					# save snapshot BEFORE clearing
					self.save_snapshot(name = snap_name, include = sections)

				if "templates" in sections:
					self.templates.clear()
					self.template_list_widget.clear()
				if "display_items" in sections:
					for item in list(self.display_items):
						try:
							self.scene.removeItem(item)
						except Exception:
							pass
					self.display_items.clear()
				if "code_elements" in sections:
					self.code_elements.clear()
					self.refresh_code_list()
				if "types" in sections:
					self.types = [t for t in self.types if t.get("is_default", False)]
				if "groups" in sections:
					self.groups.clear()
				if "pages" in sections:
					self.pages.clear()

				try:
					self.rebuild_outliner()
				except Exception:
					pass

				QMessageBox.information(dialog, "Done", f"Cleared sections: {', '.join(sections)}")
				dialog.accept()

			btn_clear.clicked.connect(on_clear)
			dialog.exec()

		btn_restore.clicked.connect(restore_snapshot_dialog)
		btn_nuke.clicked.connect(start_from_scratch_dialog)

		left_layout.addStretch()
		main_layout.addWidget(self.left_panel, 0)

		# ---------------- CENTER PANEL ----------------
		self.scene = QGraphicsScene(0, 0, self.screen_width, self.screen_height)
		self.scene.editor = self
		self.view = LockedView(self.scene)

		# self.h_ruler = HorizontalRuler(self.view)
		# self.v_ruler = VerticalRuler(self.view)
		#
		# self.h_ruler.raise_()
		# self.v_ruler.raise_()

		# self.view.viewChanged.connect(self.update_rulers)

		self.view.setRenderHint(QPainter.Antialiasing)
		self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.view.setMouseTracking(True)
		self.view.viewport().setMouseTracking(True)
		main_layout.addWidget(self.view, 1)

		# Right panel container
		self.right_panel = QWidget()
		self.right_layout = QVBoxLayout(self.right_panel)
		self.right_layout.setContentsMargins(5, 5, 5, 5)
		self.right_layout.setSpacing(5)

		# ---------- Displayed Elements ----------
		self.display_label = QLabel("Displayed Elements (Draggable):")
		self.outliner = OutlinerTree(
			display_items = self.display_items,
			editor = self,
			rebuild_callback = self.rebuild_outliner
		)
		self.outliner.itemChanged.connect(self.on_outliner_item_changed)
		self.outliner.itemSelectionChanged.connect(self.on_outliner_selection_changed)
		self.outliner.itemClicked.connect(self.on_outliner_item_clicked)

		# Pierwsze załadowanie
		# self.outliner.rebuild_outliner

		self.outliner_widget_clicked = False

		self.view.grid_size = self.grid_size

		# Fixed-height container
		display_container = QWidget()
		display_layout = QVBoxLayout(display_container)
		display_layout.setContentsMargins(0, 0, 0, 0)
		display_layout.setSpacing(2)
		display_layout.addWidget(self.display_label)
		display_layout.addWidget(self.outliner)

		# Allow it to expand but keep min/max height
		display_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
		display_container.setMinimumHeight(650)  # big enough by default
		display_container.setMaximumHeight(650)  # allow it to grow if panel is huge

		display_container.setMaximumWidth(180)  # same as settings panel
		self.outliner.setMaximumWidth(180)

		self.right_layout.addWidget(display_container)

		# Add vertical stretch to push everything to top
		self.right_layout.addStretch()

		# ---------- Settings Panel ----------
		self.settings_panel = QWidget()
		self.settings_panel_layout = QVBoxLayout(self.settings_panel)
		self.settings_panel_layout.setContentsMargins(4, 4, 4, 4)
		self.settings_panel_layout.setSpacing(4)

		# --- Max width for entire panel ---
		self.settings_panel.setMaximumWidth(180)

		# --- Settings widgets ---
		self.settings_name_entry = QLineEdit()
		self.settings_toggles_amount = QLineEdit()
		self.settings_toggles_amount.setValidator(QIntValidator(1, 9999))
		self.settings_width_entry = QLineEdit()
		self.settings_height_entry = QLineEdit()
		self.settings_pos_x_entry = QLineEdit()
		self.settings_pos_y_entry = QLineEdit()
		self.parent_select = QComboBox()
		self.parent_offset_x_entry = QLineEdit()
		self.parent_offset_y_entry = QLineEdit()
		self.settings_tint_slider = QSlider(Qt.Horizontal)
		self.settings_tint_slider.setRange(0, 100)
		# self.apply_button = QPushButton("Apply Changes")
		# self.apply_button.clicked.connect(self.apply_all_changes)
		self.settings_type_name = QComboBox()

		def update_tooltip():
			current_text = self.settings_type_name.currentText()
			self.settings_type_name.setToolTip(current_text)

		self.settings_type_name.currentIndexChanged.connect(update_tooltip)
		update_tooltip()

		# Input widths
		input_width = 50
		name_width = 180
		slider_width = 180

		# --- Name (full width) ---
		self.settings_panel_layout.addWidget(QLabel("Name:"))
		self.settings_name_entry.setMaximumWidth(name_width)
		self.settings_panel_layout.addWidget(self.settings_name_entry)

		# ---------- Width / Height / Toggles ----------
		wh_layout = QHBoxLayout()
		wh_layout.setSpacing(8)

		# Width
		wh_container = QVBoxLayout()
		wh_container.setAlignment(Qt.AlignLeft)
		wh_container.addWidget(QLabel("Width:"))
		self.settings_width_entry.setMaximumWidth(input_width)
		wh_container.addWidget(self.settings_width_entry)
		wh_layout.addLayout(wh_container)

		# Toggles
		toggles_container = QVBoxLayout()
		toggles_container.setAlignment(Qt.AlignLeft)
		toggles_container.addWidget(QLabel("Toggles:"))
		self.settings_toggles_amount.setMaximumWidth(input_width)
		toggles_container.addWidget(self.settings_toggles_amount)
		wh_layout.addLayout(toggles_container)

		# Height
		hh_container = QVBoxLayout()
		hh_container.setAlignment(Qt.AlignLeft)
		hh_container.addWidget(QLabel("Height:"))
		self.settings_height_entry.setMaximumWidth(input_width)
		hh_container.addWidget(self.settings_height_entry)
		wh_layout.addLayout(hh_container)

		# Add the combined row to the panel
		self.settings_panel_layout.addLayout(wh_layout)

		# Position X / Y
		xy_layout = QHBoxLayout()
		xy_layout.setSpacing(8)

		x_container = QVBoxLayout()
		x_container.setAlignment(Qt.AlignLeft)
		x_container.addWidget(QLabel("Pos X:"))
		self.settings_pos_x_entry.setMaximumWidth(input_width)
		x_container.addWidget(self.settings_pos_x_entry)
		xy_layout.addLayout(x_container)

		# Type Selector
		type_container = QVBoxLayout()
		type_container.setAlignment(Qt.AlignCenter)
		self.settings_type_name.addItems([t["name"] for t in self.types])
		type_container.addWidget(QLabel("Type:"))
		self.settings_type_name.view().setMinimumWidth(200)
		type_container.addWidget(self.settings_type_name)
		xy_layout.addLayout(type_container)

		y_container = QVBoxLayout()
		y_container.setAlignment(Qt.AlignRight)
		y_container.addWidget(QLabel("Pos Y:"))
		self.settings_pos_y_entry.setMaximumWidth(input_width)
		y_container.addWidget(self.settings_pos_y_entry)
		xy_layout.addLayout(y_container)

		self.settings_panel_layout.addLayout(xy_layout)

		# --- Parent Selector (centered) ---
		parent_container = QVBoxLayout()
		parent_container.setAlignment(Qt.AlignCenter)
		parent_container.addWidget(QLabel("Parent:"))
		self.parent_select.setMinimumWidth(150)
		self.parent_select.setMaximumWidth(input_width + 40)
		self.parent_select.view().setMinimumWidth(200)
		parent_container.addWidget(self.parent_select)
		self.settings_panel_layout.addLayout(parent_container)

		# Offset X/Y
		offset_layout = QHBoxLayout()
		offset_layout.setSpacing(8)

		offx_container = QVBoxLayout()
		offx_container.setAlignment(Qt.AlignLeft)
		offx_container.addWidget(QLabel("Offset X:"))
		self.parent_offset_x_entry.setMaximumWidth(input_width)
		offx_container.addWidget(self.parent_offset_x_entry)
		offset_layout.addLayout(offx_container)

		offy_container = QVBoxLayout()
		offy_container.setAlignment(Qt.AlignRight)
		offy_container.addWidget(QLabel("Offset Y:"))
		self.parent_offset_y_entry.setMaximumWidth(input_width)
		offy_container.addWidget(self.parent_offset_y_entry)
		offset_layout.addLayout(offy_container)

		self.settings_panel_layout.addLayout(offset_layout)

		# --- Tint slider ---
		self.settings_panel_layout.addWidget(QLabel("Tint % (Display Element):"))
		self.settings_tint_slider.setMaximumWidth(slider_width)
		self.settings_panel_layout.addWidget(self.settings_tint_slider)

		# --- Apply button ---
		# self.apply_button.setMaximumWidth(slider_width)
		# self.settings_panel_layout.addWidget(self.apply_button)

		# Hide initially
		self.settings_panel.setVisible(False)
		self.right_layout.addWidget(self.settings_panel)

		self.settings_name_entry.textEdited.connect(self._on_name_text_edited)
		self.settings_name_entry.editingFinished.connect(self._on_name_finished)

		# Type: push immediate PropertyCommand (jednostkowa zmiana)
		self.settings_type_name.currentIndexChanged.connect(self._on_type_changed)

		# Tint slider: pattern start -> valueChanged (mergeable) -> release clear
		self.settings_tint_slider.sliderPressed.connect(lambda: self._start_field("tint_percent"))
		self.settings_tint_slider.sliderReleased.connect(lambda: self._end_field("tint_percent"))
		self.settings_tint_slider.valueChanged.connect(self._on_tint_value_changed)

		# --- width/height ---
		self.settings_width_entry.textEdited.connect(
			lambda: self._start_field("size"))
		self.settings_width_entry.editingFinished.connect(
			self._on_size_finished)

		self.settings_height_entry.textEdited.connect(
			lambda: self._start_field("size"))
		self.settings_height_entry.editingFinished.connect(
			self._on_size_finished)

		# --- position ---
		self.settings_pos_x_entry.textEdited.connect(
			lambda: self._start_field("pos"))
		self.settings_pos_x_entry.editingFinished.connect(
			self._on_pos_finished)

		self.settings_pos_y_entry.textEdited.connect(
			lambda: self._start_field("pos"))
		self.settings_pos_y_entry.editingFinished.connect(
			self._on_pos_finished)

		self.settings_width_entry.textChanged.connect(self._on_size_live)
		self.settings_height_entry.textChanged.connect(self._on_size_live)

		self.settings_pos_x_entry.textChanged.connect(self._on_pos_live)
		self.settings_pos_y_entry.textChanged.connect(self._on_pos_live)

		# --- toggles ---
		self.settings_toggles_amount.textEdited.connect(lambda: self._start_field("toggles"))
		self.settings_toggles_amount.textChanged.connect(self._on_toggles_live)
		self.settings_toggles_amount.editingFinished.connect(self._on_toggles_finished)

		# --- parent select ---
		self.parent_select.currentIndexChanged.connect(self._on_parent_changed)

		# --- parent offsets ---
		self.parent_offset_x_entry.textEdited.connect(lambda: self._start_field("parent_offset"))
		self.parent_offset_x_entry.textChanged.connect(self._on_parent_offset_live)
		self.parent_offset_x_entry.editingFinished.connect(self._on_parent_offset_finished)

		self.parent_offset_y_entry.textEdited.connect(lambda: self._start_field("parent_offset"))
		self.parent_offset_y_entry.textChanged.connect(self._on_parent_offset_live)
		self.parent_offset_y_entry.editingFinished.connect(self._on_parent_offset_finished)

		# Add the right panel to main layout
		main_layout.addWidget(self.right_panel)

		# ---------------- INI EDITOR FRAME ----------------
		self.ini_editor_frame = ResizableFrame(self)
		self.ini_editor_frame.setStyleSheet(
			"background-color: rgba(30, 30, 30, 180); border:1px solid gray;"
		)
		self.ini_editor_frame.setGeometry(
			(self.width() - 400) // 2,
			self.height() - 240 - 20,  # initial bottom-center
			400,
			240
		)

		# QTextEdit inside frame
		self.ini_editor = QTextEdit(self.ini_editor_frame)
		self.ini_editor.setFont(QFont("Consolas", 10))
		self.ini_editor.setStyleSheet(
			"background-color: rgba(30, 30, 30, 180); color: white; border:none;"
		)
		self.ini_editor.setAcceptRichText(False)
		self.ini_editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
		self.ini_editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

		ie_font = self.ini_editor.font()
		ie_font = QFontMetrics(ie_font)
		self.ini_editor.setTabStopDistance(ie_font.horizontalAdvance(' ') * 4)

		self.highlighter = IniHighlighter(self.ini_editor.document())

		# Save Changes (If Ini Selected)
		self.save_changes_button = QPushButton("💾 Save Ini")
		self.save_changes_button.clicked.connect(self.save_ini_changes)

		# Select INI Button & Label
		self.select_ini_button = QPushButton("📂 Select Ini File")
		self.select_ini_button.clicked.connect(self.select_ini_file)

		self.selected_ini_label = QLabel("No Ini Selected")

		# Layout inside frame
		frame_layout = QVBoxLayout(self.ini_editor_frame)
		frame_layout.setContentsMargins(5, 5, 5, 5)
		frame_layout.setSpacing(5)

		# Add the editor
		frame_layout.addWidget(self.ini_editor)

		# Button + Label row, centered
		button_row = QHBoxLayout()

		button_row.setSpacing(2)
		button_row.setContentsMargins(2, 2, 2, 2)

		self.save_changes_button.setStyleSheet("padding-right: 3px;")
		self.select_ini_button.setStyleSheet("padding-right: 3px;")
		self.selected_ini_label.setStyleSheet("color: white")

		button_row.setAlignment(Qt.AlignmentFlag.AlignCenter)  # center the row
		button_row.addWidget(self.save_changes_button)
		button_row.addWidget(self.select_ini_button)
		button_row.addWidget(self.selected_ini_label)
		btn = QPushButton("Ifs Manager")
		btn.clicked.connect(self.open_drawindexed_editor)
		btn.setStyleSheet("padding-left: 3px; padding-right: 3px")
		button_row.addWidget(btn)
		frame_layout.addLayout(button_row)

		self.ini_editor_frame.show()
		self.scene.selectionChanged.connect(self.on_scene_selection_changed)
		self.update_save_button_state()

		QApplication.instance().installEventFilter(self)

		# --- Auto-save last session every 5 minutes ---
		self.last_session_timer = QTimer(self)
		self.last_session_timer.timeout.connect(self.save_last_session)
		self.last_session_timer.start(getattr('cfg', 'save_interval', 5) * 60 * 1000)  # 5 min

	# Methods

	def update_save_button_state(self):
		has_file = self.current_ini_path is not None
		self.save_changes_button.setVisible(has_file)

	def save_ini_changes(self):
		if not self.current_ini_path:
			return

		try:
			content = self.ini_editor.toPlainText()

			with open(self.current_ini_path, "w", encoding = "utf-8") as f:
				f.write(content)

			self.statusBar().showMessage(f"[SAVE] Overwritten: {self.current_ini_path}", 3000)

		except Exception as e:
			self.statusBar().showMessage(f"[ERROR] Save failed: {e}", 3000)

	def show_welcome(self):

		text = (
			f"Welcome to Menu Creator V{VERSION} by Nurarihyon\n\n"
			"Please Note that this is 1st Public Beta Release - Bugs are to be expected (Please Report them)\n\n"
			"Feel Free to provide Feedback\n\n\n"

			"There's currently no proper Guide, so if whatever I have provided doesn't suffice - Feel Free to Contact me on Discord (NurarihyonMaou, You can find me on AGMG and AGMF)\n\n\n"

			"Quick Start:\n"
			"- Create Templates on the Left\n"
			"- Add Display and Code Elements\n"
			"- Arrange Displayed Elements\n"
			"- Load the Ini File\n"
			"- Ctrl+A to Select the Generated Code, Ctrl+V to Copy it, and Ctrl+V to Paste it back to the Actual File\n"
			"- Extract MenuCreatorEssentials (Link on the Menu Creator's Page) inside Mods Folder and make sure to Instruct the Users to do the same\n\n"

			"Press F1 for Help Dialog + KeyBinds Manager"
		)

		QMessageBox.information(
			self,
			"Welcome",
			text
		)

	# --- name handlers ---
	def _on_name_text_edited(self, text):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return
		# store original name once for undo
		if "name" not in self._field_start_values:
			self._field_start_values["name"] = getattr(item, "name", "")
		# live update model/UI
		item.name = text
		try:
			self.rebuild_outliner()
		except Exception:
			pass

	def _on_name_finished(self):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return
		old = self._field_start_values.pop("name", getattr(item, "name", ""))
		new = self.settings_name_entry.text().strip()
		if old != new:
			cmd = PropertyCommand(item, "name", old, new, text = "Rename")
			try:
				self.undo_stack.push(cmd)
			except Exception as e:
				print("[WARN] undo_stack.push failed:", repr(e))
				# fallback: spróbuj wykonać redo (bez zapisu w stacku)
				try:
					cmd.redo()
				except Exception:
					pass

	# --- type handler ---
	def _on_type_changed(self, idx):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return
		old = getattr(item, "type_name", "")
		new = self.settings_type_name.currentText()
		if old != new:
			cmd = PropertyCommand(item, "type_name", old, new, text = "Change Type")
			try:
				self.undo_stack.push(cmd)
			except Exception as e:
				print("[WARN] undo_stack.push failed:", repr(e))
				# fallback: spróbuj wykonać redo (bez zapisu w stacku)
				try:
					cmd.redo()
				except Exception:
					pass
			# live update
			item.type_name = new
			try:
				self.rebuild_outliner()
			except Exception:
				pass

	# --- tint slider handlers (mergeable pattern) ---
	def _start_field(self, key):
		item = getattr(self, "active_item", None)
		if not item:
			return
		if key not in self._field_start_values:
			if key == "size":
				self._field_start_values[key] = (item.pixmap().width(), item.pixmap().height())
			elif key == "pos":
				self._field_start_values[key] = QPointF(item.pos())
			elif key == "tint_percent":
				self._field_start_values[key] = getattr(item, "tint_percent", 0)

	def _end_field(self, key):
		# clear stored start value
		self._field_start_values.pop(key, None)

	def _on_tint_value_changed(self, value):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return

		old = self._field_start_values.get("tint_percent", getattr(item, "tint_percent", 0))
		# push mergeable PropertyCommand -> QUndoStack połączy serie w jedną
		cmd = PropertyCommand(item, "tint_percent", old, int(value), text = "Tint")
		try:
			self.undo_stack.push(cmd)
		except Exception as e:
			print("[WARN] undo_stack.push failed:", repr(e))
			# fallback: spróbuj wykonać redo (bez zapisu w stacku)
			try:
				cmd.redo()
			except Exception:
				pass
		# live update model + visual
		item.tint_percent = int(value)
		try:
			if hasattr(item, "apply_tint"):
				item.apply_tint()
		except Exception:
			pass

	def _on_size_live(self):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return

		try:
			w = int(parse_size(self.settings_width_entry.text(), self.screen_width))
			h = int(parse_size(self.settings_height_entry.text(), self.screen_height))
		except ValueError:
			return

		w = max(1, w)
		h = max(1, h)

		pix = safe_scaled(item.original_pixmap, w, h)
		item.setPixmap(pix)

		if hasattr(item, "apply_tint"):
			item.apply_tint()

	def _on_size_finished(self):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return

		old = self._field_start_values.pop("size", None)
		if old is None:
			# fallback, ale nie powinno się zdarzyć
			old = (item.pixmap().width(), item.pixmap().height())

		try:
			new = (
				int(parse_size(self.settings_width_entry.text(), self.screen_width)),
				int(parse_size(self.settings_height_entry.text(), self.screen_height))
			)
		except ValueError:
			return

		if old != new:
			self.undo_stack.push(
				TransformCommand(
					item,
					item.pos(),
					old,
					item.pos(),
					new,
					text = "Resize"
				)
			)

	def _on_pos_live(self):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return

		try:
			x = int(parse_size(self.settings_pos_x_entry.text(), self.screen_width))
			y = int(parse_size(self.settings_pos_y_entry.text(), self.screen_height))
		except ValueError:
			return

		newPos = self.screen_to_scene(QPoint(x, y))
		item.setPos(newPos.x(), newPos.y())

	def _on_pos_finished(self):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return

		old = self._field_start_values.pop("pos", None)
		if old is None:
			old = QPoint(int(item.pos().x()), int(item.pos().y()))

		try:
			new = QPoint(
				int(self.settings_pos_x_entry.text()),
				int(self.settings_pos_y_entry.text())
			)

			new = self.screen_to_scene(new)
		except ValueError:
			return

		if old != new:
			self.undo_stack.push(
				TransformCommand(
					item,
					old,
					(item.pixmap().width(), item.pixmap().height()),
					new,
					(item.pixmap().width(), item.pixmap().height()),
					text = "Move"
				)
			)

	# -------- Toggles --------
	def _on_toggles_live(self, text):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return
		try:
			val = int(text) if text and text.isdigit() else getattr(item, "toggles_amount", 1)
		except Exception:
			val = getattr(item, "toggles_amount", 1)
		val = max(1, val)
		# live update
		item.toggles_amount = val

	def _on_toggles_finished(self):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return
		old = self._field_start_values.pop("toggles", getattr(item, "toggles_amount", 1))
		try:
			new = int(self.settings_toggles_amount.text())
		except Exception:
			new = getattr(item, "toggles_amount", 1)
		new = max(1, new)
		if old != new:
			cmd = PropertyCommand(item, "toggles_amount", old, new, text = "Change Toggles")
			try:
				self.undo_stack.push(cmd)
			except Exception:
				try:
					cmd.redo()
				except Exception:
					pass

	# -------- Parent select --------
	def _on_parent_changed(self, idx):
		if getattr(self, "_ui_changing", False):
			return
		item = getattr(self, "active_item", None)
		if not item:
			return
		# map index to parent name (you may have a "None" at index 0)
		try:
			new_parent = self.parent_select.currentText()
			if new_parent == "" or new_parent.lower() in ("none", "<none>"):
				new_parent = None
		except Exception:
			new_parent = None

		old_parent = getattr(item, "parent_item", None)
		if old_parent == new_parent:
			return

		# live update (so UI shows effect immediately)
		item.parent_item = new_parent

		# push change to undo
		cmd = PropertyCommand(item, "parent_item", old_parent, new_parent, text = "Change Parent")
		try:
			self.undo_stack.push(cmd)
		except Exception:
			try:
				cmd.redo()
			except Exception:
				pass

		# optionally rebuild outliner (keeps groups/pages consistent)
		try:
			self.rebuild_outliner()
		except Exception:
			pass

	# -------- Parent offsets live + finish --------
	def _on_parent_offset_live(self, text):
		if getattr(self, "_ui_changing", False):
			return

		item = getattr(self, "active_item", None)
		if not item or not item.parent_item:
			return

		parent = next((p for p in self.display_items if p.name == item.parent_item), None)
		if not parent:
			return

		try:
			ox = float(self.parent_offset_x_entry.text())
		except:
			ox = getattr(item, "parent_offset_x", 0)

		try:
			oy = float(self.parent_offset_y_entry.text())
		except:
			oy = getattr(item, "parent_offset_y", 0)

		# zapisz offset
		item.parent_offset_x = ox
		item.parent_offset_y = oy

		# 🔥 KLUCZOWE — pozycja = parent + offset (scene coords)
		new_pos = QPointF(
			parent.pos().x() + ox,
			parent.pos().y() + oy
		)

		self._ui_changing = True
		try:
			item.setPos(new_pos)
		finally:
			self._ui_changing = False

		self.scene.update()

	def _on_parent_offset_finished(self):
		if getattr(self, "_ui_changing", False):
			return

		item = getattr(self, "active_item", None)
		if not item or not item.parent_item:
			return

		parent = next((p for p in self.display_items if p.name == item.parent_item), None)
		if not parent:
			return

		old = self._field_start_values.pop(
			"parent_offset",
			(getattr(item, "parent_offset_x", 0),
			 getattr(item, "parent_offset_y", 0))
		)

		try:
			new = (
				float(self.parent_offset_x_entry.text()),
				float(self.parent_offset_y_entry.text())
			)
		except:
			return

		if old == new:
			return

		# undo batch
		batch = BatchCommand("Parent Offset")
		batch.add(PropertyCommand(item, "parent_offset_x", old[0], new[0]))
		batch.add(PropertyCommand(item, "parent_offset_y", old[1], new[1]))
		self.undo_stack.push(batch)

		# 🔥 wymuś aktualizację pozycji
		item.setPos(
			parent.pos().x() + new[0],
			parent.pos().y() + new[1]
		)

		self.scene.update()

	def _set_active_item_widgets(self, item):
		"""Ustawia pola inspektora zgodnie z aktywnym itemem (bez wywoływania sygnałów)."""
		if not item:
			return

		self._ui_changing = True
		try:
			# Name
			self.settings_name_entry.setText(getattr(item, "name", ""))

			# Type
			type_name = getattr(item, "type_name", "")
			idx = self.settings_type_name.findText(type_name)
			if idx >= 0:
				self.settings_type_name.setCurrentIndex(idx)
			else:
				# optionally set text if not found
				self.settings_type_name.setCurrentText(type_name)

			# Width / Height - try method first, then attribute
			pix = None
			try:
				pix = item.pixmap()  # QGraphicsPixmapItem
			except Exception:
				pix = getattr(item, "original_pixmap", None) or getattr(item, "_pixmap", None)
			if pix:
				self.settings_width_entry.setText(str(pix.width()))
				self.settings_height_entry.setText(str(pix.height()))
			else:
				self.settings_width_entry.setText("")
				self.settings_height_entry.setText("")

			# Position (scene -> screen) - use pos() (QGraphicsItem)
			pos = None
			try:
				pos = item.pos()
			except Exception:
				pos = getattr(item, "_pos", QPointF(0, 0))

			# convert scene point to screen if you have view helper, otherwise use as-is
			try:
				if hasattr(self, "scene_to_screen"):
					screen_pt = self.scene_to_screen(pos)
				else:
					# best-effort: if you have a view called self.view
					if hasattr(self, "view"):
						screen_pt = self.view.mapFromScene(pos)
					else:
						screen_pt = pos
				self.settings_pos_x_entry.setText(str(int(screen_pt.x())))
				self.settings_pos_y_entry.setText(str(int(screen_pt.y())))
			except Exception:
				self.settings_pos_x_entry.setText("0")
				self.settings_pos_y_entry.setText("0")

			# Parent
			parent_name = getattr(item, "parent_item", None)
			if parent_name is None:
				# choose an index that represents "no parent" or clear text
				# avoid -1 if your combobox doesn't accept it
				self.parent_select.setCurrentIndex(0)
				self.parent_offset_x_entry.setText('0')
				self.parent_offset_y_entry.setText('0')
			else:
				idx = self.parent_select.findText(str(parent_name))
				if idx >= 0:
					self.parent_select.setCurrentIndex(idx)
				else:
					# fallback: add it or set text
					self.parent_select.setCurrentText(str(parent_name))

				parent = next((elem for elem in (getattr(editor, "display_items", []) if editor else []) if
							   elem.name == item.parent_item), None)
				if parent:
					child_screen = editor.scene_to_screen(item.pos())
					parent_screen = editor.scene_to_screen(parent.pos())
					parent_offset_x = child_screen.x() - parent_screen.x()
					parent_offset_y = child_screen.y() - parent_screen.y()

					self.parent_offset_x_entry.setText(str(parent_offset_x))
					self.parent_offset_y_entry.setText(str(parent_offset_y))

			# Tint
			self.settings_tint_slider.setValue(int(getattr(item, "tint_percent", 0)))
		finally:
			self._ui_changing = False

	def _on_undo_index_changed(self, idx):
		try:
			self._ui_changing = True
			self.rebuild_outliner()
			self.rebuild_ini()

			if getattr(self, "active_item", None):
				self._set_active_item_widgets(self.active_item)
		finally:
			self._ui_changing = False

	def open_drawindexed_editor(self):
		if hasattr(self, "bindings_dialog") and self.bindings_dialog is not None:
			# refresh istniejącego
			self.bindings_dialog.filename = self.current_ini_path

			# odśwież oba taby
			new_text = self.ini_editor.toPlainText()

			if hasattr(self.bindings_dialog.draw_page, "refresh_from_ini"):
				self.bindings_dialog.draw_page.refresh_from_ini(new_text)

			if hasattr(self.bindings_dialog.texture_page, "refresh_from_ini"):
				self.bindings_dialog.texture_page.refresh_from_ini(new_text)

			self.bindings_dialog.show()
			self.bindings_dialog.raise_()
			self.bindings_dialog.activateWindow()
			return

		# 🔥 TU tworzysz nowy dialog
		self.bindings_dialog = BindingsEditorDialog(
			self.ini_editor.toPlainText(),
			parent = self,
			filename = self.current_ini_path,
			saved_edits = self.saved_edits
		)

		self.bindings_dialog.show()

	def rebuild_outliner(self):
		self.outliner.rebuild_outliner()

	def on_outliner_item_clicked(self, tree_item, column):
		el = tree_item.data(1, Qt.UserRole)  # tu zawsze DisplayedItem
		if el is not None:
			self.active_item = el

	def on_outliner_selection_changed(self):
		# Ochrona przed re-entrancy (wywołania od scene -> outliner -> scene)
		if getattr(self, "_syncing_selection", False):
			return

		self._syncing_selection = True
		try:
			# pobierz aktualne zaznaczenie elementów z outlinera (jako obiekty modelu)
			selected_items = self.get_selected_display_items()  # powinno zwracać listę el (DisplayItems)

			# --- sync scene selection (incremental) ---
			scene_selected = set(self.scene.selectedItems())
			# dodaj brakujące zaznaczenia
			for el in selected_items:
				if el not in scene_selected:
					el.setSelected(True)
			# usuń zaznaczenia, które nie są w outlinerze
			for g in list(scene_selected):
				if g not in selected_items:
					g.setSelected(False)

			# --- nic nie wybrane ---
			if not selected_items:
				self.settings_panel.setVisible(False)
				self.edit_items = []
				self.start_item_states = {}
				self.item_mouse_offsets = {}
				self.last_selected = None
				self.active_item = None
				return

			# --- setup edit state ---
			self.edit_items = selected_items

			if self.active_item in selected_items:
				self.last_selected = self.active_item
			else:
				self.last_selected = selected_items[-1]

			self.start_item_states = {
				item: (item.pos(), item.pixmap().size())
				for item in self.edit_items
			}

			scene_pos = self.view.mapToScene(
				self.view.viewport().mapFromGlobal(QCursor.pos())
			)

			self.item_mouse_offsets = {
				item: item.pos() - scene_pos
				for item in self.edit_items
			}

			# --- load settings for last selected (deferred so Qt stabilizes selections) ---
			if self.last_selected is not None:
				QTimer.singleShot(0, lambda: self.load_item_to_settings(self.last_selected))
				# pokaż panel ustawień; opcjonalnie możesz wstawić guard w load_item_to_settings
				self.settings_panel.setVisible(True)

		finally:
			self._syncing_selection = False

	def iter_outliner_items(self):
		stack = []
		for i in range(self.outliner.topLevelItemCount()):
			stack.append(self.outliner.topLevelItem(i))

		while stack:
			it = stack.pop()
			yield it
			for c in range(it.childCount()):
				stack.append(it.child(c))

	def on_outliner_item_changed(self, item, column):
		if column != 0:
			return

		tree = self.outliner

		visible = item.checkState(0) == Qt.Checked

		tree.blockSignals(True)
		try:
			node_type = item.data(0, Qt.UserRole)

			# --- 1. ustaw visibility tylko dla sensownych typów ---
			if node_type in ["ELEMENT", "PAGE", "GROUP"]:
				el = item.data(1, Qt.UserRole)
				if el:
					el.setVisible(visible)

			# --- 2. propagacja w dół ---
			def recurse_down(parent_item):
				for i in range(parent_item.childCount()):
					c = parent_item.child(i)

					desired = Qt.Checked if visible else Qt.Unchecked
					if c.checkState(0) != desired:
						c.setCheckState(0, desired)

					child_type = c.data(0, Qt.UserRole)

					# 🔥 tylko jeśli to coś, co ma visual
					if child_type in ["ELEMENT", "PAGE", "GROUP"]:
						child_el = c.data(1, Qt.UserRole)
						if child_el:
							child_el.setVisible(visible)

					recurse_down(c)

			recurse_down(item)

			# --- 3. parent tri-state ---
			def update_parents(child_item):
				parent = child_item.parent()
				if not parent:
					return

				parent_type = parent.data(0, Qt.UserRole)

				if parent_type in ["ROOT_ALWAYS", "ROOT_PAGES"]:
					return

				checked = 0
				unchecked = 0

				for i in range(parent.childCount()):
					state = parent.child(i).checkState(0)
					if state == Qt.Checked:
						checked += 1
					elif state == Qt.Unchecked:
						unchecked += 1

				if checked == parent.childCount():
					parent.setCheckState(0, Qt.Checked)
				elif unchecked == parent.childCount():
					parent.setCheckState(0, Qt.Unchecked)
				else:
					parent.setCheckState(0, Qt.PartiallyChecked)

				update_parents(parent)

			update_parents(item)

		finally:
			tree.blockSignals(False)

	def get_selected_display_items(self):
		items = []
		for it in self.outliner.selectedItems():
			if it.data(0, Qt.UserRole) == "ELEMENT":  # only actual elements
				el = it.data(1, Qt.UserRole)  # DisplayedItem
				if el:
					items.append(el)
		return items

	def delete_display_item(self):
		items = self.scene.selectedItems()

		reply = QMessageBox.question(
			self,
			"Confirm Delete",
			f"Are you sure you want to Delete {len(items)} Selected Display Element(s)?",
			QMessageBox.Yes | QMessageBox.No
		)
		if reply == QMessageBox.No:
			return

		if not items:
			return

		for it in items:
			if it in self.display_items:
				self.display_items.remove(it)
			self.scene.removeItem(it)

		self.rebuild_outliner()

	# =========================
	# INI LOAD / REBUILD
	# =========================

	def format_ini(self, ini_text):
		lines = ini_text.splitlines()
		out_lines = []
		inside_if = False

		for i, line in enumerate(lines):
			stripped = line.lstrip()
			leading_spaces = len(line) - len(stripped)

			# Detect entering/exiting if-block
			if re.match(r"^\s*if\s+.*", line, re.IGNORECASE):
				inside_if = True
			elif re.match(r"^\s*endif\s*$", line, re.IGNORECASE):
				inside_if = False

			# --- Convert spaces to tabs ---
			if leading_spaces > 0:
				tabs = math.ceil(leading_spaces / 4)
				line = "\t" * tabs + stripped

			# --- Auto-tab drawindexed inside if-block ---
			if inside_if and not line.startswith(tuple(['if', 'elif', 'else'])):
				if not line.startswith("\t"):  # only if not already indented
					line = "\t" + line

			out_lines.append(line)

			# --- Add blank line after endif before next comment ---
			if re.match(r"^\s*endif\s*$", line, re.IGNORECASE):
				if i + 1 < len(lines) and re.match(r"^\s*;", lines[i + 1]):
					out_lines.append("")  # blank line

			# --- Add blank line **before** a comment if previous line is not empty ---
			elif re.match(r"^\s*;", line) and len(out_lines) > 1:
				prev_line = out_lines[-2]
				if prev_line.strip() != "":
					out_lines.insert(-1, "")  # insert blank line before comment

		return "\n".join(out_lines)

	@staticmethod
	def strip_generated(text):
		marker = "; GENERATED by MCreatorV3.3.6B - by Nurarihyon"
		idx = text.find(marker)
		if idx != -1:
			return text[:idx].rstrip()
		return text

	@staticmethod
	def create_backup(path):
		backup_path = path.replace('.ini', '') + f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.MCreator_Backup"

		if not os.path.exists(backup_path):
			shutil.copy2(path, backup_path)

	def load_ini_file(self, path):
		if path == 'No Ini Selected':
			self.current_ini_path = None
			self.update_save_button_state()
			return

		with open(path, "r", encoding = "utf-8") as f:
			self.ini_original_text = self.format_ini(self.strip_generated(f.read()))

		self.current_ini_path = path
		self.update_save_button_state()
		self.select_ini_button.setText("🗑 Unload Ini File")
		self.selected_ini_label.setText(path.split('/')[-1])
		self.rebuild_ini()

	def parse_ini_sections(self, text):
		"""
        Returns (preamble_lines_list, sections_dict, order_list)
        - preamble_lines_list: list of raw lines before the first [Header]
        - sections_dict: { section_name: [block_text, ...], ... }
        - order_list: list of section names in original order
        """
		sections = {}
		order = []
		preamble = []

		current = None
		buf = []

		for line in text.splitlines(keepends = True):
			stripped = line.strip()
			# accept lines like "[Name]" also when no trailing newline
			if stripped.startswith("[") and stripped.endswith("]"):
				# flush buffer into current or preamble
				if current:
					sections.setdefault(current, []).append("".join(buf))
					buf.clear()
				else:
					if buf:
						preamble.extend(buf)
						buf.clear()
				current = stripped[1:-1]
				order.append(current)
			else:
				buf.append(line)

		if current:
			sections.setdefault(current, []).append("".join(buf))
		else:
			# no section at all, treat whole as preamble
			if buf:
				preamble.extend(buf)

		return preamble, sections, order

	def merge_constants(self, blocks_or_lines):
		"""
        Merge Constants by grouping lines that share the same $var base.
        - Preserves internal formatting & blank lines inside groups.
        - Groups are separated by a single blank line.
        - Extracts if...endif blocks and appends them at the end.
        - Deduplicates exact non-blank lines (first occurrence kept).
        - Returns a string that ends with exactly one newline.
        """
		# regexes
		if_start_re = re.compile(r'^\s*if\b')
		if_end_re = re.compile(r'^\s*endif\b')
		var_token_re = re.compile(r'(\$[A-Za-z_][A-Za-z0-9_]*)')
		strip_index_re1 = re.compile(r'^(.*?)(?:_(\d+))$')  # foo_12 -> foo
		strip_index_re2 = re.compile(r'^(.*?)(\d+)$')  # foo12 -> foo

		# flatten input into lines preserving order
		raw_lines = []
		for chunk in blocks_or_lines:
			raw_lines.extend(chunk.splitlines())

		# first: extract if-blocks (preserve order)
		seen = set()
		if_blocks = []
		remaining = []
		i = 0
		n = len(raw_lines)
		while i < n:
			ln = raw_lines[i]
			if if_start_re.match(ln.lstrip()):
				blk = [ln]
				i += 1
				while i < n:
					blk.append(raw_lines[i])
					if if_end_re.match(raw_lines[i].lstrip()):
						i += 1
						break
					i += 1
				blk_text = "\n".join(l.rstrip() for l in blk).rstrip()
				if blk_text not in seen:
					seen.add(blk_text)
					if_blocks.append(blk_text)
				continue
			remaining.append(ln)
			i += 1

		# group lines by variable base, preserving order and internal blanks
		groups = OrderedDict()  # base -> list(lines)
		other_lines = []  # lines w/o $token or before any group
		last_group = None

		for ln in remaining:
			s = ln.rstrip()
			if s == "":
				# blank line: if we have a last_group, treat as internal blank for that group,
				# otherwise preserve in other_lines (but collapse consecutive blanks)
				if last_group is not None:
					groups[last_group].append("")  # keep blank inside group
				else:
					if not other_lines or other_lines[-1] != "":
						other_lines.append("")
				continue

			# dedupe exact non-blank lines
			if s in seen:
				# mark last_group None if duplicate belonged elsewhere? keep last_group unchanged
				# simply skip duplicated line
				continue
			seen.add(s)

			m = var_token_re.search(ln)
			if not m:
				# no $token -> misc line
				other_lines.append(ln)
				last_group = None
				continue

			token = m.group(1)
			base = token
			m1 = strip_index_re1.match(token)
			if m1:
				base = m1.group(1)
			else:
				m2 = strip_index_re2.match(token)
				if m2:
					base = m2.group(1)

			if base not in groups:
				groups[base] = []
			groups[base].append(ln)
			last_group = base

		# build output: groups in first-seen order, separated by exactly one blank line when needed
		out = ["[Constants]"]
		# first = True
		for base, lines in groups.items():
			# if not first:
			#    # ensure single blank between groups (only if last line isn't already blank)
			#    #if out[-1].strip() != "":
			#    #    out.append("")
			# first = False
			# append group's lines as-is (including internal blanks)
			out.extend(lines)

		# append other_lines (they may already contain blanks preserved)
		if other_lines:
			# if there are groups and last line isn't blank, ensure single blank before other_lines
			if groups and out[-1].strip() != "":
				out.append("")
			# append other_lines preserving blanks and order
			out.extend(other_lines)

		# append if_blocks at end, separated by single blank line
		if if_blocks:
			if out[-1].strip() != "":
				out.append("")
			for idx, blk in enumerate(if_blocks):
				out.append(blk)
				if idx != len(if_blocks) - 1:
					out.append("")  # separate multiple if-blocks with one blank

		# trim trailing blanks and ensure exactly one final newline
		while out and out[-1] == "":
			out.pop()
		return "\n".join(out) + "\n\n"

	def merge_present(self, blocks):
		seen = set()
		out = ["[Present]\n"]

		for block in blocks:
			for line in block.splitlines():
				if line not in seen:
					if line not in ['if', 'endif', 'elif', 'else', '\n', '']:
						seen.add(line)
					out.append(line + "\n" if not line.endswith("\n") else line)

		return "".join(out)

	def classify(self, name):
		for base in SECTION_ORDER:
			if name.startswith(base):
				return base
		return "Other"

	def rebuild_ini_structured(self, original_text, generated_text):
		"""
        Rebuild INI preserving:
          - preamble (lines before first [Header]) on top
          - original sections in original order (merged Constants/Present using existing helpers)
          - generated sections grouped/placed after original (wrapped as their own sections)
          - extra spacing between different section types
        """
		preamble, orig_sections, orig_order = self.parse_ini_sections(original_text)
		out_parts = []

		def format_section(self, name, body):
			"""Formats a single INI section with normal spacing."""
			lines = body.splitlines()
			while lines and lines[0].strip() == "":
				lines.pop(0)
			while lines and lines[-1].strip() == "":
				lines.pop()
			body_str = "\n".join(lines)
			return f"[{name}]\n{body_str}\n\n"

		# 1) preamble
		if preamble:
			out_parts.append("".join(preamble).rstrip() + "\n\n")

		# 2) Constants
		if "Constants" in orig_sections:
			out_parts.append(self.merge_constants(orig_sections["Constants"]))

		# 3) Present
		if "Present" in orig_sections:
			out_parts.append(self.merge_present(orig_sections["Present"]))

		# 4) Emit original sections with spacing by type
		grouped_orig = {k: [] for k in SECTION_ORDER if k not in ("Constants", "Present")}
		grouped_orig["Other"] = []

		for name in orig_order:
			if name in ("Constants", "Present"):
				continue
			kind = self.classify(name)
			kind_key = kind if kind in grouped_orig else "Other"
			for b in orig_sections.get(name, []):
				grouped_orig[kind_key].append((name, b))

		prev_kind = None
		for k in SECTION_ORDER:
			if k in ("Constants", "Present"):
				continue
			sections = grouped_orig.get(k, [])
			if k != "Resource":
				for name, b in sections:
					if prev_kind is not None and prev_kind != k:
						out_parts.append("\n\n\n")  # extra spacing between types
					elif prev_kind == k:
						out_parts.append("\n")  # normal spacing within same type
					out_parts.append(format_section(self, name, b))
					prev_kind = k
			else:
				seen_res = set()
				for name, b in sections:
					m = re.search(r'filename\s*=\s*(.+)', b, re.IGNORECASE)
					filename = m.group(1).strip() if m else ""
					key = (name.lower(), filename)
					if key in seen_res:
						continue
					seen_res.add(key)
					if prev_kind is not None and prev_kind != "Resource":
						out_parts.append("\n\n\n")
					elif prev_kind == "Resource":
						out_parts.append("\n")
					out_parts.append(format_section(self, name, b))
					prev_kind = "Resource"

		# Emit Other last
		for name, b in grouped_orig.get("Other", []):
			if prev_kind != "Other" and prev_kind is not None:
				out_parts.append("\n\n\n")
			elif prev_kind == "Other":
				out_parts.append("\n")
			out_parts.append(format_section(self, name, b))
			prev_kind = "Other"

		# 5) Generated sections
		if generated_text and generated_text.strip():
			gen_preamble, gen_sections, gen_order = self.parse_ini_sections(generated_text)

			out_parts.append(f"\n; GENERATED by MCreatorV{VERSION} - by Nurarihyon\n\n")
			if gen_preamble:
				out_parts.append("".join(gen_preamble).rstrip() + "\n\n")

			if "Constants" in gen_sections:
				gen_sections["Constants"] = self._ensure_active_declaration(gen_sections["Constants"], 'Constants')
				out_parts.append(self.merge_constants(gen_sections["Constants"]))
			else:
				gen_sections["Constants"] = ["global $Active"]
				out_parts.append(self.merge_constants(gen_sections["Constants"]))

			if "Present" in gen_sections:
				gen_sections["Present"] = self._ensure_active_declaration(gen_sections["Present"], 'Present')
				out_parts.append(self.merge_present(gen_sections["Present"]))
			else:
				gen_sections["Present"] = ["post $Active = 0"]
				out_parts.append(self.merge_constants(gen_sections["Present"]))

			grouped_gen = {"Key": [], "CommandList": [], "CustomShader": [], "Resource": [], "Other": []}
			for name in gen_order:
				if name in ("Constants", "Present"):
					continue
				kind = self.classify(name)
				kind_key = kind if kind in grouped_gen else "Other"
				for b in gen_sections.get(name, []):
					grouped_gen[kind_key].append((name, b))

			prev_kind = None
			for k in ("Key", "CommandList", "CustomShader", "Resource", "Other"):
				if k != "Resource":
					for name, b in grouped_gen.get(k, []):
						if prev_kind is not None and prev_kind != k:
							out_parts.append("\n\n\n")
						elif prev_kind == k:
							out_parts.append("\n")
						out_parts.append(format_section(self, name, b))
						prev_kind = k
				else:
					seen_res = set()
					for name, b in grouped_gen.get("Resource", []):
						m = re.search(r'filename\s*=\s*(.+)', b, re.IGNORECASE)
						filename = m.group(1).strip() if m else ""
						key = (name.lower(), filename)
						if key in seen_res:
							continue
						seen_res.add(key)
						if prev_kind is not None and prev_kind != "Resource":
							out_parts.append("\n\n\n")
						elif prev_kind == "Resource":
							out_parts.append("\n")
						out_parts.append(format_section(self, name, b))
						prev_kind = "Resource"

		out_parts.append(f"\n; GENERATED by MCreatorV{VERSION} - by Nurarihyon")
		return "".join(out_parts)

	def _ensure_active_in_texture_override(self, ini_text):
		lines = ini_text.splitlines()
		result = []
		i = 0
		n = len(lines)

		present_found = False
		present_has_post_active = False

		while i < n:
			line = lines[i]

			# -------------------------
			# Detect [Present]
			# -------------------------
			# if re.match(r'\s*\[Present\]\s*', line, re.IGNORECASE):
			#    present_found = True
			#
			#    section_lines = [line]
			#    i += 1
			#
			#    while i < n and not re.match(r'\s*\[.*\]', lines[i]):
			#        section_lines.append(lines[i])
			#
			#        if re.search(r'post\s+\$active\s*=\s*0', lines[i], re.IGNORECASE):
			#            present_has_post_active = True
			#
			#        i += 1
			#
			#    # Inject if missing
			#    if not present_has_post_active:
			#        section_lines.append("post $Active = 0\n\n")
			#
			#    result.extend(section_lines)
			#    continue

			# -------------------------
			# TextureOverridePosition
			# -------------------------
			header_match = re.match(
				r'\s*\[TextureOverride.*Position\]\s*',
				line,
				re.IGNORECASE
			)

			if not header_match:
				result.append(line)
				i += 1
				continue

			section_lines = [line]
			i += 1

			while i < n and not re.match(r'\s*\[.*\]', lines[i]):
				section_lines.append(lines[i])
				i += 1

			vb0_index = None
			has_active = False

			for idx, sec_line in enumerate(section_lines):

				if re.match(r'\s*vb0\s*=', sec_line, re.IGNORECASE):
					vb0_index = idx

				if re.search(r'\$active\s*=', sec_line, re.IGNORECASE):
					has_active = True

			if vb0_index is not None and not has_active:
				section_lines.insert(vb0_index + 1, "$Active = 1")

			result.extend(section_lines)

		# -------------------------
		# If no Present at all
		# -------------------------

		# if not present_found:
		#    result.append("")
		#    result.append("[Present]")
		#    result.append("post $Active = 0\n\n")

		return "\n".join(result)

	# -----------------------
	# Ensure only Toggle/Condition vars are global persist
	# -----------------------
	def _to_title_case(self, var_name: str) -> str:
		# rozbija po _ i kapitalizuje każdy segment
		return ''.join(part.capitalize() for part in var_name.split('_'))

	def _ensure_active_declaration(self, sections, type):
		act_reg = r"\bglobal\s*\$active\b" if type == 'Constants' else r"\bpost\s*\$active\s*=\s*0\b"

		# połącz wszystkie bloki Constants w jeden tekst do sprawdzenia
		# text = "\n".join(constants_sections)

		if not re.search(act_reg, self.ini_editor.toPlainText().lower()):
			sections.append("global $Active" if type == 'Constants' else 'post $Active = 0')

		return sections

	def _ensure_toggle_globals(self, ini_text):
		if not hasattr(self, "saved_edits"):
			return ini_text

		edits = self.saved_edits.get(self.current_ini_path, {})
		if not edits:
			return ini_text

		# 1️⃣ Collect toggle vars (case-insensitive storage)
		toggle_vars_lower = set()

		for group in edits.values():
			for index_dict in group.values():
				for block in index_dict.values():
					cond = block.get("condition")
					if not cond:
						continue

					for v in re.findall(r'\$([A-Za-z_][A-Za-z0-9_]*)', cond):
						toggle_vars_lower.add(v.lower())

		if not toggle_vars_lower:
			return ini_text

		# 2️⃣ Collect already declared vars (case-insensitive)
		declared_lower = set()

		for m in re.finditer(
				r'(?im)^\s*(?:global(?:\s+persist)?|local)\s+(\$[A-Za-z_][A-Za-z0-9_]*)',
				ini_text
		):
			declared_lower.add(m.group(1).lstrip('$').lower())

		# 3️⃣ Compute missing
		missing_lower = sorted(toggle_vars_lower - declared_lower)
		if not missing_lower:
			return ini_text

		# 4️⃣ Build insert lines in TitleCase
		insert_lines = [
			f"global persist ${self._to_title_case(v)}"
			for v in missing_lower
		]

		insert_text = "\n".join(insert_lines)

		# 5️⃣ Insert after last variable in [Constants]
		m = re.search(r'(?im)^[ \t]*\[constants\][ \t]*$', ini_text)
		if not m:
			return ini_text

		start = m.end()

		next_header = re.search(r'(?m)^[ \t]*\[', ini_text[start:])
		section_end = start + next_header.start() if next_header else len(ini_text)

		section = ini_text[start:section_end]

		var_matches = list(re.finditer(
			r'(?im)^\s*(?:global(?:\s+persist)?|local)\s+\$[A-Za-z_][A-Za-z0-9_]*',
			section
		))

		if var_matches:
			insert_pos = start + var_matches[-1].end()
		else:
			insert_pos = start

		before = ini_text[:insert_pos].rstrip("\n")
		after = ini_text[insert_pos:].lstrip("\n")

		return before + "\n\n" + insert_text + "\n\n" + after

	def rebuild_ini(self, run=True):
		if not self.allow_rebuild_ini:
			self.allow_rebuild_ini = True
			return

		v_scroll = self.ini_editor.verticalScrollBar()
		h_scroll = self.ini_editor.horizontalScrollBar()
		v_val = v_scroll.value()
		h_val = h_scroll.value()

		self.scene.update()
		QApplication.processEvents()

		compiled = self.build_compiled_code()
		if compiled is None:
			print("[Error] build_compiled_code returned None")
			return

		# Run auto-expansion on the compiled/generated part BEFORE merging into original.
		# This avoids generated lines being attached to the last original header by accident.

		merged = self.rebuild_ini_structured(self.ini_original_text, compiled)

		found = _POST_DIRECTIVE_RE.findall(merged)
		for cmd in found:
			editor.post_commands.append(cmd.strip())

		merged = process_post_commands(merged, self.post_commands)

		self.post_commands = []

		if self.auto_if:
			try:
				merged = auto_expand_drawindexed_matching(self.display_items, merged)
			except Exception as e:
				# be defensive: if expansion fails, fall back to raw compiled
				print("[WARN] auto_expand failed:", e)

		# final resource dedup across entire document (Original + Generated)
		def remove_duplicate_resources(ini_text):
			blocks = re.split(r'(?=\[)', ini_text)
			seen = set()
			output = []
			for block in blocks:
				header_match = re.match(r'^\[(Resource\w*)\]', block, re.IGNORECASE)
				if header_match:
					resource_name = header_match.group(1)
					file_match = re.search(r'filename\s*=\s*(.+)', block, re.IGNORECASE)
					filename = file_match.group(1).strip() if file_match else ""
					key = (resource_name.lower(), filename)
					if key in seen:
						continue
					seen.add(key)
				output.append(block)
			return "".join(output)

		def remove_nons(ini_text):
			output = []
			for line in ini_text.split('\n'):
				if '{skip}' in line:
					continue
				output.append(line)
			return "\n".join(output)

		final = remove_duplicate_resources(merged)
		final = remove_nons(final)
		final = self._ensure_toggle_globals(final)
		final = self._ensure_active_in_texture_override(final)

		self.ini_editor.setPlainText(final)

		if hasattr(self, "bindings_dialog") and run:
			if hasattr(self.bindings_dialog, "texture_page"):
				self.bindings_dialog.texture_page.refresh_from_ini(self.ini_editor.toPlainText())

			if hasattr(self.bindings_dialog, "draw_page"):
				self.bindings_dialog.draw_page.refresh_from_ini(self.ini_editor.toPlainText())

			self.bindings_dialog.filename = self.current_ini_path
			self.bindings_dialog.apply_all()

		def restore_scroll():
			v_scroll.setValue(v_val)
			h_scroll.setValue(h_val)

		QTimer.singleShot(0, restore_scroll)

	# =========================
	# COMPILE ALL ELEMENTS
	# =========================

	def build_compiled_code(self):
		blocks = []

		# ---- VISUAL ELEMENTS ----
		for el in sorted(self.display_items, key = lambda x: x.zValue()):
			type_def = next(
				(t for t in self.types if t["name"] == el.type_name),
				None
			)

			if type_def is None:
				# Log detailed info
				print(
					f"[Error] Code element '{getattr(el, 'name', '<unnamed>')}' has unknown type '{el.type_name}'")
				print(f"Available types: {[t['name'] for t in self.types]}")
				# Optionally skip this code element instead of crashing
				return None

			ini = type_def.get("ini_code", "")
			blocks.append(expand_visual_ini(el, ini))

		# ---- CODE ELEMENTS ----
		for code in self.code_elements:
			type_def = next((t for t in self.types if t["name"] == code.type_name), None)

			if type_def is None:
				# Log detailed info
				print(
					f"[Error] Code element '{getattr(code, 'name', '<unnamed>')}' has unknown type '{code.type_name}'")
				print(f"Available types: {[t['name'] for t in self.types]}")
				# Optionally skip this code element instead of crashing
				return None

			ini = type_def.get("ini_code", "")
			blocks.append(self.expand_code_ini(code, ini))

		compiled = "\n\n".join(b for b in blocks if b.strip())

		# -------------------------
		# jednorazowe sprawdzenie dependencies (TU wywołujemy popup JEDNOCZEŚNIE)
		# -------------------------
		# dep_to_types możesz zdefiniować globalnie lub tutaj — None = fallback substring disabled if you implement strict matching
		dep_to_types = None  # lub {'Check Circle Hover': ['CircleHover'], ...}

		if self.allow_alert:
			compiled = ensure_declared_dependencies_have_elements(
				parent = self,  # okno/editor jako parent dla QMessageBox
				text = compiled,
				editor = self,  # editor zawiera code_elements i display_items
				dep_to_types = dep_to_types,
				include_displayed_items = True
			)
		else:
			self.allow_alert = True

		return compiled

	# =========================
	# VISUAL EXPANSION
	# =========================

	# =========================
	# CODE EXPANSION
	# =========================

	def expand_code_ini(self, code, ini):

		block_placeholder = re.compile(r"\{([A-Za-z_]\w*)(?:\.x(\d+))?\}")

		# reuse existing visual lookup
		visual = None
		if getattr(code, "ref_visual", None):
			visual = next((v for v in self.display_items if v.name == code.ref_visual), None)

		lines = ini.splitlines()

		def apply_visual_and_globals(line):
			if visual:
				line = line.replace("{element.name}", visual.name.replace(' ', ''))
				line = line.replace("{element.offset_x}", str(editor.scene_to_screen(visual.pos()).x()))
				line = line.replace("{element.offset_y}", str(editor.scene_to_screen(visual.pos()).y()))
				line = line.replace("{element.width}", str(int(visual.pixmap().width())))
				line = line.replace("{element.height}", str(int(visual.pixmap().height())))
				line = line.replace("{element.resource}", ExtractResourceName(visual.pixmap_path).replace(' ', ''))
				line = line.replace("{element.pixmap_path}", 'Resources/' + visual.pixmap_path.split('/')[-1])
				line = line.replace("{element.z}", str(visual.zValue()))
				line = line.replace("{element.page}", str(visual.page_index) if visual.page_index is not None else '-1')
				line = line.replace("{element.group}", str(visual.group) if visual.group is not None else '-1')
				line = line.replace("{element.toggles_amount}", str(visual.toggles_amount))

			line = line.replace("{screen.width}", str(int(editor.screen_width)))
			line = line.replace("{screen.height}", str(int(editor.screen_height)))
			line = line.replace("{max_page}", str(len(self.pages)))
			return line

		for idx, line in enumerate(lines):
			try:
				lines[idx] = apply_visual_and_globals(line)

			except Exception as e:
				print(f"[VISUAL][{line}] apply_visual_and_globals error: {e}")

		lines = expand_for_blocks(lines, code, visual, self.display_items, getattr(self, "code_elements", []))
		lines = expand_if_blocks(lines, code, self.code_elements, visual, self.display_items, local_vars = None,
								 debug = False)

		out_lines = []
		i = 0
		n = len(lines)

		# helper: return param list (always list of strings)
		def param_list(k):
			vals = code.params.get(k, [])
			if isinstance(vals, (list, tuple)):
				return [str(x) for x in vals]
			if vals is None or vals == "":
				return []
			return [str(vals)]

		# helper: visual/global replacements (keeps existing behavior)

		while i < n:
			raw_line = lines[i]

			# detect Loop block
			if raw_line.strip() == "Loop:":
				i += 1
				loop_lines = []
				while i < n and lines[i].strip() != "EndLoop":
					loop_lines.append(lines[i])
					i += 1
				# skip EndLoop (if present)
				i += 1

				# If loop empty, continue
				if not loop_lines:
					continue

				# Determine header placeholder if present (we will process header as a normal loop line, so we don't require header to be at specific position)
				# Collect all keys used inside the loop (both ${...} and {...})
				keys_used = set()
				for l in loop_lines:
					for m in block_placeholder.finditer(l):
						keys_used.add(m.group(1))

				# If no keys at all, just emit block once (no expansion)
				if not keys_used:
					for l in loop_lines:
						out_lines.append(l)
					continue

				# detect .xN cap from first placeholder in header-like lines (prefer header-looking lines that start with '[')
				raw_count = None
				header_found = None
				for l in loop_lines:
					if l.strip().startswith('[') and '}' in l:
						m = block_placeholder.search(l)
						if m and m.group(2):
							raw_count = int(m.group(2))
						header_found = l
						break
				# fallback: if no header-like lines, still look for any .xN in loop
				if raw_count is None:
					for l in loop_lines:
						m = block_placeholder.search(l)
						if m and m.group(2):
							raw_count = int(m.group(2))
							break

				# determine iteration count
				if raw_count is not None:
					iterations = raw_count
				else:
					# expandable: take max available among keys_used
					lengths = [len(param_list(k)) for k in keys_used]
					iterations = max(lengths) if lengths else 0

				# If expandable and no values at all, skip whole loop
				if raw_count is None and iterations == 0:
					continue

				# Expand iterations
				for idx in range(iterations):
					# If expandable (no raw_count) and any required key lacks value at idx -> skip this iteration
					if raw_count is None:
						missing = False
						for k in keys_used:
							pl = param_list(k)
							if idx >= len(pl):
								missing = True
								break
						if missing:
							continue

					# Emit each line of the block with per-iteration substitutions
					for l in loop_lines:
						# FIRST: process {if ...} for this iteration
						line = _process_conditionals_in_line(l, code, idx, all_visuals = self.display_items,
															 all_code = self.code_elements)

						# replace {key} / {key.xN} similarly
						def curly_repl(m):
							k = m.group(1)
							pl = param_list(k)
							if idx < len(pl):
								return pl[idx]
							return ""

						line = block_placeholder.sub(curly_repl, line)

						out_lines.append(line)

				continue  # done processing this Loop block

			# ---------- Normal (unchanged) line processing ----------
			# FIRST: process inline conditionals (non-loop context)
			line = _process_conditionals_in_line(raw_line, code, idx = None, all_visuals = self.display_items,
												 all_code = self.code_elements)

			# existing single-line block expansion behavior (unchanged)
			# match first {key} or {key.xN}
			match = block_placeholder.search(line)
			if match:
				key = match.group(1)
				raw_count_single = match.group(2)
				values = param_list(key)
				if not values:
					# nothing to emit for this placeholder; skip the line entirely
					# (this preserves previous behavior)
					i += 1
					continue

				if raw_count_single is not None:
					max_count = int(raw_count_single)
					emit_values = values[:max_count]
				else:
					emit_values = values

				prefix = line[:match.start()]
				suffix = line[match.end():]
				for val in emit_values:
					out_lines.append(f"{prefix}{val}{suffix}")

				i += 1
				continue

			# normal parameter placeholders: {key.xi} replacements and fallback {key}
			for key, values in code.params.items():
				for j, val in enumerate(values if isinstance(values, (list, tuple)) else [values]):
					line = line.replace(f"{{{key}.x{j}}}", str(val))
				if values:
					if isinstance(values, (list, tuple)):
						line = line.replace(f"{{{key}}}", str(values[0]))
					else:
						line = line.replace(f"{{{key}}}", str(values))

			out_lines.append(line)
			i += 1

		full = "\n".join(out_lines)
		return full

	# =========================
	# SAFE MERGE (NO DUPES)
	# =========================

	def _clear_lists(self):
		dlg = self.bindings_dialog

		for page_name in ("draw_page", "texture_page"):
			page = getattr(dlg, page_name, None)
			if page and hasattr(page, "header_list"):
				page.header_list.clear()

			if page and hasattr(page, "block_list"):
				page.block_list.clear()

	# ---------------- Methods ----------------
	def select_ini_file(self):
		# If an INI is already loaded -> this acts as UNLOAD
		if hasattr(self, "bindings_dialog"):
			self.bindings_dialog.filename = None
			self.bindings_dialog.blocks_by_header = {}
			self.bindings_dialog.header_keys = []
			self._clear_lists()

		if self.current_ini_path:
			self.unload_ini_file()
			return

		options = QFileDialog.Option.ReadOnly
		file_name, _ = QFileDialog.getOpenFileName(
			self,
			"Select Ini File",
			"",
			"Ini Files (*.ini);;All Files (*)",
			options = options
		)

		if file_name:

			if hasattr(self, "bindings_dialog"):
				if hasattr(self.bindings_dialog, "texture_page"):
					self.bindings_dialog.texture_page.refresh_from_ini(self.ini_editor.toPlainText())

				if hasattr(self.bindings_dialog, "draw_page"):
					self.bindings_dialog.draw_page.refresh_from_ini(self.ini_editor.toPlainText())

				self.bindings_dialog.filename = self.current_ini_path
				self.bindings_dialog.apply_all()

			self.current_ini_path = file_name
			self.update_save_button_state()
			self.selected_ini_label.setText(file_name.split('/')[-1])
			self.select_ini_button.setText("🗑 Unload Ini File")

			try:
				self.create_backup(file_name)

				with open(file_name, "r", encoding = "utf-8") as f:
					text = self.strip_generated(f.read())
					self.ini_editor.setPlainText(text)
					self.ini_original_text = text
			except Exception as e:
				self.selected_ini_label.setText(f"Error reading file: {e}")
				self.current_ini_path = None
				self.update_save_button_state()
				self.select_ini_button.setText("📂 Select Ini File")
				return

		self.rebuild_ini()

	def unload_ini_file(self):
		reply = QMessageBox.question(
			self,
			"Unload INI",
			"Unload current INI file and clear editor?",
			QMessageBox.Yes | QMessageBox.No
		)
		if reply == QMessageBox.No:
			return

		# Clear current INI
		self.current_ini_path = None
		self.update_save_button_state()
		self.ini_original_text = ""
		self.ini_editor.clear()

		self.selected_ini_label.setText("No Ini Selected")
		self.select_ini_button.setText("📂 Select Ini File")

		# Rebuild editor state from empty ini
		self.rebuild_ini()

	def resizeEvent(self, event):
		super().resizeEvent(event)

		if hasattr(self, "ini_editor_frame") and not getattr(self, "ini_frame_user_manipulating", False):
			frame = self.ini_editor_frame
			frame.move(
				(self.width() - frame.width()) // 2,
				self.height() - frame.height() - 5
			)

	# Code Elements

	def refresh_code_list(self):
		self.code_list.clear()
		for e in self.code_elements:
			self.code_list.addItem(f"{e.name} [{e.type_name}]")

	def add_code_element(self):
		dlg = CodeElementDialog(
			types = self.types,
			displayed_elements = editor.display_items,
			parent = self
		)
		if dlg.exec():
			self.code_elements.append(dlg.get_element())
			self.refresh_code_list()

		# self.rebuild_ini()

	def edit_code_element(self):
		row = self.code_list.currentRow()
		if row < 0:
			return

		dlg = CodeElementDialog(
			types = self.types,
			displayed_elements = editor.display_items,
			element = self.code_elements[row],
			parent = self
		)
		if dlg.exec():
			self.code_elements[row] = dlg.get_element()
			self.refresh_code_list()

		# self.rebuild_ini()

	def delete_code_element(self):
		row = self.code_list.currentRow()
		if row >= 0:
			self.code_elements.pop(row)
			self.refresh_code_list()

		self.rebuild_ini()

	# Save-Load

	def load_types(self):
		if os.path.exists(TYPES_FILE):
			with open(TYPES_FILE, "r", encoding = "utf-8") as f:
				data = json.load(f)
				self.types = data.get("types", [])
				for t in self.types:
					t.setdefault("kind", "Visual")
		else:
			self.types = [
				{"name": "Visual", "ini_code": "", "kind": "Visual", "is_default": True},
				{"name": "Slider", "ini_code": "[Constants]\n$Value = 0", "kind": "Code", "is_default": True},
				{"name": "Toggle", "ini_code": "[Constants]\n$Enabled = 0", "kind": "Code", "is_default": True},
			]
			self.save_types()

	def save_types(self):
		with open(TYPES_FILE, "w", encoding = "utf-8") as f:
			json.dump(
				{"version": TYPES_VERSION, "types": self.types},
				f,
				indent = 2
			)

	def refresh_type_combo(self, all_types=False):
		self.type_combo.clear()
		for t in self.types:
			if not all_types:
				if t['kind'] != 'Code':
					self.type_combo.addItem(t["name"])
			else:
				self.type_combo.addItem(t["name"])

	def get_selected_type(self):
		name = self.type_combo.currentText()
		return next((t for t in self.types if t["name"] == name), None)

	def open_type_editor(self):
		dlg = TypeEditorDialog(self.types, self)
		if dlg.exec():
			self.types = dlg.get_types()
			self.save_types()
			self.refresh_type_combo(False)

	# ---------------- Event Filter / Blender-like editing ----------------

	def eventFilter(self, obj, event):
		fw = QApplication.focusWidget()

		if QApplication.activeModalWidget():
			return False

		# Never steal Typing
		if isinstance(fw, (QLineEdit, QTextEdit, QComboBox)):
			return False

		if obj is self.ini_editor_frame:
			return False  # don't intercept

		if self.edit_mode and self.edit_items and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Shift:
			self.view.show_grid = True
			self.view.viewport().update()

		if event.type() == QEvent.KeyPress:

			if self.edit_mode and self.edit_items:
				if self.keybinds.matches(event, "cancel"):
					self.restore_start_states()
					self.exit_edit_mode()
					return True
				if self.keybinds.matches(event, "lock_z"):
					self.lock_z = not self.lock_z
					self.lock_x = False
					return True
				if self.keybinds.matches(event, "lock_x"):
					self.lock_x = not self.lock_x
					self.lock_z = False
					return True
				if self.keybinds.matches(event, "toggle_aspect") and self.edit_mode == "scale":
					self.lock_aspect = not self.lock_aspect
					return True
			else:
				if self.keybinds.matches(event, "move_mode"):
					self.enter_edit_mode("move")
					return True
				if self.keybinds.matches(event, "scale_mode"):
					self.enter_edit_mode("scale")
					return True
				if self.keybinds.matches(event, "delete"):
					self.delete_display_item()
					return True

		elif self.edit_mode and self.edit_items and event.type() == QEvent.KeyRelease and event.key() == Qt.Key_Shift:
			self.view.show_grid = False
			self.view.viewport().update()

			return True

		# --- If we're in edit mode and user clicks another item, finish the edit first ---
		elif self.edit_mode and self.edit_items and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
			try:
				# Map cursor to scene and find topmost item under cursor
				scene_pos = self.view.mapToScene(self.view.viewport().mapFromGlobal(QCursor.pos()))
				items_under = self.scene.items(scene_pos)  # topmost first
				clicked = items_under[0] if items_under else None

				if clicked is None or clicked in self.edit_items or clicked not in self.edit_items:
					# Build transform commands for changed items (same logic used on MouseButtonRelease)
					batch = BatchCommand("Transform Items (click-finish)")
					for item, (old_pos, old_size) in list(self.start_item_states.items()):
						new_pos = item.pos()
						new_size = (item.pixmap().width(), item.pixmap().height())
						try:
							old_size_t = (old_size.width(), old_size.height())
						except Exception:
							old_size_t = (old_size[0], old_size[1]) if isinstance(old_size, (list, tuple)) else old_size
						if (new_pos != old_pos) or (new_size != old_size_t):
							cmd = TransformCommand(item, old_pos, old_size_t, new_pos, new_size,
												   text = "Transform Item")
							batch.add(cmd)
					if batch.cmds:
						self.allow_rebuild_ini = False
						# Push to undo stack (redo will just reapply, but state already matches)
						self.undo_stack.push(batch)

					# Finish the edit mode so selection/click can proceed cleanly
					self.exit_edit_mode()
					self.rebuild_ini()
					# Do NOT return True here — allow the event to continue so Qt will select the clicked item.
			except Exception:
				# defensive: if anything goes wrong, restore a safe state and continue
				try:
					self.exit_edit_mode()
					self.rebuild_ini()
				except Exception:
					pass

		elif self.edit_mode and self.edit_items and event.type() == QEvent.MouseMove:
			scene_pos = self.view.mapToScene(self.view.viewport().mapFromGlobal(QCursor.pos()))
			delta = scene_pos - self.start_pos

			for item in self.edit_items:
				start_pos, start_size = self.start_item_states[item]
				if self.edit_mode == "move":
					new_pos = start_pos + delta

					if QApplication.keyboardModifiers() & Qt.ShiftModifier:
						g = self.view.base_grid * self.view.grid_scale
						new_pos.setX(snap(new_pos.x(), g))
						new_pos.setY(snap(new_pos.y(), g))

					if self.lock_x:
						new_pos.setX(start_pos.x())
					if self.lock_z:
						new_pos.setY(start_pos.y())

					item.setPos(new_pos)

					new_screen_pos = self.scene_to_screen(new_pos)
					self.settings_pos_x_entry.setText(str(int(new_screen_pos.x())))
					self.settings_pos_y_entry.setText(str(int(new_screen_pos.y())))

				elif self.edit_mode == "scale":
					new_w = start_size.width() + delta.x()
					new_h = start_size.height() + delta.y()

					if QApplication.keyboardModifiers() & Qt.ShiftModifier:
						g = self.view.base_grid * self.view.grid_scale
						new_w = snap(new_w, g)
						new_h = snap(new_h, g)

					new_w = max(1, new_w)
					new_h = max(1, new_h)

					scale_x = new_w / start_size.width()
					scale_y = new_h / start_size.height()

					cursor_pos = QCursor.pos()
					self.cursor_overlay.update_text(f"Width: {scale_x:.2f}x | Height: {scale_y:.2f}x", cursor_pos)

					if self.lock_aspect:
						aspect = start_size.width() / start_size.height()
						new_h = int(new_w / aspect)
					else:
						if self.lock_x:
							new_w = start_size.width()
						if self.lock_z:
							new_h = start_size.height()

					# Scale from pristine source to avoid cumulative resampling
					pixmap = safe_scaled(item.original_pixmap, int(new_w), int(new_h))
					item.setPixmap(pixmap)
					# Apply tint to the currently displayed pixmap (preserve size)
					# item.apply_tint()

					self.settings_width_entry.setText(str(int(new_w)))
					self.settings_height_entry.setText(str(int(new_h)))

			return True

		elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
			if self.edit_mode:
				# Build transform commands for any items that changed during the edit operation
				try:
					batch = BatchCommand("Transform Items")
					for item, (old_pos, old_size) in list(self.start_item_states.items()):
						new_pos = item.pos()
						new_size = (item.pixmap().width(), item.pixmap().height())
						try:
							old_size_t = (old_size.width(), old_size.height())
						except Exception:
							old_size_t = (old_size[0], old_size[1]) if isinstance(old_size, (list, tuple)) else old_size
						if (new_pos != old_pos) or (new_size != old_size_t):
							cmd = TransformCommand(item, old_pos, old_size_t, new_pos, new_size,
												   text = "Transform Item")
							batch.add(cmd)
					if batch.cmds:
						self.allow_rebuild_ini = False
						self.undo_stack.push(batch)
				except Exception:
					pass

				self.exit_edit_mode()
				self.rebuild_ini()
				return True

		return super().eventFilter(obj, event)

	# ---------------- Helper: restore original positions/sizes ----------------
	def restore_start_states(self):
		for item, (pos, size) in self.start_item_states.items():
			item.setPos(pos)
			pixmap = safe_scaled(item.original_pixmap, size.width(), size.height())
			item.setPixmap(pixmap)
			item.apply_tint()

		self.rebuild_ini()

	# ---------------- Enter / Exit Edit Mode ----------------
	def enter_edit_mode(self, mode):
		self.edit_mode = mode
		self.lock_x = False
		self.lock_z = False
		self.lock_aspect = False

		# store current mouse position
		self.start_pos = self.view.mapToScene(self.view.viewport().mapFromGlobal(QCursor.pos()))

	def exit_edit_mode(self):
		self.edit_items = [item for item in self.display_items if
						   item.name in [i.name for i in self.get_selected_display_items()]]
		self.start_item_states = {item: (item.pos(), item.pixmap().size()) for item in self.edit_items}
		# store offset between mouse and each item
		scene_pos = self.view.mapToScene(self.view.viewport().mapFromGlobal(QCursor.pos()))
		self.start_pos = scene_pos
		self.item_mouse_offsets = {item: item.pos() - scene_pos for item in self.edit_items}

		self.lock_x = False
		self.lock_z = False
		self.lock_aspect = False
		self.edit_mode = None

		self.view.show_grid = False
		self.view.viewport().update()

		self.cursor_overlay.hide()

	# ---------------- Utility Functions ----------------
	def scene_to_screen(self, scene_pos):
		widget_point = self.view.mapFromScene(scene_pos)
		return self.view.viewport().mapToGlobal(widget_point)

	def screen_to_scene(self, screen_pos):
		widget_point = self.view.viewport().mapFromGlobal(screen_pos)
		return self.view.mapToScene(widget_point)

	# ---------------- Template / Display Methods ----------------
	def select_image(self):
		file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.bmp, *.dds)")
		if file_path:
			self.current_pixmap = load_pixmap_any(file_path, self.pixmap_cache)
			self.current_template_image_path = file_path
			self.image_path_label.setText(file_path.split('/')[-1])
			self.width_input.setText(str(self.current_pixmap.width()))
			self.height_input.setText(str(self.current_pixmap.height()))

	def add_template_element(self):
		name = self.element_name_input.text() or "Element"
		type_name = self.type_combo.currentText() or "Visual"

		existing_names = [t.name for t in self.templates]

		if name in existing_names:
			idx = 1
			while f"{name}_{idx}" in existing_names:
				idx += 1
			name = f"{name}_{idx}"

		pixmap = self.current_pixmap or QPixmap(100, 50)

		width = int(self.width_input.text()) if self.width_input.text().isdigit() else pixmap.width()
		height = int(self.height_input.text()) if self.height_input.text().isdigit() else pixmap.height()

		# pixmap = safe_scaled(pixmap, width, height)

		tint_percent = self.template_tint_slider.value()

		template = Template(name, type_name, pixmap, width, height, self.current_template_image_path, tint_percent)

		self.templates.append(template)
		self.template_list_widget.addItem(name)
		self.template_list_widget.setCurrentRow(self.template_list_widget.count() - 1)
		# save templates whenever user adds a new one (explicit)
		self.save_templates()

	def apply_all_changes(self):
		item = self.active_item
		if not item:
			return

		# ---- find corresponding outliner item ----
		tree_item = None
		for it in self.iter_outliner_items():
			if it.data(1, Qt.UserRole) is item:
				tree_item = it
				break
		if not tree_item:
			return

		batch = BatchCommand("Apply Changes")

		# ---- Name change ----
		item_new_name = self.settings_name_entry.text().strip() or item.name
		if item_new_name != item.name:
			cmd_name = PropertyCommand(item, "name", item.name, item_new_name, text = "Rename Item")
			batch.add(cmd_name)

		# ---- Type Change ----
		new_type = self.settings_type_name.currentText() or 'Visual'
		if new_type != item.type_name:
			cmd_name = PropertyCommand(item, "type_name", item.type_name, new_type, text = "Change Type")
			batch.add(cmd_name)

		# ---- Toggles amount change ----
		try:
			new_toggles = int(self.settings_toggles_amount.text())
			new_toggles = max(1, new_toggles)
		except Exception:
			new_toggles = None

		if new_toggles is not None:
			old_toggles = getattr(item, "toggles_amount", 0)

			if new_toggles != old_toggles:
				cmd_toggles = PropertyCommand(
					item,
					"toggles_amount",
					old_toggles,
					new_toggles,
					text = "Change Toggles Amount"
				)
				batch.add(cmd_toggles)

		# ---- Size change ----
		try:
			w = int(self.settings_width_entry.text())
			h = int(self.settings_height_entry.text())
			w = max(1, w)
			h = max(1, h)
		except Exception:
			w = None
			h = None

		old_pos = item.pos()
		old_size = (item.pixmap().width(), item.pixmap().height())
		new_pos = old_pos
		new_size = old_size

		if w and h:
			new_size = (w, h)

		# ---- Position change (screen → scene) ----
		try:
			x_screen = int(self.settings_pos_x_entry.text())
			y_screen = int(self.settings_pos_y_entry.text())
			scene_point = self.screen_to_scene(QPoint(x_screen, y_screen))
			new_pos = QPointF(scene_point.x(), scene_point.y())
		except Exception:
			pass

		if new_pos != old_pos or new_size != old_size:
			cmd_tf = TransformCommand(item, old_pos, old_size, new_pos, new_size, text = "Apply Transform")
			batch.add(cmd_tf)

		# ---- Parent Change ----
		try:
			new_parent = str(self.parent_select.currentText())
		except Exception:
			new_parent = None

		old_parent = item.parent_item or None

		if new_parent != old_parent:
			cmd_tf = PropertyCommand(item, "parent_item", item.parent_item, new_parent, text = "Change Parent")
			batch.add(cmd_tf)

		if batch.cmds:
			try:
				self.undo_stack.push(batch)
			except Exception:
				# fallback: apply directly
				for c in batch.cmds:
					c.redo()

		self.rebuild_outliner()
		self.rebuild_ini()

	def add_selected_template_to_display(self):
		# Create item from selected template and use AddRemoveCommand to add it so it's undoable
		list_items = self.template_list_widget.selectedItems()
		if not list_items:
			return
		list_item = list_items[0]
		template = next((t for t in self.templates if t.name == list_item.text()), None)
		if template is None:
			return

		name = template.name
		i = 1
		while any(it.name == name for it in self.display_items):
			name = f"{template.name}_{i}"
			i += 1

		pixmap = template.pixmap
		pixmap_scaled = safe_scaled(pixmap, template.width, template.height)

		item = DisplayedItem(
			pixmap_scaled,
			og_pixmap = pixmap,
			pixmap_path = template.path or "",
			name = name,
			template_name = template.name,
			type_name = template.type_name
		)

		item.setZValue(len(self.display_items))
		center = self.view.mapToScene(self.view.viewport().rect().center())
		item.setPos(center.x() - pixmap_scaled.width() / 2, center.y() - pixmap_scaled.height() / 2)

		cmd = AddRemoveCommand(self, item, adding = True, text = f"Add {item.name}")
		try:
			try:
				self.allow_rebuild_ini = False
				self.undo_stack.blockSignals(True)
				self.undo_stack.push(cmd)
				self.undo_stack.blockSignals(False)

			except Exception as e:
				print("[WARN] undo_stack.push failed:", repr(e))
				# fallback: spróbuj wykonać redo (bez zapisu w stacku)
				try:
					cmd.redo()
				except Exception:
					pass
		except Exception:
			if not item.scene():
				self.scene.addItem(item)
			self.display_items.append(item)

		self.rebuild_outliner()
		self.rebuild_ini()

	def delete_selected_template_element(self):
		selected_items = self.template_list_widget.selectedItems()

		reply = QMessageBox.question(
			self,
			"Confirm Delete",
			f"Are you sure you want to Delete {len(selected_items)} Selected Template Element(s)?",
			QMessageBox.Yes | QMessageBox.No
		)
		if reply == QMessageBox.No:
			return

		for list_item in selected_items:
			self.template_list_widget.takeItem(self.template_list_widget.row(list_item))
			self.templates = [t for t in self.templates if t.name != list_item.text()]
		self.save_templates()

	def update_selected_template(self):
		# Get selected template in the list
		list_items = self.template_list_widget.selectedItems()
		if not list_items:
			return
		list_item = list_items[0]
		template = next((t for t in self.templates if t.name == list_item.text()), None)
		if template is None:
			return

		# Update template properties from input fields
		new_name = self.element_name_input.text().strip()
		if new_name:
			# Ensure uniqueness
			name = new_name
			i = 1
			while any(t.name == name and t is not template for t in self.templates):
				name = f"{new_name}_{i}"
				i += 1
			template.name = name
			list_item.setText(name)

		template.type_name = self.type_combo.currentText()
		template.width = int(self.width_input.text() or template.width or 0)
		template.height = int(self.height_input.text() or template.height or 0)
		template.path = self.current_template_image_path if self.image_path_label.text() != "No Image Selected" else template.path

		# Update pixmap if a new image was selected
		if template.path and os.path.isfile(template.path):
			pixmap = load_pixmap_any(template.path, self.pixmap_cache)
			# pixmap = safe_scaled(pixmap, template.width, template.height)
			template.pixmap = pixmap

	def on_template_selection_changed(self):
		selected_items = self.template_list_widget.selectedItems()
		if not selected_items:
			self.element_name_input.setText("")
			self.type_combo.setCurrentText("")
			self.width_input.setText("0")
			self.height_input.setText("0")
			self.current_pixmap = None
			self.image_path_label.setText("No Image Selected")
			self.template_tint_slider.setValue(0)
			return

		list_item = selected_items[0]
		template = next((t for t in self.templates if t.name == list_item.text()), None)

		if template:
			self.element_name_input.setText(template.name)
			self.type_combo.setCurrentText(template.type_name)
			self.width_input.setText(str(template.width))
			self.height_input.setText(str(template.height))
			self.current_pixmap = template.pixmap
			self.image_path_label.setText(template.path.split('/')[-1] if template.path else "No Image Selected")
			self.template_tint_slider.setValue(template.tint_percent)

	def update_selected_template_tint(self, value):
		selected_items = self.template_list_widget.selectedItems()
		if not selected_items:
			return
		list_item = selected_items[0]
		template = next((t for t in self.templates if t.name == list_item.text()), None)
		if template:
			template.tint_percent = value
			self.save_templates()

	def on_scene_selection_changed(self):
		# zabezpieczenie
		if getattr(self, "_syncing_selection", False):
			return

		self._syncing_selection = True
		try:
			scene_selected = self.scene.selectedItems()  # LISTA: order matters

			# translate outliner selected items -> list of el
			out_items = [it for it in self.outliner.selectedItems() if it.data(0, Qt.UserRole) == "ELEMENT"]
			outliner_selected_els = [it.data(1, Qt.UserRole) for it in out_items]

			# ADD: zaznacz w outlinerze te z scene które tam nie ma
			for el in scene_selected:
				if el not in outliner_selected_els:
					# select_element nie powinien ustawiać current/scroll
					self.outliner.select_element(el, make_current = False)

			# REMOVE: odznacz w outlinerze te, których nie ma już w scene
			for el in list(outliner_selected_els):
				if el not in scene_selected:
					self.outliner.deselect_element(el)

			# ustaw last_selected (ostatni w liście scene_selected) i ustaw go jako current raz
			if scene_selected:
				self.last_selected = scene_selected[-1]
				self.active_item = self.last_selected  # <<< THIS IS THE FIX

				QTimer.singleShot(0, lambda: self.load_item_to_settings(self.last_selected))
				self.settings_panel.setVisible(True)

				# --- setup edit state ---
				self.edit_items = scene_selected

				if self.active_item in scene_selected:
					self.last_selected = self.active_item
				else:
					self.last_selected = scene_selected[-1]

				self.start_item_states = {
					item: (item.pos(), item.pixmap().size())
					for item in self.edit_items
				}

				scene_pos = self.view.mapToScene(
					self.view.viewport().mapFromGlobal(QCursor.pos())
				)

				self.item_mouse_offsets = {
					item: item.pos() - scene_pos
					for item in self.edit_items
				}

			else:
				self.last_selected = None
				self.active_item = None  # <<< symmetry
				self.settings_panel.setVisible(False)

		finally:
			self._syncing_selection = False

	def load_item_to_settings(self, item):
		if not item:
			return

		self._ui_changing = True

		self.settings_panel.setVisible(True)
		self.settings_name_entry.setText(item.name)
		self.settings_toggles_amount.setText(str(item.toggles_amount))
		self.settings_width_entry.setText(str(item.pixmap().width()))
		self.settings_type_name.setCurrentText(item.type_name if item.type_name else 'Visual')
		self.settings_height_entry.setText(str(item.pixmap().height()))
		parent_names = [""] + [i.name for i in self.display_items if i != item]
		self.parent_select.clear()
		self.parent_select.addItems(parent_names)
		self.parent_select.setCurrentText(item.parent_item if item.parent_item else '')
		self.settings_tint_slider.setValue(item.tint_percent)

		screen_point = self.scene_to_screen(item.pos())
		self.settings_pos_x_entry.setText(str(int(screen_point.x())))
		self.settings_pos_y_entry.setText(str(int(screen_point.y())))

		if item.parent_item:
			parent = next((elem for elem in self.display_items if elem.name == item.parent_item), None)

			if parent is None:
				return

			parent_screen = self.scene_to_screen(parent.pos())
			self.parent_offset_x_entry.setText(str(int(screen_point.x() - parent_screen.x())))
			self.parent_offset_y_entry.setText(str(int(screen_point.y() - parent_screen.y())))
		else:
			self.parent_offset_x_entry.setText(str(0))
			self.parent_offset_y_entry.setText(str(0))

		self._ui_changing = False

	def update_z_order(self, parent, start, end, destination, row):
		for idx in range(self.outliner.topLevelItemCount()):
			tree_item = self.outliner.topLevelItem(idx)
			el = tree_item.data(0, Qt.UserRole)
			if el:
				el.setZValue(idx)

		self.rebuild_ini()

		item = self.active_item

		if not item:
			return

		# ---- find corresponding outliner item ----
		tree_item = None
		for it in self.iter_outliner_items():
			if it.data(1, Qt.UserRole) is item:
				tree_item = it
				break

		if not tree_item:
			return

		self.rebuild_outliner()
		self.rebuild_ini()

	def save_templates(self):
		data = [t.to_dict() for t in self.templates]
		with open(os.path.join(SAVE_DIR, TEMPLATES_FILE), "w", encoding = "utf-8") as f:
			json.dump(data, f, indent = 2)

	def load_templates(self):
		path = os.path.join(SAVE_DIR, TEMPLATES_FILE)
		if os.path.exists(path):
			with open(path, "r", encoding = "utf-8") as f:
				data = json.load(f)
			self.templates = []
			self.template_list_widget.clear()
			# First create raw templates (no inheritance resolve)
			raw_templates = {}
			for d in data:
				pixmap = load_pixmap_any(d["path"], self.pixmap_cache) if d.get("path") and os.path.exists(
					d["path"]) else QPixmap(
					d.get("width", 100), d.get("height", 50))
				# pixmap = safe_scaled(pixmap, d.get("width", 100), d.get("height", 50))

				tmpl = Template.from_dict(d, pixmap)
				raw_templates[tmpl.name] = tmpl

			# Resolve simple inheritance (multiple levels allowed)
			def resolve(name, visited=None):
				if visited is None:
					visited = set()
				if name in visited:
					return raw_templates.get(name)
				visited.add(name)
				t = raw_templates.get(name)
				if not t:
					return None
				if t.extends:
					parent = resolve(t.extends, visited)
					if parent:
						# Inherit fields if missing
						if not t.path:
							t.path = parent.path
							t.pixmap = parent.pixmap.copy()
						if not t.width:
							t.width = parent.width
						if not t.height:
							t.height = parent.height
						if t.tint_percent is None:
							t.tint_percent = parent.tint_percent
				return t

			for name in list(raw_templates.keys()):
				t = resolve(name)
				if t:
					self.templates.append(t)
					self.template_list_widget.addItem(t.name)

	# ---------------- Last Session Save/Load ----------------

	def serialize_groups_for_save(self, groups: dict) -> dict:
		out = {}
		for k, v in groups.items():
			if k == "ROOT_ALWAYS":
				out["ROOT_ALWAYS"] = list(v)  # keep list of group names
			elif isinstance(k, int):
				out[str(k)] = list(v)  # convert index -> string key
			else:
				# unknown key type: stringify it but warn
				out[str(k)] = list(v)
		return out

	# Convert saved JSON back to runtime shape: int keys where possible
	def deserialize_groups_from_save(self, saved: dict) -> dict:
		out = {}
		for k, v in (saved or {}).items():
			if k == "ROOT_ALWAYS":
				out["ROOT_ALWAYS"] = list(v)
			else:
				# try to convert numeric-string keys back to int
				try:
					ik = int(k)
					out[ik] = list(v)
				except ValueError:
					# non-numeric key — preserve as string (or handle specially)
					out[k] = list(v)
		# Ensure keys exist for each page index if needed later
		return out

	# ==============================
	# Display Item Serialization
	# ==============================

	def _deserialize_display_item(self, d):
		size = d.get("size", [100, 50])
		pixmap_path = d.get("pixmap_path")

		if pixmap_path and os.path.exists(pixmap_path):
			pixmap = load_pixmap_any(pixmap_path, self.pixmap_cache)
		else:
			pixmap = QPixmap(size[0], size[1])

		pixmap_scaled = safe_scaled(pixmap, size[0], size[1])

		item = DisplayedItem(pixmap_scaled, og_pixmap = pixmap)
		item.name = d["name"]  # identity restored explicitly
		item.type_name = d.get("type_name", 'Visual')
		item.toggles_amount = d.get("toggles_amount", 1)
		item.pixmap_path = pixmap_path
		item.setPos(*d.get("pos", [0, 0]))
		item.tint_percent = d.get("tint_percent", 0)
		item.tint_color = QColor(*d.get("tint_color", [255, 255, 255]))
		item.apply_tint()
		item.setZValue(d.get("z", 0))

		item.parent_item = d.get("parent_name", '')

		item.always_visible = d.get("always_visible", False)
		item.page = None
		item.group = None

		return item

	# ==============================
	# Parenting Resolve
	# ==============================

	def _resolve_item_parents(self, items, items_data):
		by_name = {i.name: i for i in items}

		for d in items_data:
			child = by_name.get(d["name"])
			parent_name = d.get("parent_name")
			if child and parent_name:
				parent = by_name.get(parent_name)
				if parent:
					child.parent_item = parent_name
					parent.children.append(child)

	# ==============================
	# Save Data Builder
	# ==============================

	def debug_list(self, name, items):
		for i, item in enumerate(items):
			if not hasattr(item, "to_dict"):
				print(f"[BAD {name}]", i, type(item), repr(item))

	def _build_save_data(self):

		data = {
			"version": 1,
			"pages": list(self.pages),  # whatever shape you already store
			"groups": self.serialize_groups_for_save(self.groups),
			"display_items": [item.to_dict() for item in self.display_items if hasattr(item, "to_dict")],
			"code_elements": [ce.to_dict() for ce in self.code_elements if hasattr(ce, "to_dict")],
			"ini": getattr(self, "current_ini_path", "") or "",
			"ifs": getattr(self, "bindings_dialog").saved_edits or {}
		}

		_assert_json_safe(data)
		return data

	# ==============================
	# Save Entry Points
	# ==============================

	def save_last_session(self):
		os.makedirs(SAVE_DIR, exist_ok = True)
		final = os.path.join(SAVE_DIR, LAST_SESSION_FILE)
		tmp = final + ".tmp"

		data = self._build_save_data()  # ← may fail

		with open(tmp, "w", encoding = "utf-8") as f:
			json.dump(data, f, indent = 2)

		os.replace(tmp, final)
		print(f"[{datetime.now()}] Last session Auto-Saved.")
		self.statusBar().showMessage(f"[{datetime.now()}] Last session Auto-Saved.", 3000)

	def save_custom_layout(self):
		filename, _ = QFileDialog.getSaveFileName(
			self, "Save Custom Layout", LAYOUTS_DIR, "JSON Files (*.json)"
		)
		if not filename:
			return

		with open(filename, "w", encoding = "utf-8") as f:
			json.dump(self._build_save_data(), f, indent = 2)

		self.statusBar().showMessage(f"Layout Saved to {filename}", 3000)

	# ==============================
	# Load Layout Data
	# ==============================

	def _load_layout_data(self, data):
		self.loading_data = True

		# clear scene and items
		for item in list(self.display_items):
			try:
				self.scene.removeItem(item)
			except Exception:
				pass
		self.display_items.clear()

		# ---- pages
		# Expecting list of page dicts or list of names. Support both.
		self.pages = []
		page_map = {}  # map page id or index -> Page-like object or name
		pages_data = data.get("pages", [])
		if isinstance(pages_data, list):
			# if list of simple names
			if pages_data and isinstance(pages_data[0], str):
				for idx, name in enumerate(pages_data):
					self.pages.append(name)
					page_map[idx] = name
			else:
				# list of dicts (Page.from_dict if available)
				for p in pages_data:
					try:
						page = Page.from_dict(p)
					except Exception:
						# fallback: minimal page representation
						page = p
					# add either the page.name or the page object depending on rest of your code
					name = getattr(page, "name", None) or p.get("name") or str(p.get("id", len(self.pages)))
					self.pages.append(name)
					# map by id (if present) and by index for compatibility
					pid = p.get("id", len(self.pages) - 1) if isinstance(p, dict) else getattr(page, "id",
																							   len(self.pages) - 1)
					page_map[pid] = name
					page_map[len(self.pages) - 1] = name
		else:
			self.pages = []

		# ---- groups
		# We will construct self.groups to match the runtime shape used by OutlinerTree:
		# a dict keyed by "ROOT_ALWAYS" and integer page indices -> list of group names
		self.groups = {}
		group_map = {}  # optional map if groups are stored with ids

		raw_groups = self.deserialize_groups_from_save(data.get("groups", {}))
		# Support multiple possible saved shapes:
		#  - dict mapping keys ("ROOT_ALWAYS" or page index as str/int) -> list of names
		#  - list of group dicts with fields {id, name, page_id}
		if isinstance(raw_groups, dict):
			# assume correct mapping already
			for k, v in raw_groups.items():
				key = "ROOT_ALWAYS" if str(k).upper() == "ROOT_ALWAYS" else int(k) if str(k).isdigit() else k
				self.groups[key] = list(v) if isinstance(v, list) else []
		elif isinstance(raw_groups, list):
			# list of group dicts or simple names
			# if list of strings, assume ROOT_ALWAYS
			if raw_groups and isinstance(raw_groups[0], str):
				self.groups["ROOT_ALWAYS"] = list(raw_groups)
			else:
				# group dicts
				for g in raw_groups:
					if not isinstance(g, dict):
						continue
					gname = g.get("name") or g.get("title") or str(g.get("id", "group"))
					page_id = g.get("page_id", "ROOT_ALWAYS")
					if page_id is None:
						key = "ROOT_ALWAYS"
					else:
						try:
							key = int(page_id)
						except Exception:
							key = "ROOT_ALWAYS" if str(page_id).upper() == "ROOT_ALWAYS" else page_id
					self.groups.setdefault(key, [])
					if gname not in self.groups[key]:
						self.groups[key].append(gname)
					gid = g.get("id")
					if gid is not None:
						group_map[gid] = (key, gname)
		else:
			# nothing present -> keep existing or empty
			self.groups.setdefault("ROOT_ALWAYS", [])

		# Ensure each page index has an entry (even empty)
		for i in range(len(self.pages)):
			self.groups.setdefault(i, self.groups.get(i, []))
		self.groups.setdefault("ROOT_ALWAYS", self.groups.get("ROOT_ALWAYS", []))

		items_data = data.get("display_items", [])

		# ---- items
		# _deserialize_display_item should return a DisplayedItem instance; we then set page_index/group index correctly.
		for d in items_data:
			item = self._deserialize_display_item(d)

			# Support multiple saved keys for page/group:
			# possible keys: "page_index", "page_id", "page" (name), "group", "group_index", "group_id", "group_name"
			# normalize to page_index (int or None) and group (int index or None)
			page_index = None
			# page stored as an int index
			if "page_index" in d and d["page_index"] is not None:
				page_index = d.get("page_index")
			elif "page_id" in d and d["page_id"] is not None:
				# if page_id is numeric and we have page_map keyed by pid -> name, attempt to resolve to an index
				pid = d.get("page_id")
				if isinstance(pid, int):
					# try to find page index with same name in pages
					name = page_map.get(pid)
					if name in self.pages:
						page_index = self.pages.index(name)
					else:
						# fallback: if pid maps to an index in page_map use it
						try:
							page_index = int(pid)
						except Exception:
							page_index = None
				else:
					# string page id or name
					try:
						page_index = self.pages.index(pid)
					except Exception:
						page_index = None
			elif "page" in d and isinstance(d.get("page"), str):
				try:
					page_index = self.pages.index(d.get("page"))
				except ValueError:
					page_index = None

			# group normalization
			group_idx = None
			# if saved as integer index for that page
			if "group_index" in d and d["group_index"] is not None:
				group_idx = d.get("group_index")
			elif "group_id" in d and d["group_id"] is not None:
				gid = d.get("group_id")
				# if we created a group_map earlier map to index
				if gid in group_map:
					key, gname = group_map[gid]
					groups_list = self.groups.get(key, [])
					try:
						group_idx = groups_list.index(gname)
					except ValueError:
						group_idx = None
				else:
					# try to fallback to numeric gid meaning index
					try:
						group_idx = int(gid)
					except Exception:
						group_idx = None
			elif "group_name" in d and d["group_name"] is not None:
				gname = d.get("group_name")
				key = "ROOT_ALWAYS" if page_index is None else page_index
				groups_list = self.groups.get(key, [])
				try:
					group_idx = groups_list.index(gname)
				except ValueError:
					# not found -> append to group list for that key
					self.groups.setdefault(key, [])
					self.groups[key].append(gname)
					group_idx = len(self.groups[key]) - 1
			elif "group" in d:
				# group could be int index or name
				g = d.get("group")
				if isinstance(g, int):
					group_idx = g
				elif isinstance(g, str):
					key = "ROOT_ALWAYS" if page_index is None else page_index
					groups_list = self.groups.setdefault(key, [])
					if g not in groups_list:
						groups_list.append(g)
					group_idx = groups_list.index(g)

			# Apply normalized page_index and group index to the item
			item.page_index = page_index
			item.group = group_idx

			self.scene.addItem(item)
			self.display_items.append(item)

		# ---- parenting: resolve parent offsets/links if you store parent_id or parent_index in saved data.
		# Keep existing resolver if it expects the two lists: items and raw items_data
		try:
			self._resolve_item_parents(self.display_items, items_data)
		except Exception:
			# be defensive: ignore parent resolution failures but don't crash
			pass

		# ---- code + ini
		self.code_elements = [
			CodeElement.from_dict(d) for d in data.get("code_elements", [])
		]
		self.refresh_code_list()

		self.selected_ini_label.setText(data.get("ini", "No Ini Selected"))
		# only call load_ini_file if path present and non-empty
		ini_path = data.get("ini", "")
		if ini_path:
			try:
				self.allow_rebuild_ini = False
				self.load_ini_file(ini_path)
			except Exception:
				# ignore ini load errors for now
				pass

		# Rebuild UI structures
		try:
			self.rebuild_outliner()
		except Exception:
			pass
		try:
			self.rebuild_ini()
		except Exception:
			pass
		try:
			# after loading:
			ifs = data.get("ifs", {})
			if isinstance(ifs, dict):
				_normalize_saved_edits_vidx(ifs)
			else:
				ifs = {}

			self.saved_edits = ifs

			ini_text = self.ini_editor.toPlainText()
			dialog = BindingsEditorDialog(ini_text, self, self.current_ini_path, self.saved_edits)
			dialog.apply_all()
		except Exception:
			pass

		self.loading_data = False

	# ==============================
	# Snapshot before Re:Startin the Project
	# ==============================

	def save_snapshot(self, name=None, include=None):
		"""
        Save a minimal snapshot.
        `name` = optional snapshot name
        `include` = list of sections to include: "templates", "display_items", "code_elements", "types"
        """
		include = include or ["templates", "display_items", "code_elements", "types", "pages", "groups"]

		snap = {
			"timestamp": datetime.now().isoformat(),
			"ini": getattr(self, "current_ini_path", ""),
			"ifs": getattr(self, "bindings_dialog", {}).saved_edits or {}
		}

		if "display_items" in include:
			snap["display_items"] = [item.to_dict() for item in self.display_items]
		if "code_elements" in include:
			snap["code_elements"] = [ce.to_dict() for ce in self.code_elements]
		if "templates" in include:
			snap["templates"] = [t.to_dict() for t in self.templates]
		if "types" in include:
			snap["types"] = [t for t in self.types if not t.get("default", False)]
		if "pages" in include:
			snap["pages"] = list(self.pages)
		if "groups" in include:
			snap["groups"] = self.serialize_groups_for_save(self.groups)

		# Save to Disk
		filename = os.path.join(SNAPSHOT_DIR,
								name + ".json" if name else f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
		with open(filename, "w", encoding = "utf-8") as f:
			json.dump(snap, f, indent = 2)
		print(f"[INFO] Snapshot saved: {filename}")
		self.statusBar().showMessage(f"[INFO] Snapshot saved: {filename}", 3000)

	def load_snapshot(self, name_or_path, restore=None):
		"""
        Load a snapshot file and return its data (dict).
        If `restore` is a list of sections, perform the restore (compatibility mode).
        """
		self.loading_data = True

		# try to resolve candidate filename(s)
		candidates = []
		# if absolute or relative path passed directly
		if os.path.exists(name_or_path):
			candidates.append(name_or_path)
		# name might already be "snapshot_123"
		candidates.append(os.path.join(SNAPSHOT_DIR, f"{name_or_path}.json"))
		candidates.append(os.path.join(SNAPSHOT_DIR, name_or_path))
		# also try with snapshot_ prefix if user passed only suffix like "123"
		if not name_or_path.startswith("snapshot_"):
			candidates.append(os.path.join(SNAPSHOT_DIR, f"{name_or_path}.json"))

		filepath = None
		for c in candidates:
			try:
				if c and os.path.exists(c):
					filepath = c
					break
			except Exception:
				pass

		if not filepath:
			raise FileNotFoundError(f"Snapshot file not found (checked candidates): {candidates}")

		with open(filepath, "r", encoding = "utf-8") as f:
			snap = json.load(f)

		# If caller only wants the snap data, return it
		if restore is None:
			return snap

		# Otherwise perform in-place restore for requested sections (compatibility branch).
		# restore is expected to be list like ["templates","display_items",...]
		if "pages" in snap:
			self.pages = snap["pages"]
		if "groups" in snap:
			try:
				self.groups = self.deserialize_groups_from_save(snap["groups"])
			except Exception:
				pass

		if "display_items" in restore and "display_items" in snap:
			for item in list(self.display_items):
				try:
					self.scene.removeItem(item)
				except Exception:
					pass
			self.display_items.clear()
			for d in snap["display_items"]:
				item = self._deserialize_display_item(d)
				self.display_items.append(item)
				self.scene.addItem(item)
			try:
				self._resolve_item_parents(self.display_items, snap["display_items"])
			except Exception:
				pass

		if "code_elements" in restore and "code_elements" in snap:
			self.code_elements = [CodeElement.from_dict(d) for d in snap["code_elements"]]
			self.refresh_code_list()

		if "templates" in restore and "templates" in snap:
			self.templates.clear()
			self.template_list_widget.clear()
			for t in snap["templates"]:
				pixmap = load_pixmap_any(t.get("path", ""), self.pixmap_cache) if t.get("path") else QPixmap(
					t.get("width", 100), t.get("height", 50))
				# pixmap = safe_scaled(pixmap, t.get("width", 100), t.get("height", 50))
				tmpl = Template.from_dict(t, pixmap)
				self.templates.append(tmpl)
				self.template_list_widget.addItem(tmpl.name)

		if "types" in restore and "types" in snap:
			self.types = [t for t in self.types if t.get("default", False)]
			self.types.extend(snap["types"])

		if "ini" in snap and snap["ini"]:
			try:
				self.load_ini_file(snap["ini"])
			except Exception:
				pass
		if "ifs" in snap:
			self.saved_edits = snap["ifs"]

		try:
			self.rebuild_outliner()
		except Exception:
			pass

		self.loading_data = False

		# return the loaded snapshot as well (useful if caller wants to inspect)
		return snap

	# ==============================
	# Load Entry Points
	# ==============================

	def load_last_session(self):
		path = os.path.join(SAVE_DIR, LAST_SESSION_FILE)
		if not os.path.exists(path):
			return

		with open(path, "r", encoding = "utf-8") as f:
			self._load_layout_data(json.load(f))

	def load_custom_layout(self):
		filename, _ = QFileDialog.getOpenFileName(
			self, "Load Custom Layout", LAYOUTS_DIR, "JSON Files (*.json)"
		)
		if not filename:
			return

		with open(filename, "r", encoding = "utf-8") as f:
			self._load_layout_data(json.load(f))

		self.statusBar().showMessage(f"Layout Loaded from {filename}", 3000)

	# ---------------- Close event -> save one more time ----------------
	def closeEvent(self, event):
		try:
			self.undo_stack.indexChanged.disconnect()
			self.scene.selectionChanged.disconnect(self.on_scene_selection_changed)
			self.save_last_session()
			self.save_templates()
			self.save_types()
		except Exception as e:
			print("[ERROR] Save on exit failed:", e)
		super().closeEvent(event)


CONFIG_PATH = "Saves/Config.json"

# ---------------- DEFAULTS ----------------

DEFAULT_CONFIG = {
	"version": VERSION,
	"first_run": 1,
	"platform_args": ["-platform", "windows:darkmode=2"],
	"style": "Basic",
	"theme": "dark",
	"accent_color": "#00CFFF",
	"font": "Segoe UI",
	"font_size": 9,
	"save_interval": 5,
	"auto_if": True,
	"update_channel": "Main",
	"update_owner": "NurarihyonMaou",
	"update_repo": "MenuCreator",
	"update_manifest_path": UPDATE_MANIFEST_PATH_DEFAULT,
	"update_main_branch": "Main",
	"update_beta_branch": "Beta",
	"update_private_code": "",
	"update_private_redeem_url": UPDATE_PRIVATE_REDEEM_URL_DEFAULT,
	"update_private_manifest_url": UPDATE_PRIVATE_MANIFEST_URL_DEFAULT,
	"update_auto_check": False
}

AVAILABLE_PLATFORM_ARGS = [
	[],
	["-platform", "windows:darkmode=0"],
	["-platform", "windows:darkmode=1"],
	["-platform", "windows:darkmode=2"],
]


# ---------------- CONFIG IO ----------------

def load_config():
	os.makedirs("Saves", exist_ok = True)

	if not os.path.exists(CONFIG_PATH):
		save_config(DEFAULT_CONFIG)
		return DEFAULT_CONFIG.copy()

	try:
		with open(CONFIG_PATH, "r", encoding = "utf-8") as f:
			data = json.load(f)

		cfg = DEFAULT_CONFIG.copy()
		cfg.update(data)
		return cfg
	except:
		return DEFAULT_CONFIG.copy()


def save_config(cfg):
	cfg["version"] = VERSION
	cfg["first_run"] = 0

	with open(CONFIG_PATH, "w", encoding = "utf-8") as f:
		json.dump(cfg, f, indent = 4)


# ---------------- PALETTE ----------------

def make_dark_palette(accent="#00CFFF"):
	pal = QPalette()

	base = QColor(30, 30, 30)
	text = QColor(220, 220, 220)
	accent = QColor(accent)

	pal.setColor(QPalette.Window, base)
	pal.setColor(QPalette.WindowText, text)
	pal.setColor(QPalette.Base, QColor(22, 22, 22))
	pal.setColor(QPalette.AlternateBase, base)
	pal.setColor(QPalette.Text, text)
	pal.setColor(QPalette.Button, base)
	pal.setColor(QPalette.ButtonText, text)
	pal.setColor(QPalette.Highlight, accent)
	pal.setColor(QPalette.HighlightedText, QColor(0, 0, 0))

	return pal


# ---------------- APPLY CONFIG ----------------

def apply_config(app, cfg):
	app.setStyle(cfg["style"])

	app.setFont(QFont(cfg["font"], cfg["font_size"]))

	if not is_windows_dark_mode():
		cfg["theme"] = "Light"

	elif cfg["theme"] == "Light":
		cfg["theme"] = "Default"

	if cfg["theme"] == "Dark":
		app.setPalette(make_dark_palette(cfg["accent_color"]))

	elif cfg["theme"] == "Light":
		app.setPalette(app.style().standardPalette())

		app.setStyleSheet("""
            QComboBox QAbstractItemView {
                background-color: white;
                color: black;
            }
        """)
	else:
		app.setPalette(QPalette())

	if editor and not cfg["theme"] == "Light":
		editor.selected_ini_label.setStyleSheet("color: white;")
		editor.ini_editor_frame.setStyleSheet(
			"background-color: rgba(30, 30, 30, 180); border:1px solid gray;")
		editor.ini_editor.setStyleSheet(
			"background-color: rgba(30, 30, 30, 180); color: white; border:none;")

		app.setStyleSheet("")


# ---------------- APP INIT ----------------

def init_app(cfg):
	for arg in cfg["platform_args"]:
		if arg not in sys.argv:
			sys.argv.append(arg)

	app = QApplication(sys.argv)
	apply_config(app, cfg)
	return app


# ---------------- UPDATE MANAGER ----------------

SUFFIX_PRIORITY = {
	"hotfix": 4,
	"": 3,
    "b": 2,
    "beta": 1,
    "alpha": 0,
}


def parse_version_build(v: str):
	if not v:
		return (0, 0, 0, 0)

	nums = re.findall(r"\d+", v)
	nums = list(map(int, nums[:3]))

	while len(nums) < 3:
		nums.append(0)

	suffix = re.findall(r"[A-Za-z]+$", v)
	suffix = suffix[0].lower() if suffix else ""

	return (*nums, SUFFIX_PRIORITY.get(suffix, 3))


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		while True:
			chunk = f.read(chunk_size)
			if not chunk:
				break
			h.update(chunk)
	return h.hexdigest()


def assert_https(url: str) -> None:
	url = (url or "").strip()
	if url and not url.lower().startswith("https://"):
		raise ValueError(f"Blocked non-HTTPS URL: {url}")


def verify_manifest_signature(manifest: dict) -> bool:
	signature = (manifest.get("signature") or "").strip()
	if not signature:
		return not UPDATE_REQUIRE_SIGNATURE

	if not HAS_CRYPTO:
		raise RuntimeError("Manifest signature present, but cryptography is not available")

	pubkey = (PUBLIC_KEY or "").strip()
	if not pubkey or "TU_WKLEJ_PUBLIC_KEY" in pubkey:
		raise RuntimeError("Manifest signature present, but PUBLIC_KEY is not configured")

	payload = dict(manifest)
	payload.pop("signature", None)
	data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

	try:
		sig_bytes = base64.b64decode(signature)
	except Exception as e:
		raise ValueError(f"Invalid manifest signature encoding: {e}")

	pub = serialization.load_pem_public_key(pubkey.encode("utf-8"))
	pub.verify(sig_bytes, data, padding.PKCS1v15(), hashes.SHA256())
	return True


def create_update_backup(target_path: str) -> str:
	target_path = os.path.abspath(target_path)
	backup_path = target_path + ".backup"
	if os.path.exists(target_path):
		shutil.copy2(target_path, backup_path)
	return backup_path


def check_failed_update() -> None:
	try:
		target_path = current_install_target()
		folder = os.path.dirname(target_path)
		flag_path = os.path.join(folder, "update_failed.flag")
		backup_path = target_path + ".backup"

		if not os.path.exists(flag_path):
			return

		logger.warning("Previous update marked as failed.")

		# Best-effort auto-restore for script/dev mode.
		if os.path.exists(backup_path) and not getattr(sys, "frozen", False):
			try:
				shutil.copy2(backup_path, target_path)
				logger.info("Restored backup after failed update.")
			except Exception as e:
				logger.error(f"Backup restore failed: {e}")

		try:
			os.remove(flag_path)
		except Exception:
			pass
	except Exception as e:
			logger.info(f"Failed-update check skipped: {e}")


def fetch_json_url(url: str, timeout: int = 20) -> dict:
	req = Request(url, headers = {"User-Agent": "MenuCreator-Updater/1.0"})
	with urlopen(req, timeout = timeout) as resp:
		payload = resp.read().decode("utf-8")
	data = json.loads(payload)
	if not isinstance(data, dict):
		raise ValueError("Manifest payload is not a JSON object")
	return data


def build_public_manifest_url(cfg: dict, channel: str) -> str:
	owner = (cfg.get("update_owner") or "").strip()
	repo = (cfg.get("update_repo") or "").strip()
	manifest_path = (cfg.get("update_manifest_path") or UPDATE_MANIFEST_PATH_DEFAULT).strip().lstrip("/")
	branch = (cfg.get(f"update_{channel}_branch") or channel).strip()

	if not owner or not repo:
		raise ValueError("GitHub Owner/Repo are not set in Settings")

	return f"https://raw.githubusercontent.com/{owner}/{repo}/refs/heads/main/{manifest_path}/{branch}/Manifest.json"


def current_install_target() -> str:
	if getattr(sys, "frozen", False):
		return os.path.abspath(sys.executable)
	if ALLOW_DEV_UPDATES and sys.argv and os.path.splitext(sys.argv[0])[1].lower() == ".py":
		return os.path.abspath(sys.argv[0])
	raise RuntimeError("Updater Disabled in Dev Mode")


def download_file_with_progress(url: str, destination: str, progress_cb=None) -> str:
	assert_https(url)
	os.makedirs(os.path.dirname(destination), exist_ok = True)
	req = Request(url, headers = {"User-Agent": "MenuCreator-Updater/1.0"})
	with urlopen(req, timeout = 60) as resp, open(destination, "wb") as out:
		total = resp.headers.get("Content-Length")
		total = int(total) if total and total.isdigit() else 0
		done = 0

		while True:
			chunk = resp.read(1024 * 256)
			if not chunk:
				break
			out.write(chunk)
			done += len(chunk)
			if progress_cb and total > 0:
				try:
					progress_cb(int(done * 100 / total))
				except Exception:
					pass

	if progress_cb:
		try:
			progress_cb(100)
		except Exception:
			pass
	return destination


def redeem_private_update_code(cfg: dict, code: str) -> dict:
	redeem_url = (cfg.get("update_private_redeem_url") or "").strip()
	assert_https(redeem_url)
	if not redeem_url:
		raise ValueError("Private Redeem URL is Empty")
	if not code.strip():
		raise ValueError("Private Code is Empty")

	payload = json.dumps({
		"app": "MenuCreator",
		"version": VERSION,
		"code": code.strip(),
		"channel": cfg.get("update_channel", "Main"),
	}).encode("utf-8")

	req = Request(
		redeem_url,
		data = payload,
		headers = {
			"User-Agent": "MenuCreator-Updater/1.0",
			"Content-Type": "application/json"
		},
		method = "POST"
	)
	with urlopen(req, timeout = 20) as resp:
		data = json.loads(resp.read().decode("utf-8"))

	if not isinstance(data, dict):
		raise ValueError("Private Redeem Response is not JSON Object")
	return data


def fetch_update_manifest(cfg: dict, channel: str) -> tuple[dict, str]:
	channel = (channel or "Main").strip()
	if channel not in UPDATE_CHANNELS and channel != "private":
		channel = "Main"

	private_code = (cfg.get("update_private_code") or "").strip()
	private_url = (cfg.get("update_private_manifest_url") or "").strip()

	if private_code:
		redeemed = redeem_private_update_code(cfg, private_code)
		manifest_url = (redeemed.get("manifest_url") or private_url).strip()
		if not manifest_url and redeemed.get("manifest"):
			manifest = redeemed["manifest"]
			if not isinstance(manifest, dict):
				raise ValueError("Private Redeem returned non-Object Manifest")
			if "signature" in manifest:
				verify_manifest_signature(manifest)
			return manifest, ""
		if not manifest_url:
			raise ValueError("Private Build Unlocked, but no Manifest_Url Returned")
		assert_https(manifest_url)
		manifest = fetch_json_url(manifest_url)
		if "signature" in manifest:
			verify_manifest_signature(manifest)
		download_url = (manifest.get("download_url") or "").strip()
		if download_url:
			assert_https(download_url)
		return manifest, manifest_url

	manifest_url = build_public_manifest_url(cfg, channel)

	assert_https(manifest_url)
	manifest = fetch_json_url(manifest_url)
	if "signature" in manifest:
		verify_manifest_signature(manifest)
	download_url = (manifest.get("download_url") or "").strip()
	if download_url:
		assert_https(download_url)
	return manifest, manifest_url


def manifest_is_newer(local_build: dict, manifest: dict) -> bool:
	remote_version = parse_version_build(str(manifest.get("version", "")))
	return remote_version > local_build


def install_staged_update(staged_path: str, target_path: str) -> str:
	target_path = os.path.abspath(target_path)
	staged_path = os.path.abspath(staged_path)

	if not os.path.exists(staged_path):
		raise FileNotFoundError(staged_path)

	backup_path = target_path + ".backup"
	if os.path.exists(target_path):
		shutil.copy2(target_path, backup_path)

	helper_path = os.path.join(tempfile.gettempdir(), "menu_creator_update_helper.bat")
	flag_path = os.path.join(os.path.dirname(target_path), "update_failed.flag")

	launcher = ""
	if getattr(sys, "frozen", False):
		launcher = f'start "" "{target_path}"'
	else:
		launcher = f'start "" "{sys.executable}" "{target_path}"'

	bat = f"""@echo off
setlocal
set "PID={os.getpid()}"
set "TARGET={target_path}"
set "SOURCE={staged_path}"
set "FLAG={flag_path}"

:wait_loop
tasklist /FI "PID eq %PID%" | find "%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)

copy /Y "%SOURCE%" "%TARGET%" >nul
if errorlevel 1 (
    echo failed>"%FLAG%"
) else (
    if exist "%FLAG%" del "%FLAG%" >nul 2>nul
)
{launcher}
del "%~f0" >nul 2>nul
"""

	with open(helper_path, "w", encoding = "utf-8", newline = "\r\n") as f:
		f.write(bat)

	subprocess.Popen(["cmd.exe", "/c", helper_path],
					 creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
	return helper_path


def auto_check_updates_on_startup(parent, cfg):
	if not cfg.get("update_auto_check"):
		return

	try:
		manifest, _ = fetch_update_manifest(cfg, cfg.get("update_channel", "Main"))
		if manifest_is_newer(parse_version_build(VERSION), manifest):
			remote_version = manifest.get("version", "unknown")

			QMessageBox.information(
				parent,
				"Update Available",
				f"An Update is Available on Startup: {remote_version}"
			)
	except Exception as e:
		logger.info(f"Startup Update Check skipped/failed: {e}")


# ---------------- SETTINGS DIALOG ----------------


class SettingsDialog(QDialog):
	def __init__(self, cfg, app):
		super().__init__()

		self.cfg = cfg
		self.app = app
		self.old_cfg = cfg.copy()
		self.pending_update = None
		self.pending_manifest_url = ""

		self.setWindowTitle("Settings")

		layout = QVBoxLayout(self)

		# ---------------- APPEARANCE ----------------
		appearance_group = QGroupBox("Appearance")
		appearance_layout = QFormLayout()
		appearance_group.setLayout(appearance_layout)
		layout.addWidget(appearance_group)

		self.style = QComboBox()
		self.style.addItems(QStyleFactory.keys())
		self.style.setCurrentText(cfg["style"])
		appearance_layout.addRow("Style:", self.style)

		self.theme = QComboBox()
		self.theme.addItems(["Default", "Dark", "Light"])
		self.theme.setCurrentText(cfg["theme"])
		appearance_layout.addRow("Theme:", self.theme)

		self.accent = QLineEdit(cfg["accent_color"])
		pick = QPushButton("Pick")
		pick.clicked.connect(self.pick_color)

		row = QHBoxLayout()
		row.addWidget(self.accent)
		row.addWidget(pick)
		appearance_layout.addRow("Accent:", row)

		self.font = QComboBox()
		self.font.addItems(QFontDatabase.families())
		self.font.setCurrentText(cfg["font"])
		appearance_layout.addRow("Font:", self.font)

		self.font_size = QSpinBox()
		self.font_size.setRange(6, 40)
		self.font_size.setValue(cfg["font_size"])
		appearance_layout.addRow("Font Size:", self.font_size)

		# ---------------- BEHAVIOR ----------------
		behavior_group = QGroupBox("Behavior")
		behavior_layout = QFormLayout()
		behavior_group.setLayout(behavior_layout)
		layout.addWidget(behavior_group)

		self.save_interval = QSpinBox()
		self.save_interval.setRange(1, 15)
		self.save_interval.setValue(cfg["save_interval"])
		behavior_layout.addRow("Auto-Save Interval:", self.save_interval)

		self.auto_if = QCheckBox("Enable Auto IF")
		self.auto_if.setChecked(cfg.get("auto_if", False))
		behavior_layout.addRow("Auto IF:", self.auto_if)

		# ---------------- UPDATES ----------------
		update_group = QGroupBox("Updates")
		update_layout = QFormLayout()
		update_group.setLayout(update_layout)
		layout.addWidget(update_group)

		self.update_channel = QComboBox()
		self.update_channel.addItems(["Main", "Beta"])
		self.update_channel.setCurrentText(cfg.get("update_channel", "Main"))
		update_layout.addRow("Channel:", self.update_channel)

		self.update_owner = QLineEdit(cfg.get("update_owner", ""))
		update_layout.addRow("GitHub Owner:", self.update_owner)

		self.update_repo = QLineEdit(cfg.get("update_repo", ""))
		update_layout.addRow("GitHub Repo:", self.update_repo)

		self.update_manifest_path = QLineEdit(cfg.get("update_manifest_path", UPDATE_MANIFEST_PATH_DEFAULT))
		update_layout.addRow("Manifest Path:", self.update_manifest_path)

		self.update_private_redeem_url = QLineEdit(cfg.get("update_private_redeem_url", ""))
		update_layout.addRow("Private Redeem URL:", self.update_private_redeem_url)

		self.update_private_manifest_url = QLineEdit(cfg.get("update_private_manifest_url", ""))
		update_layout.addRow("Private Manifest URL:", self.update_private_manifest_url)

		self.update_private_code = QLineEdit(cfg.get("update_private_code", ""))
		self.update_private_code.setEchoMode(QLineEdit.Password)
		update_layout.addRow("Private Code:", self.update_private_code)

		self.update_auto_check = QCheckBox("Check updates on startup")
		self.update_auto_check.setChecked(cfg.get("update_auto_check", False))
		update_layout.addRow("Auto Check:", self.update_auto_check)

		self.update_status = QLabel("No update check yet.")
		self.update_status.setWordWrap(True)
		update_layout.addRow("Status:", self.update_status)

		update_btn_row = QHBoxLayout()
		self.btn_check_update = QPushButton("Check Now")
		self.btn_install_update = QPushButton("Download / Install")
		self.btn_check_update.clicked.connect(self.on_check_update)
		self.btn_install_update.clicked.connect(self.on_install_update)
		update_btn_row.addWidget(self.btn_check_update)
		update_btn_row.addWidget(self.btn_install_update)
		update_layout.addRow(update_btn_row)

		# ---------------- PLATFORM ----------------
		platform_group = QGroupBox("Windows Theme (Requires Restart)")
		platform_layout = QFormLayout()
		platform_group.setLayout(platform_layout)
		layout.addWidget(platform_group)

		self.platform = QComboBox()
		self.platform.addItems([
			"Default",
			"DarkMode OFF",
			"DarkMode Follow OS",
			"Force DarkMode"
		])

		idx = AVAILABLE_PLATFORM_ARGS.index(cfg["platform_args"]) if cfg[
																		 "platform_args"] in AVAILABLE_PLATFORM_ARGS else 0
		self.platform.setCurrentIndex(idx)
		platform_layout.addRow("Mode:", self.platform)

		# ---------------- BUTTON ----------------
		btn_save = QPushButton("Save")
		btn_save.clicked.connect(self.save)
		layout.addWidget(btn_save)

		self.style.currentTextChanged.connect(self.preview)
		self.theme.currentTextChanged.connect(self.preview)
		self.font.currentTextChanged.connect(self.preview)
		self.font_size.valueChanged.connect(self.preview)
		self.accent.textChanged.connect(self.preview)
		self.save_interval.valueChanged.connect(self.preview)
		self.auto_if.stateChanged.connect(self.preview)

	def _sync_update_cfg(self):
		self.cfg["update_channel"] = self.update_channel.currentText()
		self.cfg["update_owner"] = self.update_owner.text().strip()
		self.cfg["update_repo"] = self.update_repo.text().strip()
		self.cfg["update_manifest_path"] = self.update_manifest_path.text().strip() or UPDATE_MANIFEST_PATH_DEFAULT
		self.cfg["update_private_redeem_url"] = self.update_private_redeem_url.text().strip()
		self.cfg["update_private_manifest_url"] = self.update_private_manifest_url.text().strip()
		self.cfg["update_private_code"] = self.update_private_code.text().strip()
		self.cfg["update_auto_check"] = self.update_auto_check.isChecked()

	def pick_color(self):
		col = QColorDialog.getColor(QColor(self.accent.text()), self)
		if col.isValid():
			self.accent.setText(col.name())

	def preview(self):
		self.cfg["style"] = self.style.currentText()

		if self.cfg["theme"] != self.theme.currentText():
			self.cfg["theme"] = self.theme.currentText()
			if editor:
				editor.rebuild_outliner()

		self.cfg["accent_color"] = self.accent.text()
		self.cfg["font"] = self.font.currentText()
		self.cfg["font_size"] = self.font_size.value()
		self.cfg["save_interval"] = self.save_interval.value()
		self.cfg["auto_if"] = self.auto_if.isChecked()

		self._sync_update_cfg()
		apply_config(self.app, self.cfg)

	def on_check_update(self):
		self._sync_update_cfg()

		try:
			manifest, manifest_url = fetch_update_manifest(self.cfg, self.cfg.get("update_channel", "Main"))
			self.pending_update = manifest
			self.pending_manifest_url = manifest_url
			remote_version = manifest.get("version", "unknown")

			if manifest_is_newer(parse_version_build(VERSION), manifest):
				notes = manifest.get("notes", [])
				if isinstance(notes, list):
					notes_text = " | ".join(str(x) for x in notes[:6])
				else:
					notes_text = str(notes)

				self.update_status.setText(
					f"Update Available: {remote_version}\n{notes_text}"
				)
				QMessageBox.information(
					self,
					"Update Available",
					f"New Version Found: {remote_version}"
				)
			else:
				self.update_status.setText(
					f"Up to Date on {self.cfg.get('update_channel', 'Main')}."
				)
				QMessageBox.information(
					self,
					"No Update",
					"You are already on the Newest Build for this Channel."
				)

		except Exception as e:
			self.pending_update = None
			self.pending_manifest_url = ""
			self.update_status.setText(f"Update Check failed: {e}")
			QMessageBox.warning(self, "Update Check Failed", str(e))

	def on_install_update(self):
		self._sync_update_cfg()

		manifest = self.pending_update
		if not manifest:
			try:
				manifest, self.pending_manifest_url = fetch_update_manifest(self.cfg,
																			self.cfg.get("update_channel", "Main"))
				self.pending_update = manifest
			except Exception as e:
				QMessageBox.warning(self, "Update", f"Could not load manifest:\n{e}")
				return

		if not manifest_is_newer(parse_version_build(VERSION), manifest):
			QMessageBox.information(self, "Update", "No newer build available.")
			return

		download_url = (manifest.get("download_url") or "").strip()
		if not download_url:
			QMessageBox.warning(self, "Update", "Manifest does not contain download_url.")
			return
		assert_https(download_url)

		target_name = os.path.basename(download_url.split("?")[0]) or "MenuCreator_update.bin"
		staged_dir = os.path.join(tempfile.gettempdir(), "MenuCreatorUpdates")
		staged_path = os.path.join(staged_dir, target_name)

		progress = QDialog(self)
		progress.setWindowTitle("Downloading Update")
		progress_layout = QVBoxLayout(progress)
		progress_label = QLabel("Downloading update...")
		progress_bar = QProgressBar()
		progress_bar.setRange(0, 100)
		progress_layout.addWidget(progress_label)
		progress_layout.addWidget(progress_bar)
		progress.setModal(True)
		progress.show()
		QApplication.processEvents()

		def on_progress(p):
			progress_bar.setValue(max(0, min(100, int(p))))
			QApplication.processEvents()

		try:
			download_file_with_progress(download_url, staged_path, on_progress)

			expected_sha = (manifest.get("sha256") or "").strip().lower()
			if expected_sha:
				got_sha = sha256_file(staged_path).lower()
				if got_sha != expected_sha:
					raise ValueError(f"SHA256 mismatch: expected {expected_sha}, got {got_sha}")

			target_path = current_install_target()
			create_update_backup(target_path)
			install_staged_update(staged_path, target_path)
			self.update_status.setText("Update downloaded. It will install after the app closes.")
			QMessageBox.information(
				self,
				"Update Ready",
				"The update has been downloaded. Close the app to let the updater replace the file and restart it."
			)
			self.accept()

		except Exception as e:
			progress.close()
			QMessageBox.warning(self, "Update Failed", str(e))
			self.update_status.setText(f"Download/install failed: {e}")
			return
		finally:
			try:
				progress.close()
			except Exception:
				pass

	def save(self):
		self.cfg["platform_args"] = AVAILABLE_PLATFORM_ARGS[self.platform.currentIndex()]
		self._sync_update_cfg()

		save_config(self.cfg)

		if editor:
			editor.last_session_timer.start(self.cfg["save_interval"] * 60 * 1000)
			editor.auto_if = self.cfg["auto_if"]

		self.accept()

	def reject(self):
		self.cfg.clear()
		self.cfg.update(self.old_cfg)
		apply_config(self.app, self.old_cfg)
		super().reject()


def open_config_editor():
	dlg = SettingsDialog(cfg, app)
	dlg.exec()


if __name__ == "__main__":
	editor = None

	cfg = load_config()
	check_failed_update()
	app = init_app(cfg)

	editor = MenuEditor()
	editor.showMaximized()

	# Load templates & last session
	editor.load_templates()
	editor.load_last_session()

	editor.outliner.rebuild_outliner()

	QTimer.singleShot(1200, lambda: auto_check_updates_on_startup(editor, cfg))

	help_shortcut = QShortcut(QKeySequence(editor.keybinds.get("help")), editor)
	help_shortcut.setContext(Qt.ApplicationShortcut)
	help_shortcut.activated.connect(lambda: FullKeyBindingsInfoDialog(editor.keybinds, editor).exec())

	sys.exit(app.exec())