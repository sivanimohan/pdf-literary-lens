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
Your response MUST be a single valid JSON object matching the schema below. Do NOT include any markdown, explanations, or extra text. If you cannot extract a field, set its value to null.

Schema Example (CORRECT):
{
    "metadata": {
        "book_title": "Example Title",
        "authors": ["Author One", "Author Two"],
        "publishing_house": "Publisher Name",
        "publishing_year": 2020
    },
    "toc_entries": [
        {
            "chapter_title": "Chapter 1: Introduction",
            "chapter_number": 1,
            "page_number": 5,
            "reference_boolean": false
        },
        {
            "chapter_title": "Bibliography",
            "chapter_number": null,
            "page_number": 200,
            "reference_boolean": true
        }
    ]
}

Schema Example (INCORRECT):
```json
{ "metadata": ... } // markdown or code block
Explanation: ... // extra text
```

Instructions:
- Return ONLY valid JSON, no markdown or extra text.
- If you cannot extract a field, set its value to null.
- If no table of contents entries are found, "toc_entries" MUST be an empty list [].
- Do NOT invent chapter numbers; only include if explicitly written.
- For "reference_boolean", set true ONLY for "Bibliography" or "References".
"""

    prompt_parts = [structured_prompt]
    for path in image_paths:
        prompt_parts.append(Image.open(path))

    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=ExtractionResult
    )

    import re
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                model.generate_content,
                contents=prompt_parts,
                generation_config=generation_config
            )
            text = response.text
            # Post-process: try to extract valid JSON if malformed
            def repair_json(text):
                # Attempt to repair: extract first {...} block
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(0))
                    except Exception:
                        pass
                return None
            try:
                return json.dumps(json.loads(text))
            except Exception:
                repaired = repair_json(text)
                if repaired:
                    return json.dumps(repaired)
                print(f"[Warning] Could not parse JSON from LLM output on attempt {attempt+1}.")
                if attempt + 1 == max_retries:
                    return '{"error": "API call failed or malformed JSON"}'
                await asyncio.sleep(2)
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

    # --- Metadata Extraction from First 15 Pages ---
    print("\n--- Extracting metadata (title, author) from first 15 pages ---")
    metadata_image_paths = image_paths[:15]
    model_metadata = genai.GenerativeModel(model_name="gemini-2.5-pro")
    metadata_result_str = await get_structured_data_from_images(model_metadata, metadata_image_paths)
    def clean_metadata(md):
        # If title/author is missing or 'Unknown', fallback to OCR or aggregation
        if not md or md.get('book_title') in [None, '', 'Unknown Title']:
            md['book_title'] = None
        if not md or not md.get('authors') or md.get('authors') == ['Unknown Author']:
            md['authors'] = None
        return md
    try:
        metadata_result = json.loads(metadata_result_str)
        best_metadata = clean_metadata(metadata_result.get("metadata", {}))
    except (json.JSONDecodeError, TypeError):
        print("Warning: Could not parse metadata JSON from first 15 pages.")
        best_metadata = {}

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

    def fix_toc_fields(toc):
        filtered = []
        non_chapter_terms = ["index", "notes", "acknowledgments", "references", "bibliography", "further reading"]
        for item in toc:
            # Fix field typo
            if 'page_page' in item:
                item['page_number'] = item.pop('page_page')
            title = item.get('chapter_title', '').strip().lower()
            # Filter out non-chapter entries
            if any(term in title for term in non_chapter_terms):
                continue
            filtered.append(item)
        return filtered

    try:
        final_data = json.loads(final_result_str)
    except (json.JSONDecodeError, TypeError):
        print("\n--- ❌ FINAL RESULT ---")
        print("ERROR: Failed to parse the final JSON output from the Pro model.")
        return None

    print("\n--- Consolidating final results ---")
    # Use metadata from first 15 pages, fallback to best from pass 1 if missing
    if not best_metadata:
        max_filled_fields = -1
        for result in all_parsed_results_pass1:
            metadata = result.get("metadata", {})
            metadata = clean_metadata(metadata)
            if metadata:
                filled_count = sum(1 for value in metadata.values() if value is not None)
                if filled_count > max_filled_fields:
                    max_filled_fields = filled_count
                    best_metadata = metadata

    final_combined_toc = final_data.get("toc_entries", [])
    final_combined_toc = fix_toc_fields(final_combined_toc)
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