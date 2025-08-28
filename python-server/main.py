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
    log_buffer = []
    log_buffer.append("[DEBUG] Starting PDF upload and save...")
    start = time.time()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    log_buffer.append(f"[DEBUG] PDF saved to {tmp_path}")
    log_buffer.append(f"[TIME] PDF upload and save: {time.time() - start:.2f} seconds")

    log_buffer.append("[DEBUG] Extracting text from first 15 pages...")
    start = time.time()
    reader = PdfReader(tmp_path)
    num_pages = min(15, len(reader.pages))
    extracted_text = "\n".join([reader.pages[i].extract_text() or "" for i in range(num_pages)])
    log_buffer.append(f"[DEBUG] Extracted text from {num_pages} pages.")
    log_buffer.append(f"[TIME] Text extraction (first 15 pages): {time.time() - start:.2f} seconds")
    log_buffer.append("[LOG] Extracted text (first 15 pages):\n" + extracted_text)

    log_buffer.append("[DEBUG] Calling Gemini for TOC extraction...")
    start = time.time()
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    toc_prompt = (
        "You are an expert in book structure extraction. "
        "Given the text from the first 15 pages of a book, extract a detailed and accurate table of contents. "
        "Include all chapters, sections, and subsections with their titles and page numbers if available. "
        "Format the output as a clear, structured list.\n"
        f"Text:\n{extracted_text}"
    )
    toc_result = model.generate_content(toc_prompt)
    toc = toc_result.text
    log_buffer.append("[LOG] Gemini TOC prompt:\n" + toc_prompt)
    log_buffer.append("[LOG] Gemini TOC output:\n" + toc)
    log_buffer.append("[DEBUG] Gemini TOC extraction complete.")
    log_buffer.append(f"[TIME] Gemini TOC extraction: {time.time() - start:.2f} seconds")

    import json
    import os
    log_buffer.append("[DEBUG] Sending PDF to Java backend for chapter headings...")
    start = time.time()
    with open(tmp_path, "rb") as pdf_file:
        java_url = "https://dependable-expression-production-3af1.up.railway.app/get/pdf-info/detect-chapter-headings"
        response = requests.post(java_url, files={"file": (file.filename, pdf_file, file.content_type)})
        headings = response.json()
    log_buffer.append("[DEBUG] Received chapter headings from Java backend.")
    log_buffer.append(f"[TIME] Java backend chapter headings: {time.time() - start:.2f} seconds")

    detected_path = os.path.join(os.path.dirname(__file__), "..", "detected_headings.json")
    log_buffer.append(f"[DEBUG] Saving detected headings to {detected_path}")
    with open(detected_path, "w", encoding="utf-8") as f:
        json.dump(headings, f, ensure_ascii=False, indent=2)

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
    import re
    def parse_gemini_json(text):
        cleaned = re.sub(r"^```json|```$", "", text.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except Exception:
            return {}

    log_buffer.append("[LOG] Gemini book metadata prompt:\n" + prompt1)
    log_buffer.append("[DEBUG] Calling Gemini for book metadata and TOC...")
    start = time.time()
    result1 = model.generate_content(prompt1)
    book_info = parse_gemini_json(result1.text)
    log_buffer.append("[LOG] Gemini book metadata output:\n" + result1.text)
    log_buffer.append("[DEBUG] Gemini book metadata extraction complete.")
    log_buffer.append(f"[TIME] Gemini book metadata extraction: {time.time() - start:.2f} seconds")

    # --- Gemini Prompt 2: Match expected chapters to PDF headings ---
    # Prepare variables for prompt
    book_title = book_info.get('book_title') if isinstance(book_info, dict) else ''
    real_chapters = book_info.get('toc') if isinstance(book_info, dict) else []
    rawData = headings
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
    log_buffer.append("[LOG] Gemini chapter matching prompt:\n" + prompt2)
    log_buffer.append("[DEBUG] Calling Gemini for chapter matching...")
    start = time.time()
    result2 = model.generate_content(prompt2)
    matched_chapters = parse_gemini_json(result2.text)
    log_buffer.append("[LOG] Gemini chapter matching output:\n" + result2.text)
    log_buffer.append("[DEBUG] Gemini chapter matching complete.")
    log_buffer.append(f"[TIME] Gemini chapter matching: {time.time() - start:.2f} seconds")

    # Try to parse the first 15 pages text as JSON if possible, else keep as string
    try:
        first_15_json = json.loads(extracted_text)
    except Exception:
        first_15_json = extracted_text

    # Format cleaned_headings.json as requested, with short and long summaries
    cleaned_path = os.path.join(os.path.dirname(__file__), "..", "cleaned_headings.json")
    cleaned_json = {
        "book_title": book_info.get("book_title") if isinstance(book_info, dict) else "",
        "authors": book_info.get("authors") if isinstance(book_info, dict) else [],
        "toc": []
    }

    # Extract all pages' text for summary generation
    print("[DEBUG] Extracting text from all pages for summaries...")
    start = time.time()
    all_pages_text = [reader.pages[i].extract_text() or "" for i in range(len(reader.pages))]
    print(f"[TIME] Text extraction (all pages): {time.time() - start:.2f} seconds")

    # Use matched_chapters if available, else fallback to book_info['toc']
    toc_source = matched_chapters if isinstance(matched_chapters, list) and matched_chapters else (book_info.get("toc") if isinstance(book_info, dict) else [])
    num_chapters = len(toc_source)
    print(f"[INFO] Number of matched chapters: {num_chapters}")

    # Prepare chapter texts for parallel summary generation
    chapter_infos = []
    for idx, ch in enumerate(toc_source):
        if idx >= num_chapters:
            break
        page_num = ch.get("page_start") if "page_start" in ch else ch.get("page_number", 0)
        next_page = toc_source[idx+1].get("page_start") if idx+1 < len(toc_source) and "page_start" in toc_source[idx+1] else toc_source[idx+1].get("page_number", 0) if idx+1 < len(toc_source) else len(all_pages_text)
        start_idx = max(page_num-1, 0)
        end_idx = max(next_page-1, start_idx+1)
        chapter_text = "\n".join(all_pages_text[start_idx:end_idx])
        chapter_infos.append((ch, chapter_text, idx))

    # Run Gemini summary generation in parallel
    tasks = [get_summaries(model, chapter_text, idx) for ch, chapter_text, idx in chapter_infos]
    summaries = await asyncio.gather(*tasks)

    for (ch, chapter_text, idx), (short_summary, long_summary) in zip(chapter_infos, summaries):
        raw_title = ch.get("chapter_full_title", "")
        import re
        title_only = re.sub(r"^Chapter\s*\d+[:.]?\s*", "", raw_title, flags=re.IGNORECASE).strip()
        bib_titles = ["bibliography", "references", "works cited"]
        is_bibliography = any(title_only.lower() == bib for bib in bib_titles)
        reference_id = f"ref-{idx+1}" if is_bibliography else None
        cleaned_json["toc"].append({
            "chapter_numerical_number": ch.get("chapter_numerical_number"),
            "chapter_full_title": title_only,
            "page_number": ch.get("page_start") if "page_start" in ch else ch.get("page_number", 0),
            "is_bibliography": is_bibliography,
            "reference_id": reference_id,
            "short_summary": short_summary,
            "long_summary": long_summary,
            "chapter_text": chapter_text
        })

    # Define chapter_texts before saving
    chapter_texts = [chapter_text for (_, chapter_text, _) in chapter_infos]

    # Save only the final analysis JSON
    final_json_path = os.path.join(os.path.dirname(__file__), "..", "final_book_analysis.json")
    final_json = {
        "book_title": cleaned_json.get("book_title", ""),
        "authors": cleaned_json.get("authors", []),
        "toc": cleaned_json.get("toc", [])
    }
    log_buffer.append(f"[DEBUG] Saving final minimal JSON to {final_json_path}")
    with open(final_json_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)
    log_buffer.append(f"[TIME] Total workflow: {time.time() - start_total:.2f} seconds")
    log_buffer.append("[DEBUG] Workflow complete. Returning response.")
    # Write all logs to a single file at the end
    log_path = os.path.join(os.path.dirname(__file__), "..", "detailed_log.txt")
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("\n\n".join(log_buffer))
    return final_json
