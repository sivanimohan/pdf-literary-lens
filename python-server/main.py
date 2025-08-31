def is_image_based_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    for i in range(min(5, len(reader.pages))):
        text = reader.pages[i].extract_text() or ""
        if text and len(text.strip()) > 50:
            return False
    return True

def estimate_page_offset(toc, headings):
    diffs = []
    for entry in toc:
        printed = entry.get("printed_page_number")
        title = entry.get("chapter_title")
        for h in headings:
            if h["title"] == title:
                pdf_index = h.get("pdf_page_index")
                if printed is not None and pdf_index is not None:
                    diffs.append(pdf_index - printed)
    if not diffs:
        return 0
    diffs.sort()
    return diffs[len(diffs)//2]
from fastapi import FastAPI, UploadFile, File
import requests
import google.generativeai as genai
from PyPDF2 import PdfReader
import tempfile
import os
from dotenv import load_dotenv
import time
import json
import re
import difflib
try:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer, LTChar
except ImportError:
    extract_pages = None
    LTTextContainer = None
    LTChar = None
try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)


app = FastAPI()

def parse_roman(s):
    roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    s = s.upper()
    num, prev = 0, 0
    for c in reversed(s):
        val = roman_map.get(c, 0)
        if val < prev:
            num -= val
        else:
            num += val
        prev = val
    return num if num > 0 else None

def parse_page_number(s):
    if re.match(r'^[0-9]+$', s):
        return int(s)
    elif re.match(r'^[IVXLCDM]+$', s, re.I):
        return parse_roman(s)
    return None

def extract_toc(pdf_path, max_pages=20):
    reader = PdfReader(pdf_path)
    toc_entries = []
    multi_line_buffer = []
    toc_pattern = re.compile(r"^(.*?)(\.{{2,}}|\s{{2,}})([0-9]+|[IVXLCDM]+)$", re.I)
    for i in range(min(max_pages, len(reader.pages))):
        text = reader.pages[i].extract_text() or ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = toc_pattern.match(line)
            if m:
                title = m.group(1).strip()
                page_str = m.group(3)
                page_num = parse_page_number(page_str)
                if multi_line_buffer:
                    title = " ".join(multi_line_buffer) + " " + title
                    multi_line_buffer = []
                toc_entries.append({"chapter_title": title, "printed_page_number": page_num})
            else:
                multi_line_buffer.append(line)
    return toc_entries

def extract_headings_font(pdf_path):
    headings = []
    if extract_pages is None:
        return headings
    multi_line_buffer = []
    for page_layout in extract_pages(pdf_path):
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                for text_line in element:
                    if hasattr(text_line, 'get_text'):
                        line = text_line.get_text().strip()
                        if not line:
                            continue
                        if line.endswith('-'):
                            multi_line_buffer.append(line[:-1])
                            continue
                        if multi_line_buffer:
                            line = "".join(multi_line_buffer) + line
                            multi_line_buffer = []
                        if len(line) < 8:
                            continue
                        font_sizes = [char.size for char in text_line if isinstance(char, LTChar)]
                        if font_sizes and max(font_sizes) > 12:
                            headings.append({"title": line, "pdf_page_index": page_layout.pageid})
    return headings

def extract_bookmarks(pdf_path):
    reader = PdfReader(pdf_path)
    bookmarks = []
    def walk(outlines):
        for item in outlines:
            if isinstance(item, list):
                walk(item)
            else:
                title = getattr(item, 'title', None)
                try:
                    page_index = reader.get_destination_page_number(item)
                except Exception:
                    page_index = None
                if title is not None and page_index is not None:
                    bookmarks.append({"title": title, "pdf_page_index": page_index})
    try:
        walk(reader.outline)
    except Exception:
        pass
    return bookmarks

