# PDF Literary Lens

PDF Literary Lens is a repository focused on analyzing and extracting structured literary information from PDF documents, specifically books. It originated as a fork of the [stirling-pdf-proxy](https://github.com/kongole/stirling-pdf-proxy) project and extends or customizes its features toward literary text extraction, chapter analysis, and semantic insights from PDF book data.

## Features

- **Chapter Detection**: Automatically identify and extract chapters and headings from book PDFs with detected heading outputs (see `detected_headings.json`).
- **Book Data Extraction**: Processes and structures book metadata for further analysis (refer to `bookdata`, `final_book_analysis.json`).
- **Semantic Analysis**: Supports deeper analysis on the text structure and content, with results stored under the `final_analysis` directory.
- **Integration Points**: Provides a `python-server` directory, possibly for auxiliary services or API endpoints for PDF processing.
- **Automated Workflows**: Contains scripts such as `run_chapter_extraction.bat` for quick automation of chapter extraction tasks.
- **Deployment Guides**: Includes a `railway_deploy_guide.txt` for deploying the project, likely to cloud infrastructure.

## Directory Structure

- `/src` - Primary source code for core application logic (likely Java, based on language stats and presence of `pom.xml`).
- `/python-server` - Auxiliary code or microservice, probably for analysis or API endpoints.
- `/final_analysis` - Outputs and results of semantic and structural analyses.
- `detected_headings.json`, `final_book_analysis.json` - Exported data about detected chapters/headings and aggregated book analysis.
# PDF Literary Lens

PDF Literary Lens extracts and analyzes structured literary data from PDF books. It provides tools and workflows to detect chapters/headings, collect book metadata, and run semantic analyses on extracted text. The project began as a fork of [kongole/stirling-pdf-proxy](https://github.com/kongole/stirling-pdf-proxy) and is tailored for literary/text-mining use cases.

## Key Features

- Chapter detection and heading extraction (see `detected_headings.json`).
- Structured book metadata extraction (outputs in `bookdata/` and `final_book_analysis.json`).
- Higher-level semantic/structural analysis (results in `final_analysis/`).
- Auxiliary Python server for analysis or API integration (`python-server/`).
- Containerization support via `Dockerfile` and a Railway deployment guide.

## Quick Start

Prerequisites: Java (OpenJDK 11+ recommended), Maven, Python 3.8+, and Docker (optional).

1. Clone the repo

```bash
git clone https://github.com/sivanimohan/pdf-literary-lens.git
cd pdf-literary-lens
```

2. Build the Java project with Maven

```bash
mvn -q package
# After build, run the produced JAR (replace with the actual artifact name under target/)
java -jar target/*.jar
```

3. Run the Python server (optional)

```bash
cd python-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

4. Use Docker (optional)

```bash
# Build image in repository root
docker build -t pdf-literary-lens .
# Run container (adjust port as needed)
docker run --rm -p 8080:8080 pdf-literary-lens
```

5. Run chapter extraction (Windows batch included)

```bash
# Windows
./run_chapter_extraction.bat
# For Linux/macOS: there may be an equivalent shell script or run the relevant Java/Python command directly.
```

## Project Layout

- `src/` — Java source and application code (see `pom.xml`).
- `python-server/` — Small Python service for supplementary analysis / API (`main.py`, `requirements.txt`).
- `bookdata/` — Raw or intermediate extracted book data.
- `detected_headings.json` — Example output of heading detection.
- `final_book_analysis.json` and `final_analysis/` — Aggregated/semantic analysis outputs.
- `Dockerfile`, `railway_deploy_guide.txt` — Containerization and deployment notes.

## How to Contribute

- Report issues and feature requests via GitHub Issues.
- Open pull requests with focused changes and tests/examples where applicable.
- If adding code, follow the existing style: Java for core app, Python for scripting/services.

If you'd like help improving detection accuracy or adding dataset examples, open an issue describing the input PDFs and desired output.

## Notes on Licensing

No license file is included in the repository. If you plan to reuse or redistribute code, contact the repository owner or add a license via a pull request.

## Attribution

Forked and adapted from [kongole/stirling-pdf-proxy](https://github.com/kongole/stirling-pdf-proxy).

---

If you'd like, I can also:

- Add badges (build / license / codecov) to the top of this README.
- Create a short `CONTRIBUTING.md` with a development checklist.
- Add a minimal shell script for chapter extraction on Unix-like systems.

