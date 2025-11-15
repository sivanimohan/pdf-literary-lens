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

## Usage

### Prerequisites

- Java (project appears Java-based)
- [Maven](https://maven.apache.org/) (`pom.xml` is provided)
- Python (for scripts in the `python-server` directory or additional tools)
- Docker (optional, Dockerfile provided for containerized execution)

### Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/sivanimohan/pdf-literary-lens.git
   cd pdf-literary-lens
   ```

2. **Build and Run Java Application**
   ```bash
   mvn package
   java -jar target/your-app.jar
   ```

3. **Run Chapter Extraction Script**
   ```bash
   ./run_chapter_extraction.bat
   ```

4. **Deploying (Railway example)**
   - See `railway_deploy_guide.txt` for full cloud deployment instructions.

5. **Python Server (Optional)**
   - Further instructions may be found in the `/python-server` directory if you wish to use or extend the API capabilities.

## Data and Outputs

- Book data (in `bookdata`), detected headings (`detected_headings.json`), and analysis results can be used for downstream literary or text mining applications.

## Contributing

Since this project is a fork and highly specialized for literary PDF analysis, contributions are welcome especially in areas such as:
- Improving chapter/heading detection.
- Enhancements for semantic analysis.
- Integrations with other text mining tools.

## License

No license is specified; consult the repo owner if in doubt regarding use.

## Attribution

Forked from [kongole/stirling-pdf-proxy](https://github.com/kongole/stirling-pdf-proxy).

---

**Primary Language:** Java  
Other technologies: Python for scripting/server and various configuration/text data files.
