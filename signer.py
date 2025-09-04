# signer.py
from __future__ import annotations
import io, os, re
from dataclasses import dataclass
from typing import Optional, Tuple, List

from pdf2image import convert_from_path
from PIL import Image
import pytesseract
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from dotenv import load_dotenv

# Načti .env (pokud je k dispozici)
load_dotenv()

# --------- Pomocné funkce / nastavení ---------
def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return float(val.strip())
    except Exception:
        return default

# Konfigurace přes ENV / .env
SIGNATURE_GAP_PT = _env_float("SIGNATURE_GAP_PT", 40.0)                 # horizontální mezera za textem
SIGNATURE_BASELINE_OFFSET_PT = _env_float("SIGNATURE_BASELINE_OFFSET_PT", 0.0)  # vertikální offset podpisu (kladně = nahoru)

# Cesty a fonty
TESSERACT_CMD = os.environ.get("TESSERACT_CMD") or ("/opt/homebrew/bin/tesseract" if os.path.exists("/opt/homebrew/bin/tesseract") else "tesseract")
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

DEFAULT_FONT_NAME = "DejaVuSans"
FONT_PATH = os.environ.get("SIGNER_FONT_PATH", os.path.join("assets", "DejaVuSans.ttf"))
FALLBACK_FONT_NAME = "Helvetica"
DEFAULT_LANG = os.environ.get("OCR_LANG", "ces+eng")

# Registrace TTF (pokud existuje)
if os.path.exists(FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont(DEFAULT_FONT_NAME, FONT_PATH))
    except Exception:
        pass

ANCHOR_DEFAULT = "Stanovisko odborného útvaru"

@dataclass
class AnchorHit:
    page_index: int
    bbox_px: Tuple[int, int, int, int]  # x, y, w, h v px (počátek vlevo nahoře)
    image_size: Tuple[int, int]          # (w, h) px
    dpi: int

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()

# --------- OCR: najdi anchor na stránkách ---------
def find_anchor_bbox(pdf_path: str, anchor: str = ANCHOR_DEFAULT, dpi: int = 300, lang: str = DEFAULT_LANG) -> Optional[AnchorHit]:
    pages = convert_from_path(pdf_path, dpi=dpi)
    norm_anchor = _normalize(anchor)

    for page_idx, pil_img in enumerate(pages):
        ocr = pytesseract.image_to_data(pil_img, lang=lang, output_type=pytesseract.Output.DICT)
        n = len(ocr["text"])

        # seskup do řádků
        rows = {}
        for i in range(n):
            if int(ocr.get("conf")[i]) < 0:
                continue
            key = (ocr["block_num"][i], ocr["par_num"][i], ocr["line_num"][i])
            rows.setdefault(key, []).append(i)

        for idxs in rows.values():
            words = [ocr["text"][i] for i in idxs if ocr["text"][i].strip()]
            if not words:
                continue
            line_text = _normalize(" ".join(words))

            x = min(ocr["left"][i] for i in idxs)
            y = min(ocr["top"][i] for i in idxs)
            x2 = max(ocr["left"][i] + ocr["width"][i] for i in idxs)
            y2 = max(ocr["top"][i] + ocr["height"][i] for i in idxs)

            if norm_anchor in line_text:
                return AnchorHit(page_index=page_idx,
                                 bbox_px=(x, y, x2 - x, y2 - y),
                                 image_size=pil_img.size,
                                 dpi=dpi)
    return None

def _px_to_pt(x_px: float, y_px: float, page_w_pt: float, page_h_pt: float, img_w_px: int, img_h_px: int) -> Tuple[float, float]:
    sx = page_w_pt / float(img_w_px)
    sy = page_h_pt / float(img_h_px)
    x_pt = x_px * sx
    y_pt = page_h_pt - (y_px * sy)  # převrácení osy Y
    return x_pt, y_pt

