# import os
# import requests
# import re
# import io
# import base64
# import numpy as np
# from pdf2image import convert_from_bytes
# from fastapi import FastAPI, HTTPException, UploadFile, File, Form
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from typing import List, Dict, Optional
# from urllib.parse import urljoin
# from bs4 import BeautifulSoup
# import uvicorn
# from utils.fall_back_code import fallback_code
# from utils.find_formulas import find_formulas
# from utils.extract_text_from_image import extract_text_from_image
# from PyPDF2 import PdfReader

# # ---------------------------------------------------------------------------
# # Optional dependencies (gracefully degrade if not installed)
# # ---------------------------------------------------------------------------

# try:
#     from crawl4ai import AsyncWebCrawler
#     CRAWL4AI_AVAILABLE = True
# except ImportError:
#     AsyncWebCrawler = None
#     CRAWL4AI_AVAILABLE = False

# try:
#     from crewai import Agent, Task, Crew, Process, LLM
#     from crewai.tools import BaseTool
#     CREWAI_AVAILABLE = True
# except ImportError:
#     Agent = Task = Crew = Process = LLM = None

#     class BaseTool:
#         pass

#     CREWAI_AVAILABLE = False

# # ---------------------------------------------------------------------------
# # FastAPI app
# # ---------------------------------------------------------------------------

# app = FastAPI(title="Paper Code Generator API", version="1.0.0")

# _ALLOW_ALL = os.getenv("FASTAPI_ALLOW_ALL_ORIGINS", "true").lower() in {"true", "1", "yes"}
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"] if _ALLOW_ALL else [
#         "http://localhost:5173",
#         "http://localhost:8000",
#         "http://localhost:3000",
#         "http://127.0.0.1:5173",
#         "http://127.0.0.1:3000",
#         "http://localhost:8001",
#         "http://127.0.0.1:8001",
#     ],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # ---------------------------------------------------------------------------
# # Lazy OCR reader (avoids blocking startup if no GPU)
# # ---------------------------------------------------------------------------

# _reader = None


# def get_reader():
#     global _reader
#     if _reader is None:
#         try:
#             import easyocr
#             _reader = easyocr.Reader(['en'])
#         except Exception:
#             _reader = None
#     return _reader


# # ---------------------------------------------------------------------------
# # LLM configuration maps
# # ---------------------------------------------------------------------------

# # Environment variable that holds the API key for each provider
# LLM_ENV_MAP = {
#     "grok": "XAI_API_KEY",
#     "openai": "OPENAI_API_KEY",
#     "anthropic": "ANTHROPIC_API_KEY",
#     # LiteLLM (used by CrewAI internally) reads GEMINI_API_KEY for gemini/ provider
#     "gemini": "GEMINI_API_KEY",
# }

# # LiteLLM model strings: must use "provider/model" format so CrewAI routes correctly
# LLM_MODEL_MAP = {
#     "grok": "xai/grok-beta",
#     "openai": "gpt-4o",
#     "anthropic": "anthropic/claude-3-5-sonnet-20241022",
#     "gemini": "gemini/gemini-1.5-flash",
# }

# # ---------------------------------------------------------------------------
# # Tools & Models
# # ---------------------------------------------------------------------------


# class PDFReadTool(BaseTool):
#     name: str = "PDFReadTool"
#     description: str = "Extracts text from a PDF file"

#     def _run(self, file_path) -> str:
#         """Extract text from a PDF file."""
#         try:
#             reader = PdfReader(file_path)
#             text = ""
#             for page in reader.pages:
#                 text += page.extract_text() or ""
#             return text
#         except Exception as e:
#             raise ValueError(f"Error reading PDF: {e}")


# class ProcessResponse(BaseModel):
#     text: str
#     formulas: List[str]
#     images_with_text: List[Dict]
#     image_analysis: Optional[List[Dict]] = None
#     code: str


# # ---------------------------------------------------------------------------
# # Helper functions
# # ---------------------------------------------------------------------------


# def set_llm_api_key(llm: str, api_key: str):
#     """Validate LLM choice and set the correct environment variable."""
#     normalized_llm = llm.strip().lower()
#     if normalized_llm not in LLM_ENV_MAP:
#         raise HTTPException(
#             status_code=400,
#             detail=f"Unsupported llm '{llm}'. Must be one of {list(LLM_ENV_MAP.keys())}",
#         )
#     os.environ[LLM_ENV_MAP[normalized_llm]] = api_key


# def build_crewai_llm(llm_name: str, api_key: str):
#     """
#     Build a CrewAI LLM object for the given provider.

#     CrewAI uses LiteLLM under the hood and requires:
#       - model string in 'provider/model' format  (e.g. 'gemini/gemini-1.5-flash')
#       - api_key passed directly — especially important for Gemini / Google AI Studio
#         because LiteLLM reads GEMINI_API_KEY, NOT GOOGLE_API_KEY.

#     Passing a bare string such as "gemini" to Agent(llm=...) does NOT work.
#     """
#     if LLM is None:
#         # CrewAI not installed; caller must handle CREWAI_AVAILABLE=False guard
#         return llm_name.lower()

#     normalized = llm_name.strip().lower()
#     model_string = LLM_MODEL_MAP.get(normalized, normalized)
#     return LLM(
#         model=model_string,
#         api_key=api_key,
#         temperature=0.7,
#     )


# def build_context(text: str, formulas: list, images_meta: list, framework: str) -> str:
#     return f"""
# Paper Content:
# - Text: {text[:500]}
# - Formulas: {formulas[:2]}
# - Images: {[img.get('extracted_text') or 'Image provided as base64' for img in images_meta]}
# Generate a concise {framework} ML pipeline:
# 1. Data preparation
# 2. Model (CNN if images or 'image'/'cnn' in text; else MLP)
# 3. Training code with Adam optimizer and cross-entropy loss
# 4. Evaluation with accuracy
# 5. Example usage
# Use relu activation, CrossEntropyLoss unless formulas suggest otherwise.
# """


