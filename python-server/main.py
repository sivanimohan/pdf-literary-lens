
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
            "printed_page_number": int(match.group(3))
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
        f"Here is a list of chapters from this book: {book_title}\n\n[TOC LIST]\n"
        + json.dumps(formatted_toc_for_prompt, indent=2)
        + "\nNow your job is to look in the dataset below, and find the page number where each chapter starts. "
        "Ignore the noise, just for the chapter titles and assign it the correct page number. "
        "Be mindful that:\n\n"
        "- In some cases there might be minor differences of the wording, that's ok, as long as it's clearly referring to the same chapter.\n\n"
        "- In some cases, you may see that the chapter name is divided across 2 entries, that's just a parsing error, but you're still able to identify the chapter by recognizing that the name is split across 2 entries.\n\n"
        "- Where there is some ambiguity, make reasonable guesses that will make the overall TOC make sense. For instance if you're struggling to match a particular chapter and there are 2 possibilities for that chapter, but one of them makes it very close to the start of another chapter, meaning that the chapter is very short compared to all others, that's suggestive that's the wrong one. You can use similar heuristics. But ONLY for those that aren't clear from the first place, which should be most of them.\n\n"
        "Return the result as a JSON list like this: [{\"chapter_title\": \"...\", \"printed_page_number\": ...}, ...]. "
        "Do NOT use Markdown or plain text or bullet lists.\n\n"
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
        final_chapters = match_toc_with_java_headings_gemini(toc, java_headings, book_title) if GEMINI_API_KEY else []
        final_json = {
            "book_title": book_title,
            "authors": authors,
            "toc": final_chapters
        }
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
        final_chapters = match_toc_with_java_headings_gemini(toc, java_headings, book_title) if GEMINI_API_KEY else []
        final_json = {
            "book_title": book_title,
            "authors": authors,
            "toc": final_chapters
        }
        return JSONResponse(content=final_json)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)