# --------- Kreslení overlaye ---------
def draw_overlay(page_size_pt: Tuple[float, float],
                 anchor_bbox_px: Tuple[int, int, int, int],
                 image_size_px: Tuple[int, int], *,
                 text: str,
                 signature_png_path: Optional[str],
                 text_width_pt: Optional[float] = None,
                 line_spacing_pt: float = 14.0,
                 font_size_pt: float = 12.0,
                 below_offset_pt: float = 22.0,
                 signature_height_pt: float = 36.0) -> bytes:
    """
    Vytvoří jednopage overlay:
      - vloží text POD anchor s word-wrapem,
      - podpis umístí HNED ZA POSLEDNÍ ZNAK posledního řádku,
        vodorovně s mezerou SIGNATURE_GAP_PT, vertikálně k baseline posledního řádku
        s jemným doladěním SIGNATURE_BASELINE_OFFSET_PT (kladně = nahoru).
    """
    page_w, page_h = page_size_pt
    img_w, img_h = image_size_px
    x_px, y_px, _w_px, h_px = anchor_bbox_px

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    font_name = DEFAULT_FONT_NAME if DEFAULT_FONT_NAME in pdfmetrics.getRegisteredFontNames() else FALLBACK_FONT_NAME
    c.setFont(font_name, font_size_pt)

    if text_width_pt is None:
        text_width_pt = page_w * 0.45

    # výchozí bod psaní: pod spodní hranou anchor řádky
    x_anchor_pt, y_anchor_bottom_pt = _px_to_pt(x_px, y_px + h_px, page_w, page_h, img_w, img_h)
    first_baseline = y_anchor_bottom_pt - below_offset_pt
    y_cursor = first_baseline

    # wrap textu
    words = text.split()
    lines: List[str] = []
    cur: List[str] = []
    for w in words:
        cand = (" ".join(cur + [w])).strip()
        if stringWidth(cand, font_name, font_size_pt) <= text_width_pt:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    # vykreslení řádků
    x_text = x_anchor_pt
    for line in lines:
        c.drawString(x_text, y_cursor, line)
        y_cursor -= line_spacing_pt

    # metriky posledního řádku
    last_line = lines[-1] if lines else ""
    last_line_width = stringWidth(last_line, font_name, font_size_pt)
    last_baseline = first_baseline - (len(lines) - 1) * line_spacing_pt

    # podpis: za posledním znakem, s definovanými offsety
    if signature_png_path and os.path.exists(signature_png_path):
        try:
            with Image.open(signature_png_path) as im:
                w_img, h_img = im.size
                aspect = (w_img / h_img) if h_img else 1.0
        except Exception:
            aspect = 3.0  # fallback odhad
        sig_h = signature_height_pt
        sig_w = sig_h * aspect
        x_sig = x_text + last_line_width + SIGNATURE_GAP_PT
        y_sig = last_baseline - (sig_h - font_size_pt) + SIGNATURE_BASELINE_OFFSET_PT
        c.drawImage(signature_png_path, x_sig, y_sig, width=sig_w, height=sig_h, mask='auto')

    c.save()
    return buf.getvalue()

# --------- Veřejná funkce ---------
def sign_pdf(input_pdf: str, output_pdf: str, text: str, *,
             signature_png_path: Optional[str] = None,
             anchor_text: str = ANCHOR_DEFAULT,
             dpi: int = 300) -> bool:
    hit = find_anchor_bbox(input_pdf, anchor=anchor_text, dpi=dpi)
    if not hit:
        return False

    reader = PdfReader(input_pdf)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if i == hit.page_index:
            page_w = float(page.mediabox.width)
            page_h = float(page.mediabox.height)
            overlay_bytes = draw_overlay(
                (page_w, page_h), hit.bbox_px, hit.image_size,
                text=text, signature_png_path=signature_png_path
            )
            overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
            overlay_page = overlay_reader.pages[0]
            page.merge_page(overlay_page)
        writer.add_page(page)

    with open(output_pdf, 'wb') as f:
        writer.write(f)
    return True

# --------- CLI ---------
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Sign PDF and place signature right after the inserted text.")
    p.add_argument("input", help="input PDF")
    p.add_argument("output", help="output PDF")
    p.add_argument("--text", required=True, help="text to insert under anchor")
    p.add_argument("--signature", default=os.environ.get("SIGNATURE_PNG", "assets/signature.png"), help="path to signature PNG")
    p.add_argument("--anchor", default=ANCHOR_DEFAULT, help="anchor text to find")
    p.add_argument("--dpi", type=int, default=300)
    args = p.parse_args()

    ok = sign_pdf(args.input, args.output, args.text,
                  signature_png_path=args.signature, anchor_text=args.anchor, dpi=args.dpi)
    print("OK" if ok else "ANCHOR_NOT_FOUND")