# async def scrape_url_content(url: str):
#     """Scrape URL text and images, with a fallback if crawl4ai/playwright is unavailable."""
#     if CRAWL4AI_AVAILABLE:
#         try:
#             async with AsyncWebCrawler() as crawler:
#                 try:
#                     from crawl4ai import CrawlerRunConfig, CacheMode
#                     run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
#                     result = await crawler.arun(url=url, config=run_config)
#                 except (ImportError, TypeError):
#                     result = await crawler.arun(url=url, bypass_cache=True)

#             text = (
#                 result.markdown
#                 if isinstance(result.markdown, str)
#                 else getattr(result.markdown, "raw_markdown", str(result.markdown))
#             )
#             images = getattr(result, "images", None)
#             if images is None:
#                 media = getattr(result, "media", None)
#                 if isinstance(media, dict):
#                     images = media.get("images", [])
#                 elif media is not None and hasattr(media, "images"):
#                     images = getattr(media, "images") or []
#                 else:
#                     images = []

#             normalized_images = []
#             for img in images:
#                 if isinstance(img, dict):
#                     normalized_images.append(img.get("src") or img.get("url"))
#                 elif isinstance(img, str):
#                     normalized_images.append(img)
#             return text, [src for src in normalized_images if src]
#         except Exception:
#             pass  # fall through to requests-based scraper

#     response = requests.get(url, timeout=15)
#     response.raise_for_status()
#     soup = BeautifulSoup(response.text, "html.parser")
#     text = soup.get_text(separator="\n", strip=True)
#     images = []
#     for img in soup.find_all("img"):
#         src = img.get("src")
#         if src:
#             images.append(urljoin(url, src))
#     return text, images


# def generate_code_with_crew(
#     framework: str,
#     llm_name: str,
#     api_key: str,
#     context: str,
#     text: str,
#     images: list,
#     formulas: list,
# ) -> str:
#     """
#     Run CrewAI agents to generate ML code from a research paper.
#     Falls back to a template if CrewAI is not installed or fails.

#     Key fix: a proper crewai.LLM object is built (not a bare string).
#     For Gemini / Google AI Studio this is essential — LiteLLM requires the
#     'gemini/' provider prefix and the api_key injected directly.
#     """
#     if not CREWAI_AVAILABLE:
#         return fallback_code(text, framework, images, formulas)

#     try:
#         crewai_llm = build_crewai_llm(llm_name, api_key)

#         scraper_agent = Agent(
#             role="Paper Scraper",
#             goal="Extract text, formulas, and images from a research paper",
#             backstory=(
#                 "You are an expert at parsing and extracting structured "
#                 "information from academic research papers."
#             ),
#             llm=crewai_llm,
#             verbose=True,
#         )
#         analyzer = Agent(
#             role="Content Analyzer",
#             goal="Identify ML algorithms, model architectures, and hyperparameters",
#             backstory=(
#                 "You are a machine learning researcher skilled at identifying "
#                 "model architectures and training strategies from paper descriptions."
#             ),
#             llm=crewai_llm,
#             verbose=True,
#         )
#         coder = Agent(
#             role="Code Generator",
#             goal=f"Generate complete, runnable {framework} ML code from a research paper",
#             backstory=(
#                 f"You are an expert {framework} developer who translates "
#                 "research paper algorithms into clean, working code."
#             ),
#             llm=crewai_llm,
#             verbose=True,
#         )

#         scrape_task = Task(
#             description="Summarize the key text, formulas, and image descriptions from the paper.",
#             agent=scraper_agent,
#             expected_output="A structured summary of text, formulas, and image descriptions.",
#         )
#         analyze_task = Task(
#             description=(
#                 "Analyze the paper content to identify the ML model architecture, "
#                 "loss functions, optimizers, and key hyperparameters."
#             ),
#             agent=analyzer,
#             expected_output=(
#                 "A list of model parameters: architecture type, optimizer, "
#                 "loss function, and key hyperparameters."
#             ),
#         )
#         code_task = Task(
#             description=(
#                 f"Generate complete {framework} ML code based on the following "
#                 f"context from the research paper:\n{context}"
#             ),
#             agent=coder,
#             expected_output=(
#                 f"Complete, runnable {framework} ML pipeline code including "
#                 "data preparation, model definition, training loop, and evaluation."
#             ),
#         )

#         crew = Crew(
#             agents=[scraper_agent, analyzer, coder],
#             tasks=[scrape_task, analyze_task, code_task],
#             process=Process.sequential,
#         )

#         # crew.kickoff() returns a CrewOutput object — convert to string
#         result = crew.kickoff()
#         code = str(result).strip()
#         if not code or "error" in code.lower():
#             code = fallback_code(text, framework, images, formulas)
#         return code

#     except Exception as e:
#         print(f"[CrewAI Error] {e}")
#         return fallback_code(text, framework, images, formulas)


# # ---------------------------------------------------------------------------
# # API endpoints
# # ---------------------------------------------------------------------------


# @app.post("/process_url", response_model=ProcessResponse)
# async def process_url(
#     url: str = Form(...),
#     framework: str = Form("framework"),
#     llm: str = Form("llm"),
#     api_key: str = Form(...),
# ):
#     """Process a research paper URL, extract text/formulas/images, and generate ML code."""
#     if not url:
#         raise HTTPException(status_code=400, detail="URL is required")

#     set_llm_api_key(llm, api_key)

#     try:
#         text, images = await scrape_url_content(url)
#         formulas = find_formulas(text)

#         images_with_text = []
#         for img_url in images:
#             if not img_url:
#                 continue
#             image_data = extract_text_from_image(img_url)
#             images_with_text.append(image_data)

#         context = build_context(text, formulas, images_with_text, framework)
#         code = generate_code_with_crew(framework, llm, api_key, context, text, images, formulas)

#         return ProcessResponse(
#             text=text,
#             formulas=formulas,
#             images_with_text=images_with_text,
#             image_analysis=images_with_text,
#             code=code,
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/process_pdf", response_model=ProcessResponse)
# async def process_pdf(
#     file: UploadFile = File(...),
#     framework: str = Form("framework"),
#     llm: str = Form("llm"),
#     api_key: str = Form(...),
# ):
#     """Process a PDF research paper and generate ML code."""
#     if not api_key:
#         raise HTTPException(status_code=400, detail="API key is required")

