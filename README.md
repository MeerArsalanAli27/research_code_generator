# AI Research Paper to Code Generator

AI Research Paper to Code Generator extracts useful information from a research paper and creates a runnable machine-learning pipeline. Papers can be supplied as a URL or as a PDF upload.

The application has a React/Vite frontend and a FastAPI backend. The backend extracts paper text, formulas, and image text, then uses a sequential Agno pipeline to analyze the paper and generate code. If the AI agent pipeline is unavailable or fails, the built-in fallback generator is used.

## Features

- Process a paper from a URL or PDF file
- Extract paper text and mathematical formulas
- Extract text from images with optional EasyOCR support
- Generate PyTorch or TensorFlow code
- Use OpenRouter, OpenAI, Anthropic, Gemini, or Grok models
- Fall back to deterministic code generation when agent dependencies or model calls fail
- Health and API information endpoints

## Project Structure

```text
AI_researchpaper_to_code/
|-- backend/
|   |-- main.py
|   |-- requirements.txt
|   `-- utils/
|       |-- extract_text_from_image.py
|       |-- fall_back_code.py
|       `-- find_formulas.py
`-- research-code-genie/
    |-- package.json
    `-- src/
        |-- components/
        |-- pages/
        `-- App.tsx
```

## Requirements

- Python 3.8 or newer
- Node.js 16 or newer
- npm
- Poppler for PDF-to-image conversion used by `pdf2image`

On Windows, install Poppler and add its `bin` directory to `PATH`. The backend can still extract PDF text when image conversion is unavailable, but image OCR will be skipped.

## Installation

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Frontend

```powershell
cd research-code-genie
npm install
```

## Running the Application

Start the backend from the `backend` directory:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

Start the frontend in a second terminal:

```powershell
cd research-code-genie
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`.

The backend API is available at `http://localhost:8001`. Interactive API documentation is available at `http://localhost:8001/docs`.

## API

### `GET /health`

Returns the backend health status:

```json
{"status": "healthy"}
```

### `GET /`

Returns API metadata, supported LLM providers, the default provider, and supported frameworks.

### `POST /process_url`

Send a `multipart/form-data` request with:

| Field | Required | Description |
| --- | --- | --- |
| `url` | Yes | URL of the research paper or article |
| `framework` | No | `PyTorch` or `TensorFlow`; defaults to `PyTorch` |
| `llm` | No | `openrouter`, `openai`, `anthropic`, `gemini`, or `grok` |
| `api_key` | Usually | Provider API key; can be omitted when using server-side OpenRouter configuration |

Example:

```powershell
curl.exe -X POST http://localhost:8001/process_url `
  -F "url=https://arxiv.org/abs/2302.13971" `
  -F "framework=PyTorch" `
  -F "llm=openrouter" `
  -F "api_key=YOUR_API_KEY"
```

### `POST /process_pdf`

Send a `multipart/form-data` request with the same fields as `/process_url`, replacing `url` with a required `file` field containing a PDF.

Example:

```powershell
curl.exe -X POST http://localhost:8001/process_pdf `
  -F "file=@paper.pdf" `
  -F "framework=PyTorch" `
  -F "llm=openrouter" `
  -F "api_key=YOUR_API_KEY"
```

Successful processing returns JSON containing:

- `text`: extracted paper text
- `formulas`: detected formulas
- `images_with_text`: processed images and OCR results
- `image_analysis`: image analysis data, when available
- `code`: generated machine-learning code

## API Keys

For server-side configuration, create a `.env` file in `backend` or set an environment variable before starting the server:

```powershell
$env:OPENROUTER_API_KEY = "your-key"
```

Never commit API keys or place them in source control. Request-provided keys are used only for the current processing request.

## Frontend Commands

Run these commands from `research-code-genie`:

```powershell
npm run dev       # Start the Vite development server
npm run build     # Create a production build
npm run preview   # Preview the production build locally
```

## Notes

- The frontend currently expects the backend at `http://localhost:8001`.
- URL processing uses HTTP extraction and falls back to simpler scraping when advanced scraping is unavailable.
- EasyOCR is loaded lazily. Backend startup does not require a GPU.
- Generated code should be reviewed and tested before being used in research or production.