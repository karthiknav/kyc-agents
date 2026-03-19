"""Tool to extract data from documents stored in S3 via AWS Textract.

Routes to the optimal Textract API based on document type:
- Identity documents (passport, id_card, drivers_license) → AnalyzeID
- Tabular/financial documents (income, payslip, bank_statement) → AnalyzeDocument (TABLES+FORMS)
- Other documents (address, utility_bill, etc.) → DetectDocumentText
"""
import json
import logging
import time
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_MAX_DOCUMENT_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
_POLL_MAX_RETRIES = 50
_POLL_SLEEP_SECONDS = 3

# Document type categories for API routing
_IDENTITY_DOC_TYPES = {"passport", "id_card", "drivers_license", "national_id", "residence_permit"}
_TABULAR_DOC_TYPES = {"income", "payslip", "bank_statement", "tax_return", "invoice", "financial"}


class ExtractDocumentTextInput(BaseModel):
    s3_bucket: str = Field(description="S3 bucket where the document is stored")
    s3_key: str = Field(description="S3 key (path) of the document to extract text from")
    document_type: str = Field(
        default="",
        description=(
            "Document type label from the case files (e.g. 'passport', 'id_card', 'income', 'address'). "
            "Used to select the optimal Textract API: identity documents use AnalyzeID, "
            "financial/tabular documents use AnalyzeDocument with TABLES+FORMS, "
            "other documents use plain text detection."
        ),
    )