#     set_llm_api_key(llm, api_key)

#     try:
#         pdf_bytes = await file.read()
#         text = PDFReadTool()._run(file_path=io.BytesIO(pdf_bytes))

#         images = []
#         try:
#             images = convert_from_bytes(pdf_bytes, fmt="png")
#         except Exception:
#             images = []

#         formulas = re.findall(
#             r'\$\$([^$]+)\$\$|\$([^$]+)\$|\\begin\{equation\}(.*?)\\end\{equation\}',
#             text,
#             re.DOTALL,
#         )
#         formulas = [f for group in formulas for f in group if f]

#         reader = get_reader()
#         images_with_text = []
#         for img in images:
#             try:
#                 buffer = io.BytesIO()
#                 img.save(buffer, format="PNG")
#                 base64_image = base64.b64encode(buffer.getvalue()).decode()
#                 if reader is not None:
#                     ocr_result = reader.readtext(np.array(img), detail=0, paragraph=True)
#                     extracted_text = "\n".join(ocr_result).strip()
#                 else:
#                     extracted_text = None
#                 images_with_text.append({
#                     "image": base64_image,
#                     "extracted_text": extracted_text,
#                     "size": img.size,
#                     "format": img.format or "PNG",
#                 })
#             except Exception:
#                 images_with_text.append({
#                     "image": None,
#                     "extracted_text": None,
#                     "error": "OCR failed for this image",
#                 })

#         context = build_context(text, formulas, images_with_text, framework)
#         code = generate_code_with_crew(framework, llm, api_key, context, text, images, formulas)

#         return ProcessResponse(
#             text=text,
#             formulas=formulas,
#             images_with_text=images_with_text,
#             image_analysis=images_with_text,
#             code=code,
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.get("/health")
# async def health_check():
#     """Health check endpoint."""
#     return {"status": "healthy"}


# @app.get("/")
# async def root():
#     """Root endpoint with API information."""
#     return {
#         "name": "Paper Code Generator API",
#         "version": "1.0.0",
#         "endpoints": {
#             "process_url": "POST /process_url - Process URL and generate ML code",
#             "process_pdf": "POST /process_pdf - Process PDF and generate ML code",
#             "health": "GET /health - Health check",
#         },
#         "supported_llms": list(LLM_ENV_MAP.keys()),
#         "supported_frameworks": ["PyTorch", "TensorFlow"],
#     }


# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8001)


















































# import os
# import re
# import io
# import base64
# import asyncio
# import logging
# from typing import List, Dict, Optional
# import httpx
# import trafilatura
# from bs4 import BeautifulSoup
# from urllib.parse import urljoin


# import numpy as np
# import requests
# from pdf2image import convert_from_bytes
# from fastapi import FastAPI, HTTPException, UploadFile, File, Form
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from urllib.parse import urljoin
# from bs4 import BeautifulSoup
# import uvicorn
# from PyPDF2 import PdfReader

# from utils.fall_back_code import fallback_code
# from utils.find_formulas import find_formulas
# from utils.extract_text_from_image import extract_text_from_image

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger("paper_code_generator")

# # ---------------------------------------------------------------------------
# # Optional dependencies (gracefully degrade if not installed)
# # ---------------------------------------------------------------------------

# try:
#     from crawl4ai import AsyncWebCrawler
#     CRAWL4AI_AVAILABLE = True
# except ImportError:
#     AsyncWebCrawler = None
#     CRAWL4AI_AVAILABLE = False

# try:
#     from agno.agent import Agent
#     from agno.models.anthropic import Claude
#     from agno.models.openai import OpenAIChat
#     from agno.models.google import Gemini
#     from agno.models.xai import xAI
#     AGNO_AVAILABLE = True
# except ImportError:
#     Agent = Claude = OpenAIChat = Gemini = xAI = None
#     AGNO_AVAILABLE = False

# # ---------------------------------------------------------------------------
# # FastAPI app
# # ---------------------------------------------------------------------------

# app = FastAPI(title="Paper Code Generator API", version="2.0.0")

# _ALLOW_ALL = os.getenv("FASTAPI_ALLOW_ALL_ORIGINS", "true").lower() in {"true", "1", "yes"}
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"] if _ALLOW_ALL else [
#         "http://localhost:5173",
#         "http://localhost:8000",
#         "http://localhost:3000",
#         "http://127.0.0.1:5173",
#         "http://127.0.0.1:3000",
#         "http://localhost:8001",
#         "http://127.0.0.1:8001",
#     ],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # ---------------------------------------------------------------------------
# # Lazy OCR reader (avoids blocking startup if no GPU)
# # ---------------------------------------------------------------------------

# _reader = None


# def get_reader():
#     global _reader
#     if _reader is None:
#         try:
#             import easyocr
#             _reader = easyocr.Reader(['en'])
#         except Exception:
#             _reader = None
#     return _reader


# # ---------------------------------------------------------------------------
# # LLM configuration — Agno model ids per provider. Agno's Agent/Team classes
# # take the api_key directly per-call (no process-wide env var mutation).
# # ---------------------------------------------------------------------------

# LLM_MODEL_ID_MAP = {
#     "grok": "grok-4",
#     "openai": "gpt-4o",
#     "anthropic": "claude-sonnet-4-6",
#     "gemini": "gemini-3.6-flash",
# }


# def build_agno_model(llm_name: str, api_key: str):
#     """Build the right Agno model wrapper for the requested provider."""
#     normalized = llm_name.strip().lower()
#     model_id = LLM_MODEL_ID_MAP.get(normalized, normalized)
#     if normalized == "anthropic":
#         return Claude(id=model_id, api_key=api_key)
#     if normalized == "gemini":
#         return Gemini(id=model_id, api_key=api_key)
#     if normalized == "grok":
#         return xAI(id=model_id, api_key=api_key)
#     # default / "openai"
#     return OpenAIChat(id=model_id, api_key=api_key)


# SCRAPER_INSTRUCTIONS = """You are an expert at parsing and extracting \
# structured information from academic research papers. Given raw text, \
# formulas, and image descriptions extracted from a paper, produce a \
# structured summary of the key text, formulas, and image descriptions — \
# the essential content someone would need to reimplement the paper's model. \
# Output the summary only, no commentary."""

