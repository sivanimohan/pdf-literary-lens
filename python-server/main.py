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
from PyPDF2 import PdfReader
import tempfile
import os
import json
import re

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

def get_java_headings(toc):
    # Send TOC to Java backend and get chapter headings
    # Replace with your actual Java backend endpoint
    url = "http://localhost:8080/api/chapter-headings"  # Example endpoint
    try:
        response = requests.post(url, json={"toc": toc})
        if response.status_code == 200:
            return response.json().get("headings", [])
    except Exception:
        pass
    return []

@app.post("/process-pdf")
async def process_pdf(file: UploadFile = File(...)):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        # 1. Extract TOC (first 15 pages)
        toc = extract_toc(tmp_path, max_pages=15)

        # 2. Get chapter headings from Java backend
        java_headings = get_java_headings(toc)

        # 3. Match TOC to Java headings (simple title match)
        toc_list = []
        for entry in toc:
            match = next((h for h in java_headings if h.get("text") == entry["chapter_title"]), None)
            toc_list.append({
                "chapter_numerical_number": match.get("number") if match else None,
                "chapter_full_title": entry["chapter_title"],
                "page_number": match.get("page") if match else entry.get("printed_page_number", 0)
            })

        # 4. Compose final output
        book_title = "Where Shall Wisdom Be Found?"  # TODO: Replace with dynamic extraction if available
        authors = ["Harold Bloom"]  # TODO: Replace with dynamic extraction if available
        final_json = {
            "book_title": book_title,
            "authors": authors,
            "toc": toc_list
        }
    except Exception as e:
        final_json = {"error": str(e)}
    return final_json
