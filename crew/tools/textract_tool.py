"""Tool to extract text from identity documents stored in S3 via AWS Textract."""
import json
import logging
import os
import time
import urllib.request
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_MAX_DOCUMENT_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
_POLL_MAX_RETRIES = 50
_POLL_SLEEP_SECONDS = 3
# After this many polls without SUCCEEDED, fall back to mock if USE_TEXTRACT_MOCK is enabled
_POLL_MOCK_FALLBACK = 15


class _TextractMockFallback(Exception):
    """Raised by _extract_pdf_async to signal the caller should use the mock endpoint."""
    pass


class ExtractDocumentTextInput(BaseModel):
    s3_bucket: str = Field(description="S3 bucket where the document is stored")
    s3_key: str = Field(description="S3 key (path) of the document to extract text from")
    document_type: str = Field(default="", description="Optional document type label (e.g. 'paspoort', 'rijbewijs', 'identiteitskaart')")
    full_name: str = Field(default="", description="Full name of the person from identity.fullName (used as lookup key for mock fallback)")


class ExtractDocumentTextTool(BaseTool):
    """Extract text from an identity document stored in S3 using AWS Textract."""

    name: str = "extract_document_text"
    description: str = (
        "Extracts text from an identity document (PDF or image) stored in S3 using AWS Textract. "
        "Returns structured JSON with pages and full text. "
        "For PDFs uses async detection; for images (jpg/jpeg/png) uses sync detection. "
        "Pass s3_bucket and s3_key from the get_case_files output."
    )
    args_schema: Type[ExtractDocumentTextInput] = ExtractDocumentTextInput

    def _run(self, s3_bucket: str, s3_key: str, document_type: str = "", full_name: str = "") -> str:
        """Extract text from a document in S3 using AWS Textract."""
        logger.info(
            "extract_document_text input: s3_bucket=%s, s3_key=%s, document_type=%s",
            s3_bucket, s3_key, document_type,
        )
        if not s3_bucket:
            return json.dumps({"error": "s3_bucket is required"})
        if not s3_key:
            return json.dumps({"error": "s3_key is required"})

        use_mock = os.environ.get("USE_TEXTRACT_MOCK", "").strip().lower() in ("1", "true")

        # Document size guard
        try:
            s3 = boto3.client("s3")
            head = s3.head_object(Bucket=s3_bucket, Key=s3_key)
            content_length = head.get("ContentLength", 0)
            if content_length > _MAX_DOCUMENT_SIZE_BYTES:
                logger.warning(
                    "extract_document_text: document too large (%s bytes) for s3://%s/%s",
                    content_length, s3_bucket, s3_key,
                )
                return json.dumps({
                    "error": f"Document exceeds 50 MB size limit ({content_length} bytes). Skipping.",
                    "s3_key": s3_key,
                    "document_type": document_type,
                })
        except Exception as e:
            logger.exception("extract_document_text: head_object failed for s3://%s/%s", s3_bucket, s3_key)
            return json.dumps({"error": f"Failed to check document size: {str(e)}", "s3_key": s3_key})

        key_lower = s3_key.lower()
        is_pdf = key_lower.endswith(".pdf")

        try:
            textract = boto3.client("textract")
            if is_pdf:
                blocks = self._extract_pdf_async(textract, s3_bucket, s3_key, use_mock)
            else:
                blocks = self._extract_image_sync(textract, s3_bucket, s3_key)
        except _TextractMockFallback:
            logger.info(
                "extract_document_text: mock fallback triggered after %d polls for s3://%s/%s",
                _POLL_MOCK_FALLBACK, s3_bucket, s3_key,
            )
            return self._call_textract_mock(s3_bucket, s3_key, document_type, full_name)
        except Exception as e:
            logger.exception(
                "extract_document_text: Textract failed for s3://%s/%s", s3_bucket, s3_key
            )
            if use_mock:
                logger.info("extract_document_text: Textract exception, falling back to mock")
                return self._call_textract_mock(s3_bucket, s3_key, document_type, full_name)
            return json.dumps({"error": f"Textract extraction failed: {str(e)}", "s3_key": s3_key})

        if isinstance(blocks, str):
            # Error string returned from helper
            return json.dumps({"error": blocks, "s3_key": s3_key, "document_type": document_type})

        # Assemble structured result by page
        pages: dict[int, list[str]] = {}
        for block in blocks:
            if block.get("BlockType") != "LINE":
                continue
            page_num = block.get("Page", 1)
            pages.setdefault(page_num, []).append(block.get("Text", ""))

        pages_list = [
            {"page": page_num, "lines": lines}
            for page_num, lines in sorted(pages.items())
        ]
        full_text = "\n".join(
            line for page in pages_list for line in page["lines"]
        )

        result = {
            "document_type": document_type,
            "s3_key": s3_key,
            "pages": pages_list,
            "full_text": full_text,
            "block_count": len(blocks),
        }
        logger.info(
            "extract_document_text output: s3_key=%s, pages=%s, block_count=%s",
            s3_key, len(pages_list), len(blocks),
        )
        return json.dumps(result)

    def _extract_image_sync(self, textract, s3_bucket: str, s3_key: str):
        """Synchronous Textract for image files."""
        response = textract.detect_document_text(
            Document={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}}
        )
        return response.get("Blocks", [])

    def _extract_pdf_async(self, textract, s3_bucket: str, s3_key: str, use_mock: bool = False):
        """Async Textract for PDF files; polls until complete or timeout.

        If use_mock is True and POLL_MOCK_FALLBACK polls pass without SUCCEEDED,
        raises _TextractMockFallback so the caller can switch to the mock endpoint.
        """
        start_response = textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}}
        )
        job_id = start_response["JobId"]
        logger.info("extract_document_text: started async job_id=%s for s3://%s/%s", job_id, s3_bucket, s3_key)

        for attempt in range(_POLL_MAX_RETRIES):
            time.sleep(_POLL_SLEEP_SECONDS)
            result = textract.get_document_text_detection(JobId=job_id)
            status = result.get("JobStatus")
            logger.info(
                "extract_document_text: poll attempt=%s job_id=%s status=%s",
                attempt + 1, job_id, status,
            )
            if status == "SUCCEEDED":
                blocks = result.get("Blocks", [])
                # Paginate through all result pages
                next_token = result.get("NextToken")
                while next_token:
                    page_result = textract.get_document_text_detection(
                        JobId=job_id, NextToken=next_token
                    )
                    blocks.extend(page_result.get("Blocks", []))
                    next_token = page_result.get("NextToken")
                return blocks
            elif status == "FAILED":
                logger.error(
                    "extract_document_text: Textract job failed job_id=%s", job_id
                )
                return f"Textract async job failed for s3://{s3_bucket}/{s3_key}"

            # After POLL_MOCK_FALLBACK polls without success, trigger mock fallback if enabled
            if use_mock and (attempt + 1) >= _POLL_MOCK_FALLBACK:
                logger.warning(
                    "extract_document_text: %d polls without SUCCEEDED for job_id=%s — triggering mock fallback",
                    attempt + 1, job_id,
                )
                raise _TextractMockFallback()

        logger.error(
            "extract_document_text: Textract polling timed out after %s retries for job_id=%s",
            _POLL_MAX_RETRIES, job_id,
        )
        return f"Textract async job timed out after {_POLL_MAX_RETRIES * _POLL_SLEEP_SECONDS}s for s3://{s3_bucket}/{s3_key}"

    def _call_textract_mock(self, s3_bucket: str, s3_key: str, document_type: str, full_name: str = "") -> str:
        """Call the mock service textract endpoint when real Textract is unavailable."""
        mock_url = os.environ.get("MOCK_SERVICE_URL", "").rstrip("/")
        if not mock_url:
            logger.error(
                "extract_document_text: USE_TEXTRACT_MOCK is set but MOCK_SERVICE_URL is not configured"
            )
            return json.dumps({
                "error": "Textract mock requested but MOCK_SERVICE_URL is not configured",
                "s3_key": s3_key,
                "document_type": document_type,
            })

        endpoint = f"{mock_url}/api/v1/textract/extract"
        payload = json.dumps({
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "document_type": document_type or "",
            "full_name": full_name or "",
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
            logger.info(
                "extract_document_text: mock fallback succeeded for s3://%s/%s", s3_bucket, s3_key
            )
            return body
        except Exception as e:
            logger.exception("extract_document_text: mock fallback HTTP call failed")
            return json.dumps({
                "error": f"Textract mock call failed: {str(e)}",
                "s3_key": s3_key,
                "document_type": document_type,
            })
