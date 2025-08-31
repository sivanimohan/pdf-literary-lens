import re
import requests
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from PyPDF2 import PdfReader

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
            response = requests.post(url, files=files, timeout=180)
            if response.status_code == 200:
                headings_data = response.json()
                if isinstance(headings_data, dict) and "headings" in headings_data:
                    return headings_data["headings"]
                return headings_data
        except Exception:
            return []
    return []

def match_toc_with_java_headings_gemini(toc, java_headings, gemini_api_key, book_title):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=" + gemini_api_key
    # Replace book name dynamically in the prompt
    prompt = (
        f"Here is a list of chapters from this book: {book_title}\n\n"
        "[TOC LIST]\n" +
        str(toc) +
        "\nNow your job is to look in the dataset below, and find the page number where each chapter starts. Ignore the noise, just for the chapter titles and assign it the correct page number. Be mindful that:\n\n"
        "- In some cases there might be minor differences of the wording, that's ok, as long as it's clearly referring to the same chapter.\n\n"
        "- In some cases, you may see that the chapter name is divided across 2 entries, that's just a parsing error, but you're still able to identify the chapter by recognizing that the name is split across 2 entries.\n\n"
        "- Where there is some ambiguity, make reasonable guesses that will make the overall TOC make sense. For instance if you're struggling to match a particular chapter and there are 2 possibilities for that chapter, but one of them makes it very close to the start of another chapter, meaning that the chapter is very short compared to all others, that's suggestive that's the wrong one. You can use similar heuristics. But ONLY for those that aren't clear from the first place, which should be most of them.\n\n"
        "[JAVA HEADINGS LIST]\n" + str(java_headings)
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
                    return final_chapters
                except Exception:
                    pass
        return []
    except Exception:
        return []

@app.post("/process-pdf")
async def process_pdf(
    file: UploadFile = File(...),
    gemini_api_key: str = "",
    max_toc_pages: int = 15
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        # 1. Send PDF to Java backend, get headings
        java_headings = get_java_headings(tmp_path)

        # 2. Get the TOC from the PDF
        toc_entries = extract_toc(tmp_path, max_pages=max_toc_pages)

        # 2.1 Get the first 15 pages of the PDF
        first_15_text = extract_first_n_pages_text(tmp_path, n=max_toc_pages)

        # 2.2 Get book title from metadata if available
        reader = PdfReader(tmp_path)
        book_title = reader.metadata.title if reader.metadata and reader.metadata.title else "Unknown Title"

        # 2.3 If Gemini key provided, ask Gemini to give chapters based on TOC
        toc_list = toc_entries
        if gemini_api_key:
            gemini_toc = match_toc_with_java_headings_gemini(toc_list, java_headings, gemini_api_key, book_title)
            # If Gemini returned valid chapters, use those as output
            if gemini_toc and isinstance(gemini_toc, list):
                return JSONResponse(content=gemini_toc)

        # Fallback: Output TOC in the requested format if Gemini is not used
        output = []
        for toc in toc_entries:
            if toc.get("chapter_title") and toc.get("printed_page_number"):
                output.append({
                    "title": toc["chapter_title"],
                    "pageNumber": toc["printed_page_number"],
                    "level": 1
                })
        # If no TOC, fallback to Java headings
        if not output and java_headings:
            for h in java_headings:
                title = h.get("title") or h.get("text")
                page_num = h.get("pageNumber")
                if title and page_num:
                    output.append({
                        "title": title,
                        "pageNumber": page_num,
                        "level": 1
                    })
        return JSONResponse(content=output)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})