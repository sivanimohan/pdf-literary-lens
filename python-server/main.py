import requests
import difflib
def get_java_headings(pdf_path):
    # Send PDF to Java backend and get chapter headings
    url = "https://dependable-expression-production-3af1.up.railway.app/get/pdf-info/detect-chapter-headings"
    with open(pdf_path, "rb") as f:
        files = {"file": f}
        try:
            response = requests.post(url, files=files)
            if response.status_code == 200:
                return response.json().get("headings", [])
        except Exception:
            # If error, just return empty list for headings
            return []
def match_toc_to_java_headings(toc, java_headings, pdf_path):
    matched = []
    java_titles = [h.get("text", "") for h in java_headings]
    for idx, entry in enumerate(toc):
        title = entry.get("chapter_title")
        printed_page = entry.get("printed_page_number")
        # Fuzzy match to any Java heading
        match = difflib.get_close_matches(title, java_titles, n=1, cutoff=0.7)
        if match:
            pdf_page = find_pdf_page_for_printed_number(pdf_path, printed_page)
            matched.append({
                "chapter_numerical_number": idx + 1 if entry.get("chapter_numerical_number") is None else entry.get("chapter_numerical_number"),
                "chapter_full_title": title,
                "page_start": pdf_page if pdf_page is not None else printed_page
            })
        else:
            matched.append({
                "chapter_numerical_number": entry.get("chapter_numerical_number"),
                "chapter_full_title": title,
                "page_start": printed_page
            })
    return matched
import re


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
    if isinstance(s, int):
        return s
    if isinstance(s, str):
        if s.isdigit():
            return int(s)
        elif re.match(r'^[IVXLCDM]+$', s, re.I):
            return parse_roman(s)
    return None

def extract_toc(pdf_path, max_pages=15):
    reader = PdfReader(pdf_path)
    toc_entries = []
    multi_line_buffer = []
    toc_pattern = re.compile(r"^(.*?)(\.{2,}|\s{2,})([0-9]+|[IVXLCDM]+)$", re.I)
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

def find_pdf_page_for_printed_number(pdf_path, printed_page_number):
    reader = PdfReader(pdf_path)
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        lines = text.splitlines()
        for line in lines:
            if str(printed_page_number) == line.strip():
                return i  # PDF page index
    return None

def map_toc_to_pdf_pages(pdf_path, toc):
    mapped = []
    for idx, entry in enumerate(toc):
        title = entry.get("chapter_title")
        printed_page = entry.get("printed_page_number")
        pdf_page = find_pdf_page_for_printed_number(pdf_path, printed_page)
        mapped.append({
            "chapter_numerical_number": idx + 1,
            "chapter_full_title": title,
            "page_number": pdf_page if pdf_page is not None else printed_page
        })
    return mapped
def find_pdf_page_for_printed_number(pdf_path, printed_page_number):
    reader = PdfReader(pdf_path)
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        # Look for the printed page number in header/footer (exact match)
        lines = text.splitlines()
        for line in lines:
            if str(printed_page_number) == line.strip():
                return i  # PDF page index
    return None
def map_chapters_to_pdf_pages(pdf_path, chapters):
    mapped = []
    for idx, chapter in enumerate(chapters):
        title = chapter.get("title")
        printed_page = chapter.get("page")
        pdf_page = find_pdf_page_for_printed_number(pdf_path, printed_page)
        mapped.append({
            "chapter_numerical_number": idx + 1,
            "chapter_full_title": title,
            "page_number": pdf_page if pdf_page is not None else printed_page
        })
    return mapped
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
from fastapi.responses import JSONResponse
import json
import tempfile
import os
from PyPDF2 import PdfReader

app = FastAPI()

@app.post("/process-pdf")
async def process_pdf(file: UploadFile = File(...)):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        # 1. Extract TOC from first 15 pages
        toc = extract_toc(tmp_path, max_pages=15)

        # 2. Get chapter headings from Java backend
        java_headings = get_java_headings(tmp_path)

        # 3. Compare TOC entries with Java headings, keep only matched
        toc_entries = match_toc_to_java_headings(toc, java_headings, tmp_path)

        # 4. Compose final output
        book_title = "Unknown Title"  # Optionally extract from metadata
        authors = ["Unknown Author"] # Optionally extract from metadata
        final_json = {
            "book_title": book_title,
            "authors": authors,
            "toc": toc_entries
        }
        return JSONResponse(content=final_json)
    except Exception as e:
        final_json = {"error": str(e)}
        return JSONResponse(content=final_json)
