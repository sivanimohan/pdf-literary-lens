import sys
import os

try:
    import google.generativeai as genai
    from pdf2image import convert_from_path
    from pydantic import BaseModel
    import asyncio
    import time
    from pathlib import Path
    from PIL import Image
    import json
    # Google Colab drive and reportlab are optional, needed for special use
    # from google.colab import drive
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from typing import Optional, List
    print("✅ Pre-flight check passed. All libraries are correctly imported.")
except ImportError as e:
    print(f"\n--- ❌ CRITICAL ERROR: A required library failed to import: {e} ---")
    sys.exit()

# Mount Google Drive for input PDF (optional, comment out if not in Colab)
# drive.mount('/content/drive')

# Explicitly type the API key in the code itself (move to env var in prod)
API_KEY = "AIzaSyCLCrNAI4XYyFtLBThmo8dQjzi6L9EHrE0"
try:
    genai.configure(api_key=API_KEY)
    print("API Key configured successfully.")
except Exception as e:
    print(f"An error occurred during API configuration: {e}")
    API_KEY = None

class TocEntry(BaseModel):
    chapter_title: str
    chapter_number: Optional[int]
    page_number: int
    reference_boolean: bool

class BookMetadata(BaseModel):
    book_title: Optional[str]
    authors: Optional[List[str]]
    publishing_house: Optional[str]
    publishing_year: Optional[int]

class ExtractionResult(BaseModel):
    metadata: BookMetadata
    toc_entries: list

def create_dummy_pdf(file_path):
    print(f"Creating a dummy PDF at {file_path}...")
    c = canvas.Canvas(file_path, pagesize=letter)
    width, height = letter
    c.drawString(100, height - 100, "LSD Psychotherapy by Stanislav Grof, MAPS Press, 2001")
    c.showPage()
    c.drawString(100, height - 100, "Table of Contents")
    c.drawString(120, height - 140, "1. The First Chapter ............ 9")
    c.drawString(140, height - 160, "A Sub-Chapter ............... 12")
    c.drawString(120, height - 180, "2. The Second Chapter ........... 25")
    c.showPage()
    c.drawString(100, height-100, "Back Matter")
    c.drawString(120, height - 140, "Appendix A .................. 140")
    c.drawString(120, height - 160, "Bibliography .................. 150")
    c.drawString(120, height - 180, "Index ......................... 165")
    c.showPage()
    for i in range(4, 21):
        c.drawString(100, height - 100, f"This is page {i}.")
        c.showPage()
    c.save()
    print("Dummy PDF created successfully.")

LOG_LINES = []

def log(msg):
    print(msg)
    LOG_LINES.append(msg)

async def get_structured_data_from_images(model, image_paths):
    print(f"Processing a chunk of {len(image_paths)} images...")
    structured_prompt = """
Analyze the following book pages to extract metadata and the main table of contents.
Your response will be programmatically constrained to the JSON schema provided.

The JSON object you return has two top-level keys: \"metadata\" and \"toc_entries\".

1.  **\"metadata\"**: This object contains the book's metadata.
    * \"book_title\": The full title of the book.
    * \"authors\": A list of all author names.
    * \"publishing_house\": The name of the publisher.
    * \"publishing_year\": The integer year of publication.
    * If any metadata field is not found on the pages, its value MUST be null.

2.  **\"toc_entries\"**: This is a JSON array containing ONLY THE MAIN, TOP-LEVEL CHAPTERS.
    * **CRITICAL**: You MUST IGNORE indented sub-chapters. Main chapters are typically not indented and have larger page gaps between them. Do not include sub-chapters in the list.
    * Each object in the array represents one main chapter and MUST have these four keys:
        * \"chapter_title\": The string name of the chapter.
        * \"chapter_number\": The integer chapter number. ONLY include this if the number is explicitly written (e.g., \"1.\", \"Chapter 5\"). You MUST NOT invent, assume, or count chapter numbers. If no number is written, the value MUST be null.
        * \"page_number\": The integer page number.
        * \"reference_boolean\": A boolean value. It MUST be `true` ONLY for sections explicitly titled \"Bibliography\" or \"References\". For all other entries (including \"Index\", \"Appendix\", \"Coda\", etc.), it MUST be `false`.

If no table of contents entries are found, \"toc_entries\" MUST be an empty list [].

IMPORTANT: Return ONLY valid JSON. Do NOT include any markdown, explanations, or extra text. The output must be a single valid JSON object and nothing else.
"""

    prompt_parts = [structured_prompt]
    for path in image_paths:
        prompt_parts.append(Image.open(path))

    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=ExtractionResult
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                model.generate_content,
                contents=prompt_parts,
                generation_config=generation_config
            )
            return response.text
        except Exception as e:
            error_str = str(e)
            if "Connection reset by peer" in error_str or "Deadline Exceeded" in error_str:
                print(f"Attempt {attempt + 1} failed. Retrying...")
                if attempt + 1 == max_retries: return '{"error": "API call failed"}'
                await asyncio.sleep(2)
            else:
                return f'{{"error": "API call failed", "details": "{error_str}"}}'