# ANALYZER_INSTRUCTIONS = """You are a machine learning researcher skilled at \
# identifying model architectures and training strategies from paper \
# descriptions. Given a structured summary of a research paper, identify:
# - The model architecture (e.g. CNN, MLP, Transformer)
# - The loss function and optimizer
# - Key hyperparameters (learning rate, batch size, layers, etc.)
# Output a short, structured list of these parameters only — no code."""

# CODER_INSTRUCTIONS = """You are an expert ML developer who translates \
# research paper algorithms into clean, working code. Given a structured list \
# of a paper's model architecture, loss function, optimizer, and \
# hyperparameters, write a complete, runnable ML pipeline in the requested \
# framework: data preparation, model definition, training loop, evaluation, \
# and example usage. Return ONLY the code, no explanations, no markdown code \
# fences."""


# class PDFReadTool:
#     """Extracts text from a PDF file."""

#     @staticmethod
#     def run(file_path) -> str:
#         try:
#             reader = PdfReader(file_path)
#             text = ""
#             for page in reader.pages:
#                 text += page.extract_text() or ""
#             return text
#         except Exception as e:
#             raise ValueError(f"Error reading PDF: {e}")


# class ProcessResponse(BaseModel):
#     text: str
#     formulas: List[str]
#     images_with_text: List[Dict]
#     image_analysis: Optional[List[Dict]] = None
#     code: str


# # ---------------------------------------------------------------------------
# # Helper functions
# # ---------------------------------------------------------------------------


# def validate_llm_choice(llm: str) -> str:
#     normalized = llm.strip().lower()
#     if normalized not in LLM_MODEL_ID_MAP:
#         raise HTTPException(
#             status_code=400,
#             detail=f"Unsupported llm '{llm}'. Must be one of {list(LLM_MODEL_ID_MAP.keys())}",
#         )
#     return normalized


# def build_context(text: str, formulas: list, images_meta: list, framework: str) -> str:
#     return f"""
# Paper Content:
# - Text: {text[:2000]}
# - Formulas: {formulas[:5]}
# - Images: {[img.get('extracted_text') or 'Image provided as base64' for img in images_meta][:5]}

# Generate a concise {framework} ML pipeline:
# 1. Data preparation
# 2. Model (CNN if images or 'image'/'cnn' in text; else MLP)
# 3. Training code with Adam optimizer and cross-entropy loss
# 4. Evaluation with accuracy
# 5. Example usage
# Use relu activation, CrossEntropyLoss unless formulas suggest otherwise.
#  and output what found in a structured way, with no commentary or markdown code fences.
#  and give formulas that has been used to build the model, and give the code in a structured way, with no commentary or markdown code fences.
# """


# def strip_code_fences(code: str) -> str:
#     code = code.strip()
#     code = re.sub(r"^```[a-zA-Z]*\n", "", code)
#     code = re.sub(r"\n```$", "", code)
#     return code.strip()


# async def scrape_url_content(url: str):
#     """Scrape URL text and images, with a fallback if crawl4ai/playwright is unavailable."""
#     if CRAWL4AI_AVAILABLE:
#         try:
#             async with AsyncWebCrawler() as crawler:
#                 try:
#                     from crawl4ai import CrawlerRunConfig, CacheMode
#                     run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
#                     result = await crawler.arun(url=url, config=run_config)
#                 except (ImportError, TypeError):
#                     result = await crawler.arun(url=url, bypass_cache=True)

#             text = (
#                 result.markdown
#                 if isinstance(result.markdown, str)
#                 else getattr(result.markdown, "raw_markdown", str(result.markdown))
#             )
#             images = getattr(result, "images", None)
#             if images is None:
#                 media = getattr(result, "media", None)
#                 if isinstance(media, dict):
#                     images = media.get("images", [])
#                 elif media is not None and hasattr(media, "images"):
#                     images = getattr(media, "images") or []
#                 else:
#                     images = []

#             normalized_images = []
#             for img in images:
#                 if isinstance(img, dict):
#                     normalized_images.append(img.get("src") or img.get("url"))
#                 elif isinstance(img, str):
#                     normalized_images.append(img)
#             return text, [src for src in normalized_images if src]
#         except Exception as e:
#             logger.warning(f"crawl4ai failed, falling back to requests: {e}")

#     # Blocking network call moved off the event loop.
#     def _fetch():
#         response = requests.get(url, timeout=15)
#         response.raise_for_status()
#         soup = BeautifulSoup(response.text, "html.parser")
#         text = soup.get_text(separator="\n", strip=True)
#         images = []
#         for img in soup.find_all("img"):
#             src = img.get("src")
#             if src:
#                 images.append(urljoin(url, src))
#         return text, images

#     return await asyncio.to_thread(_fetch)


# async def generate_code_with_agno(
#     framework: str,
#     llm_name: str,
#     api_key: str,
#     context: str,
#     text: str,
#     images: list,
#     formulas: list,
# ) -> str:
#     """
#     Generate ML code via a deterministic 3-agent pipeline built on Agno,
#     mirroring the original CrewAI structure 1:1:

#         Scraper Agent  -> Analyzer Agent -> Coder Agent

#     Each agent's output is fed as the next agent's input explicitly (plain
#     sequential .arun() calls), the same hand-off CrewAI's
#     Process.sequential gave you — but without leaving agent-to-agent
#     routing up to an LLM "team leader" the way Team(mode="coordinate")
#     does. Ordering is guaranteed every run.

#     Agno agents are cheap to construct (microseconds, no network call at
#     init) so building three per-request has negligible overhead. The API
#     key is passed directly into the model wrapper per call, so concurrent
#     requests for different users/providers never collide.
#     """
#     if not AGNO_AVAILABLE:
#         return fallback_code(text, framework, images, formulas)

#     try:
#         model = build_agno_model(llm_name, api_key)

