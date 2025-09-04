# app.py
from __future__ import annotations
import os, sys, json
from pathlib import Path
from typing import List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from signer import sign_pdf, ANCHOR_DEFAULT

APP_NAME = "PDF Signer"
PHRASES_FILE = Path("phrases.json")

DEFAULT_TEMPLATES = [
    "Svěřená správa a systémová podpora 2025",
    "SN 2-25 Oracle Support pro iFIS",
    "SN 5-08 Administrace Oracle",
]

# ---------- Vylepšený Drag & Drop widget ----------
class DropWidget(QtWidgets.QWidget):
    fileDropped = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(240)
        self._drag_active = False
        self._hover_file_is_pdf = False
        self.setCursor(QtCore.Qt.CursorShape.DragCopyCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

    def _is_pdf_urls(self, mime: QtCore.QMimeData) -> bool:
        if not mime.hasUrls():
            return False
        for u in mime.urls():
            if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf"):
                return True
        return False

    # --- Drag & Drop events ---
    def dragEnterEvent(self, e: QtGui.QDragEnterEvent):
        self._hover_file_is_pdf = self._is_pdf_urls(e.mimeData())
        if self._hover_file_is_pdf:
            e.acceptProposedAction()
            self._drag_active = True
            self.update()
        else:
            e.ignore()

    def dragMoveEvent(self, e: QtGui.QDragMoveEvent):
        if self._hover_file_is_pdf:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e: QtGui.QDragLeaveEvent):
        self._drag_active = False
        self._hover_file_is_pdf = False
        self.update()

    def dropEvent(self, e: QtGui.QDropEvent):
        self._drag_active = False
        self.update()
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(".pdf"):
                self.fileDropped.emit(p)
                e.acceptProposedAction()
                return
        e.ignore()

    # --- Malování drop-zóny s ikonou a textem ---
    def paintEvent(self, ev: QtGui.QPaintEvent):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        r = self.rect().adjusted(14, 14, -14, -14)
        radius = 20

        # barvy podle stavu
        if self._drag_active and self._hover_file_is_pdf:
            bg = QtGui.QColor("#e8f5e9")     # zelenkavé pozadí
            border = QtGui.QColor("#2e7d32") # tmavší zelená
            text_color = QtGui.QColor("#1b5e20")
            icon_color = QtGui.QColor("#2e7d32")
            headline = "Pusť pro zpracování"
            subline = "Vložíme text a podpis"
        else:
            bg = QtGui.QColor("#fafafa")
            border = QtGui.QColor("#bdbdbd")
            text_color = QtGui.QColor("#616161")
            icon_color = QtGui.QColor("#9e9e9e")
            headline = "Přetáhni PDF sem"
            subline = "nebo vlož přes schránku"

        # výplň
        p.setBrush(bg)
        pen = QtGui.QPen(border, 2, QtCore.Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(r, radius, radius)

        # ikona – stylizovaná šipka dolů nad „dokumentem“
        # vypočti střed
        cx = r.center().x()
        cy = r.center().y()
        # šipka
        arrow_h = min(r.height(), r.width()) * 0.18
        arrow_w = arrow_h * 0.9
        path = QtGui.QPainterPath()
        path.moveTo(cx, cy - arrow_h * 0.8)
        path.lineTo(cx, cy + arrow_h * 0.1)
        path.moveTo(cx - arrow_w * 0.5, cy - arrow_h * 0.1)
        path.lineTo(cx, cy + arrow_h * 0.5)
        path.lineTo(cx + arrow_w * 0.5, cy - arrow_h * 0.1)

        p.setPen(QtGui.QPen(icon_color, 6, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawPath(path)

        # „list papíru“ – obdélník pod šipkou
        doc_w = arrow_w * 1.4
        doc_h = arrow_h * 0.9
        doc_rect = QtCore.QRectF(cx - doc_w/2, cy + arrow_h * 0.55, doc_w, doc_h)
        p.setPen(QtGui.QPen(icon_color, 3))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(doc_rect, 6, 6)

        # text
        p.setPen(text_color)
        font = p.font()
        font.setPointSizeF(16)
        font.setBold(True)
        p.setFont(font)
        rect_headline = QtCore.QRect(r.left(), int(r.top() + r.height()*0.12), r.width(), int(r.height()*0.25))
        p.drawText(rect_headline, QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignBottom, headline)

        font.setPointSizeF(11)
        font.setBold(False)
        p.setFont(font)
        rect_sub = QtCore.QRect(r.left(), rect_headline.bottom()+4, r.width(), int(r.height()*0.12))
        p.drawText(rect_sub, QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop, subline)

        p.end()

# ---------- Hlavní okno ----------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.settings = QtCore.QSettings("local", APP_NAME)

        # šablony frází
        self.phrases: List[str] = self._load_templates()

        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central); layout.setContentsMargins(16,16,16,16); layout.setSpacing(12)

        layout.addWidget(QtWidgets.QLabel("PDF k podepsání:"))
        self.drop = DropWidget(); self.drop.fileDropped.connect(self.on_file)
        layout.addWidget(self.drop, 1)

        layout.addWidget(QtWidgets.QLabel("Text stanoviska (lze upravit ručně):"))
        self.textEdit = QtWidgets.QPlainTextEdit()
        self.textEdit.setPlaceholderText("Sem napište / vložte stanovisko…")
        self.textEdit.setMinimumHeight(110)
        layout.addWidget(self.textEdit)

        # šablony frází
        tmplRow = QtWidgets.QHBoxLayout()
        tmplRow.addWidget(QtWidgets.QLabel("Šablony:"))
        self.phraseBox = QtWidgets.QComboBox(); self.phraseBox.setEditable(True)
        self.phraseBox.addItems(self.phrases)
        self.phraseBox.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        btnInsert = QtWidgets.QPushButton("Vložit do textu"); btnInsert.clicked.connect(self.insert_template_into_editor)
        btnAdd = QtWidgets.QPushButton("Uložit jako šablonu"); btnAdd.clicked.connect(self.add_current_as_template)
        btnManage = QtWidgets.QPushButton("Správa šablon…"); btnManage.clicked.connect(self.manage_templates_dialog)
        tmplRow.addWidget(self.phraseBox, 1); tmplRow.addWidget(btnInsert); tmplRow.addWidget(btnAdd); tmplRow.addWidget(btnManage)
        layout.addLayout(tmplRow)

        # anchor + podpis
        self.anchorEdit = QtWidgets.QLineEdit(self.settings.value("anchor", ANCHOR_DEFAULT))
        self.anchorEdit.setPlaceholderText("Anchor (text, který hledáme v PDF)")

        self.sigPath = QtWidgets.QLineEdit(self.settings.value("signature", "assets/signature.png"))
        btnSig = QtWidgets.QPushButton("Vybrat podpis (PNG)"); btnSig.clicked.connect(self.pick_signature)

        form = QtWidgets.QFormLayout()
        form.addRow("Anchor:", self.anchorEdit)
        sigRow = QtWidgets.QHBoxLayout(); sigRow.addWidget(self.sigPath); sigRow.addWidget(btnSig)
        form.addRow("Podpis:", sigRow)
        layout.addLayout(form)

        self.status = QtWidgets.QLabel("Přetáhni PDF soubor do oblasti výše…")
        layout.addWidget(self.status)

        self.resize(900, 760)

    # persistence šablon
    def _load_templates(self) -> List[str]:
        if PHRASES_FILE.exists():
            try:
                arr = json.loads(PHRASES_FILE.read_text(encoding="utf-8"))
                if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
                    return arr
            except Exception:
                pass
        return DEFAULT_TEMPLATES.copy()

    def _save_templates(self):
        try:
            PHRASES_FILE.write_text(json.dumps(self.phrases, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, APP_NAME, f"Nelze uložit phrases.json: {e}")

    def _refresh_templates_ui(self):
        self.phraseBox.clear(); self.phraseBox.addItems(self.phrases)

    # akce se šablonami
    def insert_template_into_editor(self):
        text = self.phraseBox.currentText().strip()
        if not text: return
        cursor = self.textEdit.textCursor()
        if cursor.hasSelection(): cursor.removeSelectedText()
        cursor.insertText(text)

    def add_current_as_template(self):
        text = self.phraseBox.currentText().strip()
        if not text: return
        if text not in self.phrases:
            self.phrases.append(text)
            self._save_templates()
            self._refresh_templates_ui()
            QtWidgets.QMessageBox.information(self, APP_NAME, f"Fráze uložena: {text}")

    def manage_templates_dialog(self):
        dlg = TemplateEditorDialog(self, self.phrases)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.phrases = dlg.templates()
            self._save_templates()
            self._refresh_templates_ui()

    # podpis
    def pick_signature(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Vyberte PNG s podpisem", str(Path.cwd()), "PNG Files (*.png)")
        if fn:
            self.sigPath.setText(fn)
            self.settings.setValue("signature", fn)

    # zpracování PDF
    def on_file(self, pdf_path: str):
        # Fallback: editor → pokud prázdný, dropdown
        text = self.textEdit.toPlainText().strip() or self.phraseBox.currentText().strip()
        if not text:
            QtWidgets.QMessageBox.warning(self, APP_NAME, "Nejprve zadejte text stanoviska nebo vyberte šablonu.")
            return

        anchor = self.anchorEdit.text().strip() or ANCHOR_DEFAULT
        sig = self.sigPath.text().strip()
        self.settings.setValue("anchor", anchor)

        in_path = Path(pdf_path); out_path = in_path.with_name(in_path.stem + "-signed" + in_path.suffix)
        self.status.setText(f"Zpracovávám: {in_path.name} …"); QtWidgets.QApplication.processEvents()

        ok = sign_pdf(str(in_path), str(out_path), text,
                      signature_png_path=sig, anchor_text=anchor)
        if ok:
            self.status.setText(f"Hotovo: {out_path}")
            QtWidgets.QMessageBox.information(self, APP_NAME, f"Uloženo: {out_path}")
        else:
            self.status.setText("Anchor nenalezen.")
            QtWidgets.QMessageBox.warning(self, APP_NAME, "Anchor nebyl nalezen. Zkontrolujte text anchoru a kvalitu OCR.")

# ---------- Dialog správy šablon ----------
class TemplateEditorDialog(QtWidgets.QDialog):
    def __init__(self, parent: Optional[QtWidgets.QWidget], templates: List[str]):
        super().__init__(parent)
        self.setWindowTitle("Správa šablon frází")
        self.resize(640, 420)

        v = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget(); self.list.addItems(templates)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        v.addWidget(self.list)

        btns = QtWidgets.QHBoxLayout()
        self.btnAdd = QtWidgets.QPushButton("Přidat")
        self.btnEdit = QtWidgets.QPushButton("Upravit")
        self.btnDel = QtWidgets.QPushButton("Smazat")
        btns.addWidget(self.btnAdd); btns.addWidget(self.btnEdit); btns.addWidget(self.btnDel); btns.addStretch(1)
        v.addLayout(btns)

        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        v.addWidget(box)

        self.btnAdd.clicked.connect(self.add)
        self.btnEdit.clicked.connect(self.edit)
        self.btnDel.clicked.connect(self.delete)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)

    def add(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "Nová fráze", "Text:")
        if ok and text.strip():
            self.list.addItem(text.strip())

    def edit(self):
        item = self.list.currentItem()
        if not item: return
        text, ok = QtWidgets.QInputDialog.getText(self, "Upravit frázi", "Text:", text=item.text())
        if ok and text.strip():
            item.setText(text.strip())

    def delete(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def templates(self) -> List[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

# ---------- CLI mód ----------
def run_cli(args: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(description="PDF Signer – CLI")
    p.add_argument("input")
    p.add_argument("--text", required=True)
    p.add_argument("--signature", default=os.environ.get("SIGNATURE_PNG", "assets/signature.png"))
    p.add_argument("--anchor", default=ANCHOR_DEFAULT)
    p.add_argument("--output")
    ns = p.parse_args(args)

    inp = Path(ns.input)
    out = Path(ns.output) if ns.output else inp.with_name(inp.stem + "-signed" + inp.suffix)
    ok = sign_pdf(str(inp), str(out), ns.text,
                  signature_png_path=ns.signature, anchor_text=ns.anchor)
    print(out if ok else "ANCHOR_NOT_FOUND")
    return 0 if ok else 1

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf"):
        sys.exit(run_cli(sys.argv[1:]))
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
