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

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI()

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

        reader = PdfReader(tmp_path)
        num_pages = min(15, len(reader.pages))
        extracted_text = "\n".join([reader.pages[i].extract_text() or "" for i in range(num_pages)])
        log_data["extracted_text_first_15"] = extracted_text

        # Use Gemini 2.5 Pro for all calls
        model = genai.GenerativeModel("gemini-2.5-pro")

        # 1. TOC Extraction: exhaustive prompt
        prompt1 = (
            "You are a meticulous data extractor. From the following text from the first 15 pages of a PDF, extract the book title, authors, and a complete Table of Contents (TOC).\n"
            "Your main goal is to be exhaustive with the TOC. You must extract *every single item* listed, including:\n"
            "- Parts or Sections (e.g., 'Part I: Title')\n"
            "- Standard chapters (e.g., '1. Chapter Title')\n"
            "- Non-numbered sections like 'Preface', 'Foreword', 'Introduction', 'Acknowledgments', 'Conclusion', 'Postscript', etc.\n"
            "- Appendices and end matter like 'Notes', 'References', 'Bibliography', and 'Index'.\n"
            "Return the results as a single JSON object in the exact format below. Do not omit any items from the TOC.\n"
            "{\n  'book_title': 'Exact Book Title',\n  'authors': ['Author One', 'Author Two'],\n  'toc': [\n    {'chapter_numerical_number': 1, 'chapter_full_title': 'Chapter 1: Title'},\n    {'chapter_numerical_number': null, 'chapter_full_title': 'Preface'}\n  ]\n}\n"
            f"TEXT FROM FIRST 15 PAGES:\n{extracted_text}"
        )
        log_data["gemini_metadata_prompt"] = prompt1

        try:
            result1 = model.generate_content(prompt1)
            book_info = parse_gemini_json(result1.text)
            log_data["gemini_metadata_output"] = result1.text
        except Exception as e:
            log_data["gemini_metadata_error"] = str(e)
            book_info = {}

        book_title = book_info.get('book_title', '')
        real_chapters = book_info.get('toc', [])

        # 2. Java headings (noisy)
        try:
            with open(tmp_path, "rb") as pdf_file:
                java_url = "https://dependable-expression-production-3af1.up.railway.app/get/pdf-info/detect-chapter-headings"
                response = requests.post(java_url, files={"file": (file.filename, pdf_file, file.content_type)})
                headings = response.json()
            log_data["java_headings"] = headings
        except Exception as e:
            log_data["java_error"] = str(e)
            headings = []

        # 3. Chapter Matching: clear prompt, ignore noise
        prompt2 = (
            f"You are a data correlation expert. Your task is to assign the correct starting page number to a list of expected book chapters.\n"
            f"You will be given two lists:\n"
            f"1. `EXPECTED CHAPTERS`: A clean list of chapters extracted from the book's Table of Contents.\n"
            f"2. `PDF HEADINGS FOUND`: A noisy list of all text headings found in the PDF. This list is messy and may contain irrelevant text from page headers, footers, or the index.\n\n"
            f"**Your Task:** For each chapter in the `EXPECTED CHAPTERS` list, find the best matching entry in the `PDF HEADINGS FOUND` list and extract its `pageNumber`.\n"
            f"Focus on matching the chapter title. Ignore the noisy, irrelevant headings.\n\n"
            f"**EXPECTED CHAPTERS:**\n{json.dumps(real_chapters, indent=2)}\n\n"
            f"**PDF HEADINGS FOUND:**\n{json.dumps(headings, indent=2)}\n\n"
            "**Output Rules:**\n"
            "- Return a single JSON array containing ALL chapters from the `EXPECTED CHAPTERS` list.\n"
            "- Use the exact titles from the `EXPECTED CHAPTERS` list for the `chapter_full_title` field.\n"
            "- If a good match is found, use its page number for `page_start`.\n"
            "- If no plausible match is found for a chapter, use `0` as the `page_start`.\n"
            "- The output format must be exactly: `[ { 'chapter_numerical_number': ..., 'chapter_full_title': '...', 'page_start': ... } ]`"
        )
        log_data["gemini_chapter_match_prompt"] = prompt2

        try:
            result2 = model.generate_content(prompt2)
            matched_chapters = parse_gemini_json(result2.text)
            log_data["gemini_chapter_match_output"] = result2.text
        except Exception as e:
            log_data["gemini_chapter_match_error"] = str(e)
            matched_chapters = []

        final_json = {
            "book_title": book_info.get("book_title", ""),
            "authors": book_info.get("authors", []),
            "toc": []
        }
        # Always use PDF page index for chapter start pages from Java backend
            toc_source = matched_chapters if isinstance(matched_chapters, list) and matched_chapters else real_chapters
            if isinstance(toc_source, list):
                for ch in toc_source:
                    final_json["toc"].append({
                        "chapter_numerical_number": ch.get("chapter_numerical_number"),
                        "chapter_full_title": ch.get("chapter_full_title"),
                        "page_number": ch.get("page_start") if "page_start" in ch else ch.get("page_number", 0)
                    })
    except Exception as e:
        log_data["fatal_error"] = str(e)
        final_json = {"error": str(e)}

    log_path = os.path.join(os.path.dirname(__file__), "..", "detailed_log.json")
    with open(log_path, "w", encoding="utf-8") as log_file:
        json.dump(log_data, log_file, ensure_ascii=False, indent=2)
    return final_json