#         scraper_agent = Agent(
#             name="Paper Scraper",
#             role="Extract text, formulas, and images from a research paper",
#             model=model,
#             instructions=SCRAPER_INSTRUCTIONS,
#         )
#         analyzer = Agent(
#             name="Content Analyzer",
#             role="Identify ML algorithms, model architectures, and hyperparameters",
#             model=model,
#             instructions=ANALYZER_INSTRUCTIONS,
#         )
#         coder = Agent(
#             name="Code Generator",
#             role=f"Generate complete, runnable {framework} ML code from a research paper",
#             model=model,
#             instructions=CODER_INSTRUCTIONS,
#         )

#         # Step 1: Scraper condenses the raw extracted content.
#         scrape_response = await scraper_agent.arun(context)
#         scraped_summary = getattr(scrape_response, "content", None) or str(scrape_response)

#         # Step 2: Analyzer identifies architecture/loss/optimizer/hyperparams.
#         analyze_response = await analyzer.arun(scraped_summary)
#         analysis = getattr(analyze_response, "content", None) or str(analyze_response)

#         # Step 3: Coder writes the final pipeline from the analysis.
#         code_prompt = (
#             f"Framework: {framework}\n\n"
#             f"Model parameters identified from the paper:\n{analysis}\n\n"
#             f"Original paper context for reference:\n{context}"
#         )
#         code_response = await coder.arun(code_prompt)
#         code = getattr(code_response, "content", None) or str(code_response)
#         code = strip_code_fences(code)

#         if not code or "error" in code.lower()[:200]:
#             return fallback_code(text, framework, images, formulas)
#         return code
#     except Exception as e:
#         logger.warning(f"[Agno Error] {e}")
#         return fallback_code(text, framework, images, formulas)


# async def process_image_for_ocr(img) -> Dict:
#     """Encode + OCR a single PIL image off the event loop."""
#     def _process():
#         try:
#             buffer = io.BytesIO()
#             img.save(buffer, format="PNG")
#             base64_image = base64.b64encode(buffer.getvalue()).decode()
#             reader = get_reader()
#             if reader is not None:
#                 ocr_result = reader.readtext(np.array(img), detail=0, paragraph=True)
#                 extracted_text = "\n".join(ocr_result).strip()
#             else:
#                 extracted_text = None
#             return {
#                 "image": base64_image,
#                 "extracted_text": extracted_text,
#                 "size": img.size,
#                 "format": img.format or "PNG",
#             }
#         except Exception:
#             return {
#                 "image": None,
#                 "extracted_text": None,
#                 "error": "OCR failed for this image",
#             }

#     return await asyncio.to_thread(_process)


# # ---------------------------------------------------------------------------
# # API endpoints
# # ---------------------------------------------------------------------------

# @app.post("/process_url", response_model=ProcessResponse)
# async def process_url(
#     url: str = Form(...),
#     framework: str = Form("PyTorch"),
#     llm: str = Form("openai"),
#     api_key: str = Form(...)
# ):
#     """
#     Lightweight, fast URL scraper tailored for academic papers and articles.
#     Extracts text, formulas, image metadata, and generates an ML pipeline.
#     """
#     llm_choice = validate_llm_choice(llm)

#     headers = {
#         "User-Agent": (
#             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#             "AppleWebKit/537.36 (KHTML, like Gecko) "
#             "Chrome/122.0.0.0 Safari/537.36"
#         )
#     }

#     # 1. Fetch URL content using httpx
#     async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
#         try:
#             response = await client.get(url)
#             response.raise_for_status()
#             html = response.text
#         except Exception as e:
#             logger.error(f"Failed to fetch URL {url}: {e}")
#             raise HTTPException(status_code=400, detail=f"Failed to fetch content from URL: {str(e)}")

#     # 2. Trafilatura strips web clutter and preserves main paper text as Markdown
#     extracted_text = trafilatura.extract(
#         html,
#         include_tables=True,
#         include_links=False,
#         output_format="markdown"
#     ) or ""

#     # 3. Parse image URLs directly from HTML
#     soup = BeautifulSoup(html, "html.parser")
#     images = []
#     for img in soup.find_all("img"):
#         src = img.get("src")
#         if src and not src.startswith("data:"):
#             images.append(urljoin(url, src))

#     try:
#         # 4. Extract mathematical formulas from text
#         formulas = find_formulas(extracted_text)

#         # 5. OCR/process extracted image URLs concurrently
#         images_with_text = await asyncio.gather(
#             *[asyncio.to_thread(extract_text_from_image, img_url) for img_url in images if img_url]
#         )
#         images_with_text = list(images_with_text)

#         # 6. Generate ML pipeline code using Agno agents
#         context = build_context(extracted_text, formulas, images_with_text, framework)
#         code = await generate_code_with_agno(
#             framework, llm_choice, api_key, context, extracted_text, images_with_text, formulas
#         )

#         # 7. Return a valid ProcessResponse matching the response_model schema
#         return ProcessResponse(
#             text=extracted_text,
#             formulas=formulas,
#             images_with_text=images_with_text,
#             image_analysis=images_with_text,
#             code=code,
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# # @app.post("/process_url", response_model=ProcessResponse)
# # async def process_url( url: str = Form(...),
# #     framework: str = Form("framework"),
# #     llm: str = Form("llm"),
# #     api_key: str = Form(...)):
# #     """
# #     Lightweight, fast URL scraper tailored for academic papers and articles.
# #     Does not require Playwright or Chromium binaries.
# #     """
# #     headers = {
# #         "User-Agent": (
# #             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
# #             "AppleWebKit/537.36 (KHTML, like Gecko) "
# #             "Chrome/122.0.0.0 Safari/537.36"
# #         )
# #     }

# #     async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
# #         try:
# #             response = await client.get(url)
# #             response.raise_for_status()
# #             html = response.text
# #         except Exception as e:
# #             logger.error(f"Failed to fetch URL {url}: {e}")
# #             raise HTTPException(status_code=400, detail=f"Failed to fetch content from URL: {str(e)}")

# #     # Trafilatura strips navigation bars, footers, and ads, preserving paper content/text
# #     extracted_text = trafilatura.extract(
# #         html,
# #         include_tables=True,
# #         include_links=False,
# #         output_format="markdown"
# #     ) or ""

# #     # Parse images directly from HTML
# #     soup = BeautifulSoup(html, "html.parser")
# #     images = []
# #     for img in soup.find_all("img"):
# #         src = img.get("src")
# #         if src and not src.startswith("data:"):
# #             images.append(urljoin(url, src))

# #     return extracted_text, images


# # async def process_url(
# #     url: str = Form(...),
# #     framework: str = Form("framework"),
# #     llm: str = Form("llm"),
# #     api_key: str = Form(...),
# # ):
# #     """Process a research paper URL, extract text/formulas/images, and generate ML code."""
# #     if not url:
# #         raise HTTPException(status_code=400, detail="URL is required")

# #     llm = validate_llm_choice(llm)

# #     try:
# #         text, images = await scrape_url_content(url)
# #         formulas = find_formulas(text)

# #         # Image text extraction runs concurrently instead of one-by-one.
# #         images_with_text = await asyncio.gather(
# #             *[asyncio.to_thread(extract_text_from_image, img_url) for img_url in images if img_url]
# #         )
# #         images_with_text = list(images_with_text)

# #         context = build_context(text, formulas, images_with_text, framework)
# #         code = await generate_code_with_agno(framework, llm, api_key, context, text, images, formulas)

# #         return ProcessResponse(
# #             text=text,
# #             formulas=formulas,
# #             images_with_text=images_with_text,
# #             image_analysis=images_with_text,
# #             code=code,
# #         )
# #     except HTTPException:
# #         raise
# #     except Exception as e:
# #         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/process_pdf", response_model=ProcessResponse)
# async def process_pdf(
#     file: UploadFile = File(...),
#     framework: str = Form("framework"),
#     llm: str = Form("llm"),
#     api_key: str = Form(...),
# ):
#     """Process a PDF research paper and generate ML code."""
#     if not api_key:
#         raise HTTPException(status_code=400, detail="API key is required")

#     llm = validate_llm_choice(llm)

#     try:
#         pdf_bytes = await file.read()

#         # Blocking PDF parsing/rasterization moved off the event loop.
#         text = await asyncio.to_thread(PDFReadTool.run, io.BytesIO(pdf_bytes))

#         try:
#             images = await asyncio.to_thread(convert_from_bytes, pdf_bytes, fmt="png")
#         except Exception:
#             images = []

#         formulas = re.findall(
#             r'\$\$([^$]+)\$\$|\$([^$]+)\$|\\begin\{equation\}(.*?)\\end\{equation\}',
#             text,
#             re.DOTALL,
#         )
#         formulas = [f for group in formulas for f in group if f]

#         # OCR each image concurrently instead of sequentially.
#         images_with_text = await asyncio.gather(
#             *[process_image_for_ocr(img) for img in images]
#         )
#         images_with_text = list(images_with_text)

#         context = build_context(text, formulas, images_with_text, framework)
#         code = await generate_code_with_agno(framework, llm, api_key, context, text, images, formulas)

#         return ProcessResponse(
#             text=text,
#             formulas=formulas,
#             images_with_text=images_with_text,
#             image_analysis=images_with_text,
#             code=code,
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.get("/health")
# async def health_check():
#     """Health check endpoint."""
#     return {"status": "healthy"}


# @app.get("/")
# async def root():
#     """Root endpoint with API information."""
#     return {
#         "name": "Paper Code Generator API",
#         "version": "2.0.0",
#         "endpoints": {
#             "process_url": "POST /process_url - Process URL and generate ML code",
#             "process_pdf": "POST /process_pdf - Process PDF and generate ML code",
#             "health": "GET /health - Health check",
#         },
#         "supported_llms": list(LLM_MODEL_ID_MAP.keys()),
#         "supported_frameworks": ["PyTorch", "TensorFlow"],
#     }


# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8001)









import os
import re
import io
import base64
import asyncio
import logging
from typing import List, Dict, Optional
import httpx
import trafilatura
from bs4 import BeautifulSoup
from urllib.parse import urljoin


import numpy as np
import requests
from pdf2image import convert_from_bytes
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import uvicorn
from PyPDF2 import PdfReader
from dotenv import load_dotenv

from utils.fall_back_code import fallback_code
from utils.find_formulas import find_formulas
from utils.extract_text_from_image import extract_text_from_image

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("paper_code_generator")

# ---------------------------------------------------------------------------
# Optional dependencies (gracefully degrade if not installed)
# ---------------------------------------------------------------------------

try:
    from crawl4ai import AsyncWebCrawler
    CRAWL4AI_AVAILABLE = True
except ImportError:
    AsyncWebCrawler = None
    CRAWL4AI_AVAILABLE = False

try:
    from agno.agent import Agent
    from agno.models.anthropic import Claude
    from agno.models.openai import OpenAIChat
    from agno.models.google import Gemini
    from agno.models.xai import xAI
    from agno.models.openrouter import OpenRouter
    AGNO_AVAILABLE = True
except ImportError:
    Agent = Claude = OpenAIChat = Gemini = xAI = OpenRouter = None
    AGNO_AVAILABLE = False

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Paper Code Generator API", version="2.0.0")

_ALLOW_ALL = os.getenv("FASTAPI_ALLOW_ALL_ORIGINS", "true").lower() in {"true", "1", "yes"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _ALLOW_ALL else [
        "http://localhost:5173",
        "http://localhost:8000",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Lazy OCR reader (avoids blocking startup if no GPU)
# ---------------------------------------------------------------------------

_reader = None


def get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(['en'])
        except Exception:
            _reader = None
    return _reader


# ---------------------------------------------------------------------------
# LLM configuration — Agno model ids per provider. Agno's Agent/Team classes
# take the api_key directly per-call (no process-wide env var mutation).
#
# "openrouter" is the default provider, routed to NVIDIA's Nemotron 3 Ultra
# model (a 550B-param / 55B-active MoE reasoning model) via OpenRouter's
# unified API.
# ---------------------------------------------------------------------------

DEFAULT_LLM = "openrouter"

LLM_MODEL_ID_MAP = {
    "openrouter": "nvidia/nemotron-3-ultra-550b-a55b",
    "grok": "grok-4",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-3.6-flash",
}


def build_agno_model(llm_name: str, api_key: str):
    """Build the right Agno model wrapper for the requested provider."""
    normalized = llm_name.strip().lower()
    model_id = LLM_MODEL_ID_MAP.get(normalized, normalized)
    if normalized == "anthropic":
        return Claude(id=model_id, api_key=api_key)
    if normalized == "gemini":
        return Gemini(id=model_id, api_key=api_key)
    if normalized == "grok":
        return xAI(id=model_id, api_key=api_key)
    if normalized == "openrouter":
        return OpenRouter(id=model_id, api_key=api_key)
    # default / "openai"
    return OpenAIChat(id=model_id, api_key=api_key)


SCRAPER_INSTRUCTIONS = """You are an expert at parsing and extracting \
structured information from academic research papers. Given raw text, \
formulas, and image descriptions extracted from a paper, produce a \
structured summary of the key text, formulas, and image descriptions — \
the essential content someone would need to reimplement the paper's model. \
Output the summary only, no commentary."""

ANALYZER_INSTRUCTIONS = """You are a machine learning researcher skilled at \
identifying model architectures and training strategies from paper \
descriptions. Given a structured summary of a research paper, identify:
- The model architecture (e.g. CNN, MLP, Transformer)
- The loss function and optimizer
- Key hyperparameters (learning rate, batch size, layers, etc.)
Output a short, structured list of these parameters only — no code."""

CODER_INSTRUCTIONS = """You are an expert ML developer who translates \
research paper algorithms into clean, working code. Given a structured list \
of a paper's model architecture, loss function, optimizer, and \
hyperparameters, write a complete, runnable ML pipeline in the requested \
framework: data preparation, model definition, training loop, evaluation, \
and example usage. Return ONLY the code, no explanations, no markdown code \
fences."""


class PDFReadTool:
    """Extracts text from a PDF file."""

    @staticmethod
    def run(file_path) -> str:
        try:
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        except Exception as e:
            raise ValueError(f"Error reading PDF: {e}")


class ProcessResponse(BaseModel):
    text: str
    formulas: List[str]
    images_with_text: List[Dict]
    image_analysis: Optional[List[Dict]] = None
    code: str


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def validate_llm_choice(llm: str) -> str:
    normalized = llm.strip().lower()
    if normalized not in LLM_MODEL_ID_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported llm '{llm}'. Must be one of {list(LLM_MODEL_ID_MAP.keys())}",
        )
    return normalized


def resolve_api_key(llm: str, api_key: str) -> str:
    """Use a request key when provided, otherwise use the server key for OpenRouter."""
    if api_key and api_key.strip():
        return api_key.strip()

    if llm == "openrouter":
        server_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if server_key:
            return server_key

    raise HTTPException(
        status_code=400,
        detail=f"API key is required for {llm}. Add it in the app or configure the server key.",
    )


def build_context(text: str, formulas: list, images_meta: list, framework: str) -> str:
    return f"""
Paper Content:
- Text: {text[:2000]}
- Formulas: {formulas[:5]}
- Images: {[img.get('extracted_text') or 'Image provided as base64' for img in images_meta][:5]}

Generate a concise {framework} ML pipeline:
1. Data preparation
2. Model (CNN if images or 'image'/'cnn' in text; else MLP)
3. Training code with Adam optimizer and cross-entropy loss
4. Evaluation with accuracy
5. Example usage
Use relu activation, CrossEntropyLoss unless formulas suggest otherwise.
 and output what found in a structured way, with no commentary or markdown code fences.
 and give formulas that has been used to build the model, and give the code in a structured way, with no commentary or markdown code fences.
"""


def strip_code_fences(code: str) -> str:
    code = code.strip()
    code = re.sub(r"^```[a-zA-Z]*\n", "", code)
    code = re.sub(r"\n```$", "", code)
    return code.strip()


async def scrape_url_content(url: str):
    """Scrape URL text and images, with a fallback if crawl4ai/playwright is unavailable."""
    if CRAWL4AI_AVAILABLE:
        try:
            async with AsyncWebCrawler() as crawler:
                try:
                    from crawl4ai import CrawlerRunConfig, CacheMode
                    run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
                    result = await crawler.arun(url=url, config=run_config)
                except (ImportError, TypeError):
                    result = await crawler.arun(url=url, bypass_cache=True)

            text = (
                result.markdown
                if isinstance(result.markdown, str)
                else getattr(result.markdown, "raw_markdown", str(result.markdown))
            )
            images = getattr(result, "images", None)
            if images is None:
                media = getattr(result, "media", None)
                if isinstance(media, dict):
                    images = media.get("images", [])
                elif media is not None and hasattr(media, "images"):
                    images = getattr(media, "images") or []
                else:
                    images = []

            normalized_images = []
            for img in images:
                if isinstance(img, dict):
                    normalized_images.append(img.get("src") or img.get("url"))
                elif isinstance(img, str):
                    normalized_images.append(img)
            return text, [src for src in normalized_images if src]
        except Exception as e:
            logger.warning(f"crawl4ai failed, falling back to requests: {e}")

    # Blocking network call moved off the event loop.
    def _fetch():
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                images.append(urljoin(url, src))
        return text, images

    return await asyncio.to_thread(_fetch)


async def generate_code_with_agno(
    framework: str,
    llm_name: str,
    api_key: str,
    context: str,
    text: str,
    images: list,
    formulas: list,
) -> str:
    """
    Generate ML code via a deterministic 3-agent pipeline built on Agno,
    mirroring the original CrewAI structure 1:1:

        Scraper Agent  -> Analyzer Agent -> Coder Agent

    Each agent's output is fed as the next agent's input explicitly (plain
    sequential .arun() calls), the same hand-off CrewAI's
    Process.sequential gave you — but without leaving agent-to-agent
    routing up to an LLM "team leader" the way Team(mode="coordinate")
    does. Ordering is guaranteed every run.

    Agno agents are cheap to construct (microseconds, no network call at
    init) so building three per-request has negligible overhead. The API
    key is passed directly into the model wrapper per call, so concurrent
    requests for different users/providers never collide.
    """
    if not AGNO_AVAILABLE:
        return fallback_code(text, framework, images, formulas)

    try:
        model = build_agno_model(llm_name, api_key)

        scraper_agent = Agent(
            name="Paper Scraper",
            role="Extract text, formulas, and images from a research paper",
            model=model,
            instructions=SCRAPER_INSTRUCTIONS,
        )
        analyzer = Agent(
            name="Content Analyzer",
            role="Identify ML algorithms, model architectures, and hyperparameters",
            model=model,
            instructions=ANALYZER_INSTRUCTIONS,
        )
        coder = Agent(
            name="Code Generator",
            role=f"Generate complete, runnable {framework} ML code from a research paper",
            model=model,
            instructions=CODER_INSTRUCTIONS,
        )

        # Step 1: Scraper condenses the raw extracted content.
        scrape_response = await scraper_agent.arun(context)
        scraped_summary = getattr(scrape_response, "content", None) or str(scrape_response)

        # Step 2: Analyzer identifies architecture/loss/optimizer/hyperparams.
        analyze_response = await analyzer.arun(scraped_summary)
        analysis = getattr(analyze_response, "content", None) or str(analyze_response)

        # Step 3: Coder writes the final pipeline from the analysis.
        code_prompt = (
            f"Framework: {framework}\n\n"
            f"Model parameters identified from the paper:\n{analysis}\n\n"
            f"Original paper context for reference:\n{context}"
        )
        code_response = await coder.arun(code_prompt)
        code = getattr(code_response, "content", None) or str(code_response)
        code = strip_code_fences(code)

        if not code or "error" in code.lower()[:200]:
            return fallback_code(text, framework, images, formulas)
        return code
    except Exception as e:
        logger.warning(f"[Agno Error] {e}")
        return fallback_code(text, framework, images, formulas)


async def process_image_for_ocr(img) -> Dict:
    """Encode + OCR a single PIL image off the event loop."""
    def _process():
        try:
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            base64_image = base64.b64encode(buffer.getvalue()).decode()
            reader = get_reader()
            if reader is not None:
                ocr_result = reader.readtext(np.array(img), detail=0, paragraph=True)
                extracted_text = "\n".join(ocr_result).strip()
            else:
                extracted_text = None
            return {
                "image": base64_image,
                "extracted_text": extracted_text,
                "size": img.size,
                "format": img.format or "PNG",
            }
        except Exception:
            return {
                "image": None,
                "extracted_text": None,
                "error": "OCR failed for this image",
            }

    return await asyncio.to_thread(_process)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.post("/process_url", response_model=ProcessResponse)
async def process_url(
    url: str = Form(...),
    framework: str = Form("PyTorch"),
    llm: str = Form(DEFAULT_LLM),
    api_key: str = Form("")
):
    """
    Lightweight, fast URL scraper tailored for academic papers and articles.
    Extracts text, formulas, image metadata, and generates an ML pipeline.
    """
    llm_choice = validate_llm_choice(llm)
    api_key = resolve_api_key(llm_choice, api_key)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }

    # 1. Fetch URL content using httpx
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
        except Exception as e:
            logger.error(f"Failed to fetch URL {url}: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to fetch content from URL: {str(e)}")

    # 2. Trafilatura strips web clutter and preserves main paper text as Markdown
    extracted_text = trafilatura.extract(
        html,
        include_tables=True,
        include_links=False,
        output_format="markdown"
    ) or ""

    # 3. Parse image URLs directly from HTML
    soup = BeautifulSoup(html, "html.parser")
    images = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and not src.startswith("data:"):
            images.append(urljoin(url, src))

    try:
        # 4. Extract mathematical formulas from text
        formulas = find_formulas(extracted_text)

        # 5. OCR/process extracted image URLs concurrently
        images_with_text = await asyncio.gather(
            *[asyncio.to_thread(extract_text_from_image, img_url) for img_url in images if img_url]
        )
        images_with_text = list(images_with_text)

        # 6. Generate ML pipeline code using Agno agents
        context = build_context(extracted_text, formulas, images_with_text, framework)
        code = await generate_code_with_agno(
            framework, llm_choice, api_key, context, extracted_text, images_with_text, formulas
        )

        # 7. Return a valid ProcessResponse matching the response_model schema
        return ProcessResponse(
            text=extracted_text,
            formulas=formulas,
            images_with_text=images_with_text,
            image_analysis=images_with_text,
            code=code,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process_pdf", response_model=ProcessResponse)
async def process_pdf(
    file: UploadFile = File(...),
    framework: str = Form("PyTorch"),
    llm: str = Form(DEFAULT_LLM),
    api_key: str = Form(""),
):
    """Process a PDF research paper and generate ML code."""
    llm = validate_llm_choice(llm)
    api_key = resolve_api_key(llm, api_key)

    try:
        pdf_bytes = await file.read()

        # Blocking PDF parsing/rasterization moved off the event loop.
        text = await asyncio.to_thread(PDFReadTool.run, io.BytesIO(pdf_bytes))

        try:
            images = await asyncio.to_thread(convert_from_bytes, pdf_bytes, fmt="png")
        except Exception:
            images = []

        formulas = re.findall(
            r'\$\$([^$]+)\$\$|\$([^$]+)\$|\\begin\{equation\}(.*?)\\end\{equation\}',
            text,
            re.DOTALL,
        )
        formulas = [f for group in formulas for f in group if f]

        # OCR each image concurrently instead of sequentially.
        images_with_text = await asyncio.gather(
            *[process_image_for_ocr(img) for img in images]
        )
        images_with_text = list(images_with_text)

        context = build_context(text, formulas, images_with_text, framework)
        code = await generate_code_with_agno(framework, llm, api_key, context, text, images, formulas)

        return ProcessResponse(
            text=text,
            formulas=formulas,
            images_with_text=images_with_text,
            image_analysis=images_with_text,
            code=code,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Paper Code Generator API",
        "version": "2.0.0",
        "endpoints": {
            "process_url": "POST /process_url - Process URL and generate ML code",
            "process_pdf": "POST /process_pdf - Process PDF and generate ML code",
            "health": "GET /health - Health check",
        },
        "supported_llms": list(LLM_MODEL_ID_MAP.keys()),
        "default_llm": DEFAULT_LLM,
        "supported_frameworks": ["PyTorch", "TensorFlow"],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
    