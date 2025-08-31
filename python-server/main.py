import re
import os
import requests
import tempfile
import json
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from PyPDF2 import PdfReader

app = FastAPI()

# Read Gemini API key from env var, fallback to empty string if not set
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

def extract_first_n_pages_text(pdf_path, n=15):
    reader = PdfReader(pdf_path)
    texts = []
    for i in range(min(n, len(reader.pages))):
        text = reader.pages[i].extract_text() or ""
        texts.append(text)
    extracted = "\n".join(texts)
    print("[DEBUG] Extracted text from first 15 pages:")
    print(extracted[:2000])  # Print first 2000 chars for brevity
    return extracted

def parse_chapter_list(text_response):
    # Regex matches: *   Chapter N: Title: Page
    pattern = r"\*\s*Chapter\s*(\d+):\s*(.*?):\s*(\d+)"
    chapters = []
    for match in re.finditer(pattern, text_response):
        chapters.append({
            "chapter_number": int(match.group(1)),
            "chapter_title": match.group(2).strip(),
            "printed_page_number": int(match.group(3))
        })
    return chapters

def extract_metadata_and_toc_with_gemini(text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + GEMINI_API_KEY
    prompt = (
        "Given the following text from the first 15 pages of a book PDF, extract the following information as a single JSON object:\n"
        "{\n"
        "  \"book_title\": \"...\",\n"
        "  \"authors\": [\"...\"],\n"
        "  \"toc\": [\n"
        "    {\"chapter_title\": \"...\", \"printed_page_number\": ...},\n"
        "    ...\n"
        "  ]\n"
        "}\n"
        "If any information is missing, use \"Unknown Title\" for the book title and [\"Unknown Author\"] for the authors. The table of contents (toc) should be a list as described. Do NOT use Markdown, plain text, or bullet lists.\n"
        "If the TOC is not present, return an empty list for toc.\n"
        "Text:\n" + text
    )
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, headers=headers, json=data)
        print("[DEBUG] Gemini Metadata+TOC API status:", response.status_code)
        if response.status_code == 200:
            result = response.json()
            print("[DEBUG] Gemini Metadata+TOC raw response:", result)
            candidates = result.get("candidates", [])
            if candidates:
                text_response = candidates[0]["content"]["parts"][0]["text"]
                try:
                    metadata_toc = json.loads(text_response)
                    # Sanitize missing values
                    if "book_title" not in metadata_toc or not metadata_toc["book_title"]:
                        metadata_toc["book_title"] = "Unknown Title"
                    if "authors" not in metadata_toc or not metadata_toc["authors"]:
                        metadata_toc["authors"] = ["Unknown Author"]
                    if "toc" not in metadata_toc or not isinstance(metadata_toc["toc"], list):
                        metadata_toc["toc"] = []
                    return metadata_toc
                except Exception:
                    print("[DEBUG] Gemini Metadata+TOC response not valid JSON:", text_response)
                    # Try fallback parsing
                    return {
                        "book_title": "Unknown Title",
                        "authors": ["Unknown Author"],
                        "toc": []
                    }
        return {
            "book_title": "Unknown Title",
            "authors": ["Unknown Author"],
            "toc": []
        }
    except Exception as e:
        print("[DEBUG] Gemini Metadata+TOC API exception:", e)
        return {
            "book_title": "Unknown Title",
            "authors": ["Unknown Author"],
            "toc": []
        }

def get_java_headings(pdf_path):
    url = "https://dependable-expression-production-3af1.up.railway.app/get/pdf-info/detect-chapter-headings"
    with open(pdf_path, "rb") as f:
        files = {"file": f}
        try:
            response = requests.post(url, files=files, timeout=180)
            print("[DEBUG] Java headings API status:", response.status_code)
            if response.status_code == 200:
                headings_data = response.json()
                print("[DEBUG] Java headings raw response:", headings_data)
                if isinstance(headings_data, dict) and "headings" in headings_data:
                    return headings_data["headings"]
                return headings_data
        except Exception as e:
            print("[DEBUG] Java headings API exception:", e)
            return {"error": str(e)}
    return []

def match_toc_with_java_headings_gemini(toc, java_headings, book_title):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + GEMINI_API_KEY
    prompt = (
        f"Here is a list of chapters from this book: {book_title}\n\n[TOC LIST]\n"
        + str(toc)
        + "\nNow your job is to look in the dataset below, and find the page number where each chapter starts. Ignore the noise, just for the chapter titles and assign it the correct page number. Be mindful that:\n\n"
        "- In some cases there might be minor differences of the wording, that's ok, as long as it's clearly referring to the same chapter.\n\n"
        "- In some cases, you may see that the chapter name is divided across 2 entries, that's just a parsing error, but you're still able to identify the chapter by recognizing that the name is split across 2 entries.\n\n"
        "- Where there is some ambiguity, make reasonable guesses that will make the overall TOC make sense. For instance if you're struggling to match a particular chapter and there are 2 possibilities for that chapter, but one of them makes it very close to the start of another chapter, meaning that the chapter is very short compared to all others, that's suggestive that's the wrong one. You can use similar heuristics. But ONLY for those that aren't clear from the first place, which should be most of them.\n\n"
        "Return the result as a JSON list like this: [{\"chapter_title\": \"...\", \"printed_page_number\": ...}, ...]. Do NOT use Markdown or plain text or bullet lists.\n\n"
        "[JAVA HEADINGS LIST]\n"
        + str(java_headings)
    )
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, headers=headers, json=data)
        print("[DEBUG] Gemini match API status:", response.status_code)
        if response.status_code == 200:
            result = response.json()
            print("[DEBUG] Gemini match raw response:", result)
            candidates = result.get("candidates", [])
            if candidates:
                text_response = candidates[0]["content"]["parts"][0]["text"]
                try:
                    final_chapters = json.loads(text_response)
                    if isinstance(final_chapters, list):
                        return final_chapters
                except Exception:
                    print("[DEBUG] Gemini match response not valid JSON:", text_response)
                    # Try fallback parsing
                    final_chapters = parse_chapter_list(text_response)
                    if final_chapters:
                        print("[DEBUG] Parsed chapter list from markdown format.")
                        return final_chapters
        return []
    except Exception as e:
        print("[DEBUG] Gemini match API exception:", e)
        return []

@app.post("/extract-toc")
async def extract_toc_endpoint(file: UploadFile = File(...)):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        first_15_text = extract_first_n_pages_text(tmp_path, n=15)
        metadata_toc = extract_metadata_and_toc_with_gemini(first_15_text) if GEMINI_API_KEY else {
            "book_title": "Unknown Title",
            "authors": ["Unknown Author"],
            "toc": []
        }
        return JSONResponse(content=metadata_toc)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})

@app.post("/match-toc-java")
async def match_toc_java_endpoint(
    file: UploadFile = File(...),
    book_title: str = "Unknown Title",
    author: str = "Unknown Author"
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        first_15_text = extract_first_n_pages_text(tmp_path, n=15)
        metadata_toc = extract_metadata_and_toc_with_gemini(first_15_text) if GEMINI_API_KEY else {
            "book_title": book_title,
            "authors": [author],
            "toc": []
        }
        java_headings = get_java_headings(tmp_path)
        final_chapters = match_toc_with_java_headings_gemini(metadata_toc["toc"], java_headings, metadata_toc["book_title"]) if GEMINI_API_KEY else []
        final_json = {
            "book_title": metadata_toc["book_title"],
            "authors": metadata_toc["authors"],
            "toc": final_chapters
        }
        return JSONResponse(content=final_json)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})

@app.post("/process-pdf")
async def process_pdf(
    file: UploadFile = File(...),
    book_title: str = "Unknown Title",
    author: str = "Unknown Author"
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        first_15_text = extract_first_n_pages_text(tmp_path, n=15)
        metadata_toc = extract_metadata_and_toc_with_gemini(first_15_text) if GEMINI_API_KEY else {
            "book_title": book_title,
            "authors": [author],
            "toc": []
        }
        java_headings = get_java_headings(tmp_path)
        final_chapters = match_toc_with_java_headings_gemini(metadata_toc["toc"], java_headings, metadata_toc["book_title"]) if GEMINI_API_KEY else []
        final_json = {
            "book_title": metadata_toc["book_title"],
            "authors": metadata_toc["authors"],
            "toc": final_chapters
        }
        return JSONResponse(content=final_json)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})