async def process_pdf(pdf_path):
    if not API_KEY:
        print("Cannot proceed without a valid API Key.")
        return None

    print("\nStep 1: Converting first 20 PDF pages to JPEG images...")
    output_dir = Path("pages")
    output_dir.mkdir(exist_ok=True)
    images = convert_from_path(pdf_path, last_page=20, fmt='jpeg', output_folder=output_dir, output_file="page_")
    image_paths = sorted([str(p) for p in output_dir.glob("*.jpg")])
    print(f"Successfully converted {len(image_paths)} pages.")

    # --- Pass 1: Discovery Pass with Flash Lite Model ---
    print("\n--- Starting Pass 1: Discovery (using gemini-2.5-flash-lite) ---")
    model_flash = genai.GenerativeModel(model_name="gemini-2.5-flash-lite")
    chunk_size = 5
    discovery_tasks = []
    for i in range(0, len(image_paths), chunk_size):
        chunk_paths = image_paths[i:i + chunk_size]
        discovery_tasks.append(get_structured_data_from_images(model_flash, chunk_paths))
    discovery_results = await asyncio.gather(*discovery_tasks)

    toc_page_indices = set()
    all_parsed_results_pass1 = []
    for i, res_str in enumerate(discovery_results):
        try:
            res_json = json.loads(res_str)
            all_parsed_results_pass1.append(res_json)
            if res_json.get("toc_entries"):
                start_index = i * chunk_size
                end_index = start_index + chunk_size
                for page_idx in range(start_index, min(end_index, len(image_paths))):
                    toc_page_indices.add(page_idx)
        except (json.JSONDecodeError, TypeError):
            print(f"Warning: Could not parse JSON from discovery chunk {i+1}.")
            continue

    if not toc_page_indices:
        print("\n--- Discovery Pass found no pages with TOC entries. Aborting. ---")
        return None

    print(f"\n--- Discovery Pass identified {len(toc_page_indices)} potential TOC pages. ---")

    # --- Pass 2: Verification Pass with Pro Model ---
    print("\n--- Starting Pass 2: Verification (using gemini-2.5-pro) ---")
    model_pro = genai.GenerativeModel(model_name="gemini-2.5-pro")
    targeted_image_paths = [image_paths[i] for i in sorted(list(toc_page_indices))]
    final_result_str = await get_structured_data_from_images(model_pro, targeted_image_paths)

    try:
        final_data = json.loads(final_result_str)
    except (json.JSONDecodeError, TypeError):
        print("\n--- ❌ FINAL RESULT ---")
        print("ERROR: Failed to parse the final JSON output from the Pro model.")
        return None

    print("\n--- Consolidating final results ---")
    best_metadata = {}
    max_filled_fields = -1
    for result in all_parsed_results_pass1:
        metadata = result.get("metadata", {})
        if metadata:
            filled_count = sum(1 for value in metadata.values() if value is not None)
            if filled_count > max_filled_fields:
                max_filled_fields = filled_count
                best_metadata = metadata

    final_combined_toc = final_data.get("toc_entries", [])
    final_combined_toc.sort(key=lambda item: item.get('page_number', 0))
    deduplicated_toc = []
    seen_titles = set()
    for item in final_combined_toc:
        title = item.get('chapter_title', '').strip().lower()
        if title and title not in seen_titles:
            deduplicated_toc.append(item)
            seen_titles.add(title)
    final_result = {
        "metadata": best_metadata,
        "toc_entries": deduplicated_toc
    }
    return final_result

async def main(pdf_path):
    if not API_KEY:
        print("Cannot run without an API Key.")
        return

    max_attempts = 2
    final_data = None
    for attempt in range(max_attempts):
        print(f"\n{'='*20} STARTING ATTEMPT {attempt + 1} of {max_attempts} {'='*20}")
        final_data = await process_pdf(pdf_path)

        if final_data:
            print("\n\n--- ✅ SUCCESS: COMBINED, SORTED, & DEDUPLICATED FINAL DATA ---")
            print(json.dumps(final_data, indent=2))
            with open("lsd_psychotherapy_toc_gemini_flashlite.json", "w") as f:
                json.dump(final_data, f, indent=2)
            log("Saved extracted data to lsd_psychotherapy_toc_gemini_flashlite.json")
            break
        else:
            if attempt < max_attempts - 1:
                print(f"\n--- ⚠️ Attempt {attempt + 1} failed. Retrying one last time... ---")
                await asyncio.sleep(3)
            else:
                print("\n\n--- ❌ FINAL RESULT ---")
                print("ERROR: All attempts failed. Could not extract valid data.")

    with open("lsd_psychotherapy_toc_gemini_flashlite.log.txt", "w") as f:
        f.write("\n".join(LOG_LINES))
    print("Saved log to lsd_psychotherapy_toc_gemini_flashlite.log.txt")

## The main() and CLI logic is only for standalone use. For FastAPI, process_pdf must be importable at top-level.