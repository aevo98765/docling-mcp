import gc
import os
from typing import Annotated, Any
from dotenv import load_dotenv

from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, FormatOption, PdfFormatOption
from docling.utils.accelerator_utils import AcceleratorDevice
from docling_core.types.doc.document import (
    ContentLayer, DoclingDocument
)
from docling_core.types.doc.labels import (
    DocItemLabel,
)

from docling_mcp.docling_cache import get_cache_key
from docling_mcp.logger import setup_logger
from docling_mcp.shared import local_document_cache, local_stack_cache, mcp

from elasticsearch import Elasticsearch
from elastic_transport import ObjectApiResponse

load_dotenv()

# Create a default project logger
logger = setup_logger()


def cleanup_memory():
    """Force garbage collection to free up memory."""
    logger.info("Performed memory cleanup")
    gc.collect()


@mcp.tool()
def is_document_in_local_cache(cache_key: str) -> bool:
    """
    Verify if document is already converted and in the local cache.

    Args:
        key: string

    Returns:

        success: bool
    """
    return cache_key in local_document_cache


@mcp.tool()
def convert_pdf_document_into_json_docling_document_from_uri_path(
        source: str,
) -> tuple[bool, str]:
    """
    Convert a PDF document from a URL or local path and store in local cache.

    Args:
        source: URL or local file path to the document

    Returns:
        The tools returns a tuple, the first element being a boolean
        representing success and the second for the cache_key to allow
        future access to the file.

    Usage:
        convert_document("https://arxiv.org/pdf/2408.09869")
        convert_document("/path/to/document.pdf")
    """
    try:
        # Remove any quotes from the source string
        source = source.strip("\"'")

        # Log the cleaned source
        logger.info(f"Processing document from source: {source}")

        # Generate cache key
        cache_key = get_cache_key(source)

        if cache_key in local_document_cache:
            logger.info(f"{source} has previously been added.")
            return False, "Document already exists in the system cache."

        # Log the start of processing
        logger.info("Set up pipeline options")

        # Configure pipeline
        # ocr_options = EasyOcrOptions(lang=ocr_language or ["en"])
        pipeline_options = PdfPipelineOptions(
            # do_ocr=False,
            # ocr_options=ocr_options,
            accelerator_device=AcceleratorDevice.MPS  # Explicitly set MPS
        )
        format_options: dict[InputFormat, FormatOption] = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }

        # Create converter with MPS acceleration
        logger.info(f"Creating DocumentConverter with format_options: {format_options}")
        converter = DocumentConverter(format_options=format_options)

        # Convert the document
        logger.info("Start conversion")
        result = converter.convert(source)

        # Check for errors - handle different API versions
        has_error = False
        error_message = ""

        # Try different ways to check for errors based on the API version
        if hasattr(result, "status"):
            if hasattr(result.status, "is_error"):
                has_error = result.status.is_error
            elif hasattr(result.status, "error"):
                has_error = result.status.error

        if hasattr(result, "errors") and result.errors:
            has_error = True
            error_message = str(result.errors)

        if has_error:
            error_msg = f"Conversion failed: {error_message}"
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=error_msg))

        local_document_cache[cache_key] = result.document

        item = result.document.add_text(
            label=DocItemLabel.TEXT,
            text=f"source: {source}",
            content_layer=ContentLayer.FURNITURE,
        )

        local_stack_cache[cache_key] = [item]

        # Log completion
        logger.info(f"Successfully created the Docling document: {source}")

        # Clean up memory
        cleanup_memory()

        return True, cache_key

    except Exception as e:
        logger.exception(f"Error converting document: {source}")
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message=f"Unexpected error: {e!s}")
        )

if os.getenv("ELASTIC_SEARCH_URL") and os.getenv("ELASTIC_SEARCH_API_KEY"):
    @mcp.tool()
    def docling_document_to_elastic_search(
            document_key: str
    ) -> [bool, str]:
        """
        Upload a docling document to elastic search server.

        Args:
            document_key:

        Returns:
            The tool returns a tuple, the first element being a boolean
            representing success and the second is the unique identifier for
            the documents existence in elastic search.

        """
        # Check if the document key in the local cache.
        if document_key not in local_document_cache:
            doc_keys = ", ".join(local_document_cache.keys())
            raise ValueError(
                f"document-key: {document_key} is not found. Existing document-keys are: {doc_keys}"
            )
        # Load the elastic search client.
        client = Elasticsearch(os.getenv("ELASTIC_SEARCH_URL"), api_key=os.getenv("ELASTIC_SEARCH_API_KEY"))

        # Check that there is a successful connection.
        if not client.ping():
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="Failed to connect to Elasticsearch"))

        # Access the pre-existing file from memory
        document: DoclingDocument = local_document_cache[document_key]

        result_dict = document.export_to_dict()
        # Binary hash int value cannot be parsed by elastic as it exceeds the 'long' data type. Convert to string to circumvent.
        result_dict["origin"]["binary_hash"] = str(result_dict["origin"]["binary_hash"])

        # Add the document to elastic search
        elastic_response: ObjectApiResponse = client.index(index="docling-mcp", id=document_key, document=result_dict)

        # Check to see if this addition was not a success
        if elastic_response.meta.status not in [200, 201]:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="File not added to Elastic search"))

        return True, document_key


@mcp.tool()
def convert_attachments_into_docling_document(
        pdf_payloads: list[Annotated[bytes, {"media_type": "application/octet-stream"}]],
) -> list[dict[str, Any]]:
    """
    Process a pdf files attachment from Claude Desktop.

    Args:
        pdf_payloads: PDF document as binary data from the attachment

    Returns:
        A dictionary with processed results
    """
    results = []
    for pdf_payload in pdf_payloads:
        # Example processing - you can replace this with your actual processing logic
        file_size = len(pdf_payload)

        # First few bytes as hex for identification
        header_bytes = pdf_payload[:10].hex()

        # You can implement file type detection, parsing, or any other processing here
        # For example, if it's an image, you might use PIL to process it

        results.append(
            {
                "file_size_bytes": file_size,
                "header_hex": header_bytes,
                "status": "processed",
            }
        )

    return results
