import re
import requests
import difflib
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import tempfile
from PyPDF2 import PdfReader

app = FastAPI()

def parse_roman(s):
    """
    Parses a Roman numeral string and returns its integer value.
    Returns None if the string is not a valid Roman numeral.
    """
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
    """
    Parses a string that may be an Arabic numeral or a Roman numeral,
    returning the integer value.
    """
    if isinstance(s, int):
        return s
    if isinstance(s, str):
        if s.isdigit():
            return int(s)
        elif re.match(r'^[IVXLCDM]+$', s, re.I):
            return parse_roman(s)
    return None

def extract_toc(pdf_path, max_pages=15):
    """
    Extracts table of contents entries from the first 'max_pages' of a PDF.
    It looks for lines ending with a page number (Arabic or Roman).
    """
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

def extract_first_n_pages_text(pdf_path, n=15):
    reader = PdfReader(pdf_path)
    texts = []
    for i in range(min(n, len(reader.pages))):
        text = reader.pages[i].extract_text() or ""
        texts.append(text)
    return "\n".join(texts)

def get_java_headings(pdf_path):
    url = "https://dependable-expression-production-3af1.up.railway.app/get/pdf-info/detect-chapter-headings"
    with open(pdf_path, "rb") as f:
        files = {"file": f}
        try:
            response = requests.post(url, files=files)
            if response.status_code == 200:
                return response.json().get("headings", [])
        except Exception:
            return []
    return []

def extract_toc_with_gemini(text, gemini_api_key):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=" + gemini_api_key
    prompt = (
        "Given the following text from the first 15 pages of a book PDF, extract the table of contents as a list of chapters. "
        "For each chapter, return a JSON object with 'chapter_title' and 'printed_page_number'. "
        "If the TOC is not present, return an empty list.\nText:\n" + text
    )
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            candidates = result.get("candidates", [])
            if candidates:
                text_response = candidates[0]["content"]["parts"][0]["text"]
                import json
                try:
                    toc_entries = json.loads(text_response)
                    if isinstance(toc_entries, list):
                        return toc_entries
                except Exception:
                    pass
        return []
    except Exception:
        return []

def match_toc_with_java_headings_gemini(toc, java_headings, gemini_api_key, book_title):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=" + gemini_api_key
    # Prompt uses book_title variable instead of a hardcoded book name
    prompt = (
        f"Here is a list of chapters from this book: {book_title}\n\n[TOC LIST]\n" +
        str(toc) +
        "\nNow your job is to look in the dataset below, and find the page number where each chapter starts. Ignore the noise, just for the chapter titles and assign it the correct page number. Be mindful that:\n\n- In some cases there might be minor differences of the wording, that's ok, as long as it's clearly referring to the same chapter.\n\n- In some cases, you may see that the chapter name is divided across 2 entries, that's just a parsing error, but you're still able to identify the chapter by recognizing that the name is split across 2 entries.\n\n- Where there is some ambiguity, make reasonable guesses that will make the overall TOC make sense. For instance if you're struggling to match a particular chapter and there are 2 possibilities for that chapter, but one of them makes it very close to the start of another chapter, meaning that the chapter is very short compared to all others, that's suggestive that's the wrong one. You can use similar heuristics. But ONLY for those that aren't clear from the first place, which should be most of them.\n\n[JAVA HEADINGS LIST]\n" + str(java_headings)
    )
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            candidates = result.get("candidates", [])
            if candidates:
                text_response = candidates[0]["content"]["parts"][0]["text"]
                import json
                try:
                    final_chapters = json.loads(text_response)
                    if isinstance(final_chapters, list):
                        return final_chapters
                except Exception:
                    pass
        return []
    except Exception:
        return []

def find_pdf_page_for_printed_number(pdf_path, printed_page_number):
    reader = PdfReader(pdf_path)
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        for line in text.splitlines():
            if str(printed_page_number) == line.strip():
                return i
    return None

def match_toc_to_java_headings_for_final_json(toc, java_headings, pdf_path, fuzzy_cutoff=0.7):
    matched = []
    java_titles = [h.get("text", "") for h in java_headings]
    offset_list = []
    for idx, entry in enumerate(toc):
        title = entry.get("chapter_title")
        printed_page = entry.get("printed_page_number")
        match = difflib.get_close_matches(title, java_titles, n=1, cutoff=fuzzy_cutoff)
        strategy = "fuzzy match" if match else "TOC fallback"
        pdf_page = find_pdf_page_for_printed_number(pdf_path, printed_page)
        if match and pdf_page is not None:
            offset_list.append(pdf_page - printed_page)
        matched.append({
            "chapter_numerical_number": idx + 1,
            "chapter_full_title": title,
            "page_start": pdf_page if pdf_page is not None else printed_page,
            "matching_strategy": strategy
        })
    offset_warning = None
    if offset_list:
        if all(x == offset_list[0] for x in offset_list):
            for ch in matched:
                if ch["page_start"] is not None:
                    ch["page_start"] = ch["page_start"] - offset_list[0]
        else:
            offset_warning = f"Inconsistent offset detected: {offset_list}"
    return matched, offset_warning

@app.post("/process-pdf")
async def process_pdf(
    file: UploadFile = File(...),
    fuzzy_cutoff: float = 0.7,
    gemini_api_key: str = ""
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        reader = PdfReader(tmp_path)
        book_title = reader.metadata.title if reader.metadata and reader.metadata.title else "Unknown Title"
        authors = [reader.metadata.author] if reader.metadata and reader.metadata.author else ["Unknown Author"]

        # 1. Send PDF to Java backend for headings
        java_headings = get_java_headings(tmp_path)

        # 2. Get the TOC from the PDF (first 15 pages)
        first_15_text = extract_first_n_pages_text(tmp_path, n=15)

        # 2.2 Use Gemini to get TOC if API key is available, else use regex
        toc = extract_toc_with_gemini(first_15_text, gemini_api_key) if gemini_api_key else []
        if not toc:
            toc = extract_toc(tmp_path, max_pages=15)

        # 3. Ask Gemini to match TOC with Java PDF headings using the prompt with book_title
        final_chapters = match_toc_with_java_headings_gemini(toc, java_headings, gemini_api_key, book_title) if gemini_api_key else []
        # 4. Fallback: if Gemini fails, use local matching
        if not final_chapters:
            final_chapters, offset_warning = match_toc_to_java_headings_for_final_json(toc, java_headings, tmp_path, fuzzy_cutoff)
        else:
            offset_warning = None

        # 5. Final output
        final_json = {
            "book_title": book_title,
            "authors": authors,
            "toc": final_chapters
        }
        if offset_warning:
            final_json["offset_warning"] = offset_warning
        return JSONResponse(content=final_json)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})