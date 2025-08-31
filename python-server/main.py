import re
import requests
import tempfile
import json
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from PyPDF2 import PdfReader

app = FastAPI()

def extract_first_n_pages_text(pdf_path, n=15):
    reader = PdfReader(pdf_path)
    texts = []
    for i in range(min(n, len(reader.pages))):
        text = reader.pages[i].extract_text() or ""
        texts.append(text)
    return "\n".join(texts)

def extract_toc_with_gemini(text, gemini_api_key):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + gemini_api_key
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
                try:
                    toc_entries = json.loads(text_response)
                    if isinstance(toc_entries, list):
                        return toc_entries
                except Exception:
                    pass
        return []
    except Exception:
        return []

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
        except Exception as e:
            return {"error": str(e)}
    return []

def match_toc_with_java_headings_gemini(toc, java_headings, gemini_api_key, book_title):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + gemini_api_key
    prompt = (
        f"Here is a list of chapters from this book: {book_title}\n\n[TOC LIST]\n"
        + str(toc)
        + "\nNow your job is to look in the dataset below, and find the page number where each chapter starts. Ignore the noise, just for the chapter titles and assign it the correct page number. Be mindful that:\n\n"
        "- In some cases there might be minor differences of the wording, that's ok, as long as it's clearly referring to the same chapter.\n\n"
        "- In some cases, you may see that the chapter name is divided across 2 entries, that's just a parsing error, but you're still able to identify the chapter by recognizing that the name is split across 2 entries.\n\n"
        "- Where there is some ambiguity, make reasonable guesses that will make the overall TOC make sense. For instance if you're struggling to match a particular chapter and there are 2 possibilities for that chapter, but one of them makes it very close to the start of another chapter, meaning that the chapter is very short compared to all others, that's suggestive that's the wrong one. You can use similar heuristics. But ONLY for those that aren't clear from the first place, which should be most of them.\n\n"
        "[JAVA HEADINGS LIST]\n"
        + str(java_headings)
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
                try:
                    final_chapters = json.loads(text_response)
                    if isinstance(final_chapters, list):
                        return final_chapters
                except Exception:
                    pass
        return []
    except Exception:
        return []

@app.post("/extract-toc")
async def extract_toc_endpoint(file: UploadFile = File(...), gemini_api_key: str = ""):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        first_15_text = extract_first_n_pages_text(tmp_path, n=15)
        toc = extract_toc_with_gemini(first_15_text, gemini_api_key) if gemini_api_key else []
        return JSONResponse(content={"toc": toc})
    except Exception as e:
        return JSONResponse(content={"error": str(e)})

@app.post("/match-toc-java")
async def match_toc_java_endpoint(
    file: UploadFile = File(...),
    gemini_api_key: str = "",
    book_title: str = "Unknown Title",
    author: str = "Unknown Author"
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        first_15_text = extract_first_n_pages_text(tmp_path, n=15)
        toc = extract_toc_with_gemini(first_15_text, gemini_api_key) if gemini_api_key else []
        java_headings = get_java_headings(tmp_path)
        final_chapters = match_toc_with_java_headings_gemini(toc, java_headings, gemini_api_key, book_title) if gemini_api_key else []
        final_json = {
            "book_title": book_title,
            "authors": [author],
            "toc": final_chapters
        }
        return JSONResponse(content=final_json)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})

@app.post("/process-pdf")
async def process_pdf(
    file: UploadFile = File(...),
    gemini_api_key: str = "",
    book_title: str = "Unknown Title",
    author: str = "Unknown Author"
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        first_15_text = extract_first_n_pages_text(tmp_path, n=15)
        toc = extract_toc_with_gemini(first_15_text, gemini_api_key) if gemini_api_key else []
        java_headings = get_java_headings(tmp_path)
        final_chapters = match_toc_with_java_headings_gemini(toc, java_headings, gemini_api_key, book_title) if gemini_api_key else []
        final_json = {
            "book_title": book_title,
            "authors": [author],
            "toc": final_chapters
        }
        return JSONResponse(content=final_json)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})