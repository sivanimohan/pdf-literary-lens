from fastapi import FastAPI, UploadFile, File
import requests
import google.generativeai as genai
from PyPDF2 import PdfReader
import tempfile
import os
from dotenv import load_dotenv
import time
import asyncio

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
# print(genai.list_models())

app = FastAPI()

async def get_summaries(model, chapter_text, idx):
    # --- All chapter text logic commented out ---
    # if chapter_text:
    #     # Any logic using chapter_text would go here
    return None, None

@app.post("/process-pdf")
async def process_pdf(file: UploadFile = File(...)):
    start_total = time.time()
    log_data = {}
    try:
        start = time.time()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        log_data["pdf_path"] = tmp_path
        log_data["pdf_upload_time"] = time.time() - start

        start = time.time()
        reader = PdfReader(tmp_path)
        num_pages = min(15, len(reader.pages))
        extracted_text = "\n".join([reader.pages[i].extract_text() or "" for i in range(num_pages)])
        log_data["extracted_text_first_15"] = extracted_text
        log_data["extract_time_first_15"] = time.time() - start

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
        toc_prompt = (
            "You are an expert in book structure extraction. "
            "Given the text from the first 15 pages of a book, extract a detailed and accurate table of contents. "
            "Include all chapters, sections, and subsections with their titles and page numbers if available. "
            "Format the output as a clear, structured list.\n"
            f"Text:\n{extracted_text}"
        )
        log_data["gemini_toc_prompt"] = toc_prompt
        try:
            toc_result = model.generate_content(toc_prompt)
            toc = toc_result.text
            log_data["gemini_toc_output"] = toc
        except Exception as e:
            log_data["gemini_toc_error"] = str(e)

        try:
            with open(tmp_path, "rb") as pdf_file:
                java_url = "https://dependable-expression-production-3af1.up.railway.app/get/pdf-info/detect-chapter-headings"
                response = requests.post(java_url, files={"file": (file.filename, pdf_file, file.content_type)})
                headings = response.json()
            log_data["java_headings"] = headings
        except Exception as e:
            log_data["java_error"] = str(e)

        prompt1 = (
            "The following text is from the first 15 pages of a book's PDF. Your only task is to find the name of the book, the authors, and then the Table of Contents within this text, ignoring everything else.\n"
            "Analyze the text, extract:\n"
            "1. The book title\n"
            "2. The authors\n"
            "3. The complete chapter list with titles\n"
            "Return the results as a single JSON object with this exact format:\n"
            "{\n  'book_title': 'Exact Book Title',\n  'authors': ['Author One', 'Author Two'],\n  'toc': [\n    {'chapter_numerical_number': 1, 'chapter_full_title': 'Chapter 1: Title'},\n    {'chapter_numerical_number': null, 'chapter_full_title': 'Preface'}\n  ]\n}\n"
            "Include all numbered chapters as well as non-numbered sections like 'Preface', 'Introduction', 'Conclusion', etc.\n"
            "If you cannot find a Table of Contents, return 'toc': [] but still try to provide the book title and authors if present.\n"
            f"TEXT FROM FIRST 15 PAGES:\n{extracted_text}"
        )
        log_data["gemini_metadata_prompt"] = prompt1
        import re
        def parse_gemini_json(text):
            cleaned = re.sub(r"^```json|```$", "", text.strip(), flags=re.MULTILINE)
            try:
                return json.loads(cleaned)
            except Exception:
                return {}
        try:
            result1 = model.generate_content(prompt1)
            book_info = parse_gemini_json(result1.text)
            log_data["gemini_metadata_output"] = result1.text
        except Exception as e:
            log_data["gemini_metadata_error"] = str(e)

        book_title = book_info.get('book_title') if isinstance(book_info, dict) else ''
        real_chapters = book_info.get('toc') if isinstance(book_info, dict) else []
        rawData = log_data.get("java_headings", [])
        prompt2 = (
            f"EXPECTED CHAPTERS from Table of Contents for \"{book_title}\":\n"
            f"{json.dumps(real_chapters, indent=2)}\n\n"
            f"PDF HEADINGS FOUND:\n{json.dumps(rawData[:30] if isinstance(rawData, list) else rawData, indent=2)}\n\n"
            "Task: For each expected chapter, find the best matching PDF heading and return the complete list with page numbers.\n"
            "Return ALL expected chapters in this exact JSON format:\n"
            "[\n  {'chapter_numerical_number': 1, 'chapter_full_title': 'Chapter 1: Exact Title', 'page_start': 25},\n  {'chapter_numerical_number': null, 'chapter_full_title': 'Introduction', 'page_start': 5}\n]\n"
            "Rules:\n"
            "- Include ALL chapters from the expected list\n"
            "- Use exact titles from expected chapters\n"
            "- Find page numbers from PDF headings by matching similar titles\n"
            "- If no page found, use 0 as page_start\n"
            "- Return complete JSON array with all chapters"
        )
        log_data["gemini_chapter_match_prompt"] = prompt2
        try:
            result2 = model.generate_content(prompt2)
            matched_chapters = parse_gemini_json(result2.text)
            log_data["gemini_chapter_match_output"] = result2.text
        except Exception as e:
            log_data["gemini_chapter_match_error"] = str(e)

        # Final output: only book title, authors, and chapters with page numbers
        final_json = {
            "book_title": book_info.get("book_title", "") if isinstance(book_info, dict) else "",
            "authors": book_info.get("authors", []) if isinstance(book_info, dict) else [],
            "toc": []
        }
        toc_source = matched_chapters if isinstance(matched_chapters, list) and matched_chapters else (book_info.get("toc") if isinstance(book_info, dict) else [])
        for ch in toc_source:
            final_json["toc"].append({
                "chapter_numerical_number": ch.get("chapter_numerical_number"),
                "chapter_full_title": ch.get("chapter_full_title"),
                "page_number": ch.get("page_start") if "page_start" in ch else ch.get("page_number", 0)
            })
    except Exception as e:
        log_data["fatal_error"] = str(e)
        final_json = {"error": str(e)}
    # Write all logs to a single structured JSON file at the end
    log_path = os.path.join(os.path.dirname(__file__), "..", "detailed_log.json")
    with open(log_path, "w", encoding="utf-8") as log_file:
        json.dump(log_data, log_file, ensure_ascii=False, indent=2)
    return final_json