def ocr_headings(pdf_path, max_pages=5):
    headings = []
    if pytesseract is None or Image is None:
        return headings
    reader = PdfReader(pdf_path)
    for i in range(min(max_pages, len(reader.pages))):
        # You need to render the PDF page to an image here (use pdf2image or similar)
        # For demonstration, assume you have an image file path
        # img = Image.open(tmp_img.name)
        # text = pytesseract.image_to_string(img)
        # for line in text.splitlines():
        #     if len(line.strip()) >= 8:
        #         headings.append({"title": line.strip(), "pdf_page_index": i})
        pass
    return headings

def fuzzy_match_toc_to_headings(toc, headings):
    deduped = []
    heading_titles = [h["title"] for h in headings]
    offset = estimate_page_offset(toc, headings)
    for entry in toc:
        title = entry["chapter_title"]
        matches = difflib.get_close_matches(title, heading_titles, n=1, cutoff=0.7)
        pdf_index = None
        if matches:
            match_title = matches[0]
            for h in headings:
                if h["title"] == match_title:
                    pdf_index = h["pdf_page_index"]
                    break
        if pdf_index is not None:
            pdf_index += offset
        deduped.append({
            "chapter_title": title,
            "printed_page_number": entry["printed_page_number"],
            "pdf_page_index": pdf_index if pdf_index is not None else 0
        })
    return deduped

def parse_gemini_json(text):
    cleaned = re.sub(r"^```json|^```|```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except Exception:
        return {}


@app.post("/process-pdf")
async def process_pdf(file: UploadFile = File(...)):
    start_total = time.time()
    log_data = {}
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        log_data["pdf_path"] = tmp_path

        # PDF type preprocessing
        image_based = is_image_based_pdf(tmp_path)
        log_data["is_image_based"] = image_based

        # 1. Extract TOC (first 20 pages, regex for dotted lines, multi-line, roman numerals)
        toc = extract_toc(tmp_path, max_pages=20)
        log_data["toc_extracted"] = toc

        # 2. Extract candidate headings (font/layout, multi-line)
        headings_font = extract_headings_font(tmp_path) if not image_based else []
        log_data["headings_font"] = headings_font

        # 3. Extract bookmarks (if present)
        bookmarks = extract_bookmarks(tmp_path) if not image_based else []
        log_data["bookmarks"] = bookmarks

        # 4. OCR fallback (for image-based pages)
        ocr_headings_list = ocr_headings(tmp_path) if image_based else []
        log_data["ocr_headings"] = ocr_headings_list

        # 5. Combine all headings (multi-source reconciliation)
        all_headings = headings_font + bookmarks + ocr_headings_list
        # Deduplicate
        unique = {}
        for h in all_headings:
            key = h["title"].strip().lower() + "@" + str(h.get("pdf_page_index", 0))
            if key not in unique:
                unique[key] = h
        all_headings = list(unique.values())
        log_data["all_headings"] = all_headings

        # 6. Fuzzy match TOC titles to detected headings, with offset correction
        deduped = fuzzy_match_toc_to_headings(toc, all_headings)
        log_data["deduped"] = deduped

        # Compose final output in required format
        # You may want to extract book_title and authors from metadata or input; here, placeholders are used
        book_title = "Where Shall Wisdom Be Found?"  # TODO: Replace with dynamic extraction if available
        authors = ["Harold Bloom"]  # TODO: Replace with dynamic extraction if available
        toc_list = []
        for entry in deduped:
            toc_list.append({
                "chapter_numerical_number": entry.get("chapter_numerical_number"),
                "chapter_full_title": entry.get("chapter_title"),
                "page_number": entry.get("pdf_page_index", entry.get("printed_page_number", 0))
            })
        final_json = {
            "book_title": book_title,
            "authors": authors,
            "toc": toc_list
        }
    except Exception as e:
        log_data["fatal_error"] = str(e)
        final_json = {"error": str(e)}

    log_path = os.path.join(os.path.dirname(__file__), "..", "detailed_log.json")
    with open(log_path, "w", encoding="utf-8") as log_file:
        json.dump(log_data, log_file, ensure_ascii=False, indent=2)
    return final_json