class ExtractDocumentTextTool(BaseTool):
    """Extract data from a document stored in S3 using the optimal AWS Textract API for the document type."""

    name: str = "extract_document_text"
    description: str = (
        "Extracts data from a document stored in S3 using AWS Textract. "
        "Automatically selects the best Textract API based on document_type: "
        "identity documents (passport, id_card) use AnalyzeID for structured identity fields; "
        "financial/tabular documents (income, payslip, bank_statement) use AnalyzeDocument with "
        "TABLES and FORMS extraction; other documents use plain text detection. "
        "Pass s3_bucket, s3_key, and document_type from the get_case_files output."
    )
    args_schema: Type[ExtractDocumentTextInput] = ExtractDocumentTextInput

    def _run(self, s3_bucket: str, s3_key: str, document_type: str = "") -> str:
        """Extract data from a document in S3, routing to the optimal Textract API."""
        logger.info(
            "extract_document_text input: s3_bucket=%s, s3_key=%s, document_type=%s",
            s3_bucket, s3_key, document_type,
        )
        if not s3_bucket:
            return json.dumps({"error": "s3_bucket is required"})
        if not s3_key:
            return json.dumps({"error": "s3_key is required"})

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

        doc_type_lower = document_type.lower().strip()
        key_lower = s3_key.lower()
        is_pdf = key_lower.endswith(".pdf")

        try:
            textract = boto3.client("textract")

            if doc_type_lower in _IDENTITY_DOC_TYPES:
                return self._extract_identity(textract, s3_bucket, s3_key, document_type)
            elif doc_type_lower in _TABULAR_DOC_TYPES:
                return self._extract_tabular(textract, s3_bucket, s3_key, document_type, is_pdf)
            else:
                return self._extract_plain_text(textract, s3_bucket, s3_key, document_type, is_pdf)

        except Exception as e:
            logger.exception(
                "extract_document_text: Textract failed for s3://%s/%s", s3_bucket, s3_key
            )
            return json.dumps({"error": f"Textract extraction failed: {str(e)}", "s3_key": s3_key})

    # ------------------------------------------------------------------
    # Identity documents → AnalyzeID
    # ------------------------------------------------------------------

    def _extract_identity(self, textract, s3_bucket: str, s3_key: str, document_type: str) -> str:
        """Use Textract AnalyzeID for identity documents (passport, ID card, etc.)."""
        logger.info("extract_document_text: using AnalyzeID for document_type=%s", document_type)

        response = textract.analyze_id(
            DocumentPages=[
                {
                    "S3Object": {
                        "Bucket": s3_bucket,
                        "Name": s3_key,
                    }
                }
            ]
        )

        # Parse AnalyzeID response into structured identity fields
        identity_fields = {}
        documents_summary = []
        for doc_idx, identity_document in enumerate(response.get("IdentityDocuments", [])):
            doc_fields = {}
            for field in identity_document.get("IdentityDocumentFields", []):
                field_type = field.get("Type", {}).get("Text", "")
                field_value = field.get("ValueDetection", {}).get("Text", "")
                field_confidence = field.get("ValueDetection", {}).get("Confidence", 0)
                if field_type and field_value:
                    doc_fields[field_type] = {
                        "value": field_value,
                        "confidence": round(field_confidence, 2),
                    }
                    identity_fields[field_type] = field_value

            documents_summary.append({
                "document_index": doc_idx + 1,
                "fields_extracted": len(doc_fields),
                "fields": doc_fields,
            })

        result = {
            "extraction_method": "ANALYZE_ID",
            "document_type": document_type,
            "s3_key": s3_key,
            "identity_fields": identity_fields,
            "documents": documents_summary,
            "document_count": len(response.get("IdentityDocuments", [])),
        }
        logger.info(
            "extract_document_text output (AnalyzeID): s3_key=%s, identity_fields=%s, document_count=%s",
            s3_key, list(identity_fields.keys()), result["document_count"],
        )
        return json.dumps(result)

    # ------------------------------------------------------------------
    # Tabular/financial documents → AnalyzeDocument (TABLES + FORMS)
    # ------------------------------------------------------------------

    def _extract_tabular(self, textract, s3_bucket: str, s3_key: str, document_type: str, is_pdf: bool) -> str:
        """Use Textract AnalyzeDocument with TABLES+FORMS for financial/tabular documents."""
        logger.info("extract_document_text: using AnalyzeDocument (TABLES+FORMS) for document_type=%s", document_type)

        if is_pdf:
            blocks = self._analyze_document_async(textract, s3_bucket, s3_key)
        else:
            response = textract.analyze_document(
                Document={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}},
                FeatureTypes=["TABLES", "FORMS"],
            )
            blocks = response.get("Blocks", [])

        if isinstance(blocks, str):
            return json.dumps({"error": blocks, "s3_key": s3_key, "document_type": document_type})

        # Build block lookup for relationship resolution
        block_map = {b["Id"]: b for b in blocks}

        # Extract key-value pairs from FORMS
        key_value_pairs = self._extract_key_value_pairs(blocks, block_map)

        # Extract tables
        tables = self._extract_tables(blocks, block_map)

        # Extract full text from LINE blocks
        full_text = "\n".join(
            b.get("Text", "") for b in blocks if b.get("BlockType") == "LINE"
        )

        result = {
            "extraction_method": "ANALYZE_DOCUMENT",
            "document_type": document_type,
            "s3_key": s3_key,
            "key_value_pairs": key_value_pairs,
            "tables": tables,
            "full_text": full_text,
            "block_count": len(blocks),
        }
        logger.info(
            "extract_document_text output (AnalyzeDocument): s3_key=%s, kv_pairs=%s, tables=%s, blocks=%s",
            s3_key, len(key_value_pairs), len(tables), len(blocks),
        )
        return json.dumps(result)

    def _extract_key_value_pairs(self, blocks: list, block_map: dict) -> dict:
        """Extract form key-value pairs from AnalyzeDocument blocks."""
        kv_pairs = {}
        for block in blocks:
            if block.get("BlockType") != "KEY_VALUE_SET" or "KEY" not in block.get("EntityTypes", []):
                continue
            key_text = self._get_text_from_relationships(block, block_map, "CHILD")
            value_block = None
            for rel in block.get("Relationships", []):
                if rel["Type"] == "VALUE":
                    for vid in rel.get("Ids", []):
                        value_block = block_map.get(vid)
                        break
            value_text = ""
            if value_block:
                value_text = self._get_text_from_relationships(value_block, block_map, "CHILD")
            if key_text:
                kv_pairs[key_text.strip()] = value_text.strip()
        return kv_pairs

    def _extract_tables(self, blocks: list, block_map: dict) -> list:
        """Extract tables from AnalyzeDocument blocks as list of row arrays."""
        tables = []
        for block in blocks:
            if block.get("BlockType") != "TABLE":
                continue
            rows: dict[int, dict[int, str]] = {}
            for rel in block.get("Relationships", []):
                if rel["Type"] != "CHILD":
                    continue
                for cell_id in rel.get("Ids", []):
                    cell = block_map.get(cell_id)
                    if not cell or cell.get("BlockType") != "CELL":
                        continue
                    row_idx = cell.get("RowIndex", 1)
                    col_idx = cell.get("ColumnIndex", 1)
                    cell_text = self._get_text_from_relationships(cell, block_map, "CHILD")
                    rows.setdefault(row_idx, {})[col_idx] = cell_text.strip()
            # Convert to list of lists
            if rows:
                table_data = []
                for row_num in sorted(rows.keys()):
                    row = rows[row_num]
                    max_col = max(row.keys()) if row else 0
                    table_data.append([row.get(c, "") for c in range(1, max_col + 1)])
                tables.append(table_data)
        return tables

    @staticmethod
    def _get_text_from_relationships(block: dict, block_map: dict, rel_type: str) -> str:
        """Resolve CHILD relationships to extract concatenated text."""
        texts = []
        for rel in block.get("Relationships", []):
            if rel["Type"] != rel_type:
                continue
            for child_id in rel.get("Ids", []):
                child = block_map.get(child_id)
                if child and child.get("BlockType") == "WORD":
                    texts.append(child.get("Text", ""))
        return " ".join(texts)

    def _analyze_document_async(self, textract, s3_bucket: str, s3_key: str):
        """Async Textract AnalyzeDocument for multi-page PDFs with TABLES+FORMS."""
        start_response = textract.start_document_analysis(
            DocumentLocation={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}},
            FeatureTypes=["TABLES", "FORMS"],
        )
        job_id = start_response["JobId"]
        logger.info("extract_document_text: started async analysis job_id=%s for s3://%s/%s", job_id, s3_bucket, s3_key)

        for attempt in range(_POLL_MAX_RETRIES):
            time.sleep(_POLL_SLEEP_SECONDS)
            result = textract.get_document_analysis(JobId=job_id)
            status = result.get("JobStatus")
            logger.info(
                "extract_document_text: poll attempt=%s job_id=%s status=%s",
                attempt + 1, job_id, status,
            )
            if status == "SUCCEEDED":
                blocks = result.get("Blocks", [])
                next_token = result.get("NextToken")
                while next_token:
                    page_result = textract.get_document_analysis(JobId=job_id, NextToken=next_token)
                    blocks.extend(page_result.get("Blocks", []))
                    next_token = page_result.get("NextToken")
                return blocks
            elif status == "FAILED":
                logger.error("extract_document_text: analysis job failed job_id=%s", job_id)
                return f"Textract analysis job failed for s3://{s3_bucket}/{s3_key}"

        logger.error(
            "extract_document_text: analysis polling timed out after %s retries for job_id=%s",
            _POLL_MAX_RETRIES, job_id,
        )
        return f"Textract analysis job timed out after {_POLL_MAX_RETRIES * _POLL_SLEEP_SECONDS}s for s3://{s3_bucket}/{s3_key}"

    # ------------------------------------------------------------------
    # Plain text documents → DetectDocumentText
    # ------------------------------------------------------------------

    def _extract_plain_text(self, textract, s3_bucket: str, s3_key: str, document_type: str, is_pdf: bool) -> str:
        """Use Textract DetectDocumentText for general documents."""
        logger.info("extract_document_text: using DetectDocumentText for document_type=%s", document_type)

        if is_pdf:
            blocks = self._detect_text_async(textract, s3_bucket, s3_key)
        else:
            response = textract.detect_document_text(
                Document={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}}
            )
            blocks = response.get("Blocks", [])

        if isinstance(blocks, str):
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
            "extraction_method": "DETECT_TEXT",
            "document_type": document_type,
            "s3_key": s3_key,
            "pages": pages_list,
            "full_text": full_text,
            "block_count": len(blocks),
        }
        logger.info(
            "extract_document_text output (DetectText): s3_key=%s, pages=%s, block_count=%s",
            s3_key, len(pages_list), len(blocks),
        )
        return json.dumps(result)

    def _detect_text_async(self, textract, s3_bucket: str, s3_key: str):
        """Async Textract DetectDocumentText for multi-page PDFs."""
        start_response = textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}}
        )
        job_id = start_response["JobId"]
        logger.info("extract_document_text: started async text detection job_id=%s for s3://%s/%s", job_id, s3_bucket, s3_key)

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
                next_token = result.get("NextToken")
                while next_token:
                    page_result = textract.get_document_text_detection(JobId=job_id, NextToken=next_token)
                    blocks.extend(page_result.get("Blocks", []))
                    next_token = page_result.get("NextToken")
                return blocks
            elif status == "FAILED":
                logger.error("extract_document_text: text detection job failed job_id=%s", job_id)
                return f"Textract text detection job failed for s3://{s3_bucket}/{s3_key}"

        logger.error(
            "extract_document_text: text detection polling timed out after %s retries for job_id=%s",
            _POLL_MAX_RETRIES, job_id,
        )
        return f"Textract text detection job timed out after {_POLL_MAX_RETRIES * _POLL_SLEEP_SECONDS}s for s3://{s3_bucket}/{s3_key}"
