
# --- BEGIN: Integrated image-based TOC extraction logic ---
import re
import os
import requests
import tempfile
import json
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
# Remove PyPDF2 import, not needed for new workflow

# Import the new TOC extraction logic
import toc_logic

app = FastAPI()

# Read Gemini API key from env var, fallback to empty string if not set
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# This is a fallback parser if Gemini returns markdown instead of JSON
def parse_chapter_list(text_response):
    pattern = r"\*\s*Chapter\s*(\d+):\s*(.*?):\s*(\d+)"
    chapters = []
    for match in re.finditer(pattern, text_response):
        chapters.append({
            "chapter_number": int(match.group(1)),
            "chapter_title": match.group(2).strip(),
            "page_number": int(match.group(3))
        })
    return chapters

async def get_toc_from_new_logic(pdf_path: str):
    """
    Wrapper function to call the new image-based TOC extraction logic.
    """
    print("[DEBUG] Starting new image-based TOC extraction from toc_logic.py")
    if not GEMINI_API_KEY:
        print("[DEBUG] GEMINI_API_KEY not set, skipping new TOC logic.")
        return []
    try:
        # Call the async process_pdf function from the new module
        result_json = await toc_logic.process_pdf(pdf_path)
        if result_json and "toc_entries" in result_json:
            print("[DEBUG] Successfully extracted TOC using new image-based logic.")
            return result_json
        else:
            print("[DEBUG] New TOC extraction logic returned no entries.")
            return None
    except Exception as e:
        print(f"[DEBUG] An error occurred while running the new TOC logic: {e}")
        return None


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

    # --- IMPORTANT CHANGE ---
    # Reformat the TOC to remove page numbers and other extra fields
    # before sending it to the final matching prompt.
    print("[DEBUG] Raw TOC passed to final matching step:", toc)
    formatted_toc_for_prompt = [
        {
            "chapter_title": entry.get("chapter_title"),
            "chapter_number": entry.get("chapter_number")
        }
        for entry in toc
    ]
    print("[DEBUG] Formatted TOC for final prompt (should NOT include page_number):", formatted_toc_for_prompt)

    prompt = (
        f"You are given a list of chapters from the book '{book_title}'. Your job is to match each chapter to its starting page number using the dataset below.\n\n"
        "[TOC LIST]\n"
        + json.dumps(formatted_toc_for_prompt, indent=2)
        + "\n\n[JAVA HEADINGS LIST]\n"
        + str(java_headings)
        + "\n\nReturn ONLY a valid JSON array of objects, with no markdown, no explanations, and no extra text. Each object must have these keys: 'chapter_title' (string), 'page_number' (integer).\n\n"
        "Example output:\n"
        "[\n  {\"chapter_title\": \"Introduction\", \"page_number\": 7},\n  {\"chapter_title\": \"Wisdom, Gods and Goddesses\", \"page_number\": 13}\n]\n\n"
        "Do NOT use triple backticks, markdown, or any text before or after the JSON."
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
                # Strip triple backticks and 'json' if present
                cleaned = text_response.strip()
                if cleaned.startswith('```json'):
                    cleaned = cleaned[len('```json'):].strip()
                if cleaned.startswith('```'):
                    cleaned = cleaned[len('```'):].strip()
                if cleaned.endswith('```'):
                    cleaned = cleaned[:-3].strip()
                try:
                    final_chapters = json.loads(cleaned)
                    if isinstance(final_chapters, list) and final_chapters:
                        return final_chapters
                except Exception:
                    print("[DEBUG] Gemini match response not valid JSON:", cleaned)
                    # Try fallback parsing
                    final_chapters = parse_chapter_list(cleaned)
                    if final_chapters:
                        print("[DEBUG] Parsed chapter list from markdown format.")
                        return final_chapters
                # Fallback: return original TOC if Gemini output is empty or invalid
                print("[DEBUG] Gemini output empty or invalid, returning original TOC.")
                return toc
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
        # Call the new TOC extraction logic
        result = await get_toc_from_new_logic(tmp_path)
        toc = result["toc_entries"] if result and "toc_entries" in result else []
        return JSONResponse(content={"toc": toc})
    except Exception as e:
        return JSONResponse(content={"error": str(e)})
    finally:
        # Clean up the temporary file
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/match-toc-java")
async def match_toc_java_endpoint(
    file: UploadFile = File(...)
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        # Call the new TOC extraction logic
        result = await get_toc_from_new_logic(tmp_path)
        toc = result["toc_entries"] if result and "toc_entries" in result else []
        metadata = result["metadata"] if result and "metadata" in result else {}
        book_title = metadata.get("book_title") or "Unknown Title"
        authors = metadata.get("authors") or ["Unknown Author"]
        java_headings = get_java_headings(tmp_path)
        print("[DEBUG] Java headings for matching:", java_headings)
        final_chapters = match_toc_with_java_headings_gemini(toc, java_headings, book_title) if GEMINI_API_KEY else []
        final_json = {
            "book_title": book_title,
            "authors": authors,
            "toc": final_chapters
        }
        print("[DEBUG] Final API response:", final_json)
        return JSONResponse(content=final_json)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/process-pdf")
async def process_pdf(
    file: UploadFile = File(...)
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        # Call the new TOC extraction logic
        result = await get_toc_from_new_logic(tmp_path)
        toc = result["toc_entries"] if result and "toc_entries" in result else []
        metadata = result["metadata"] if result and "metadata" in result else {}
        book_title = metadata.get("book_title") or "Unknown Title"
        authors = metadata.get("authors") or ["Unknown Author"]
        java_headings = get_java_headings(tmp_path)
        print("[DEBUG] Java headings for matching:", java_headings)
        final_chapters = match_toc_with_java_headings_gemini(toc, java_headings, book_title) if GEMINI_API_KEY else []
        final_json = {
            "book_title": book_title,
            "authors": authors,
            "toc": final_chapters
        }
        print("[DEBUG] Final API response:", final_json)
        return JSONResponse(content=final_json)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)