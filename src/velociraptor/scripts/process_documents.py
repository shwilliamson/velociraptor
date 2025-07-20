from dotenv import load_dotenv
load_dotenv()

import mimetypes
import re
from pathlib import Path

from velociraptor.db.neo4j import Neo4jDb
from velociraptor.models.document import Document
from velociraptor.models.page import Page
from velociraptor.models.summary import Summary
from velociraptor.split.pdf import split_pdf_to_images
from velociraptor.summarize.summarize import summarize_summaries, extract_and_summarize_page
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)
db = Neo4jDb()

def sanitize_folder_name(filename: str) -> str:
    """Replace illegal directory characters with underscores."""
    # Remove file extension and replace illegal characters
    name = Path(filename).stem
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def summarize_layer(summaries: list[Summary], doc: Document) -> None:
    """Recursively summarizes layers of summaries up to the root document."""
    if len(summaries) < 4:
        # base case, we've reached the root doc
        summary = summarize_summaries(*summaries, position=0)
        doc.text = summary.text
        doc.height = summary.height
        logger.info(f"Summarized root document layer {doc.height}.")
        db.save_document(doc, summaries)
        return

    i = 0
    new_summaries: list[Summary] = []
    # Process summaries in overlapping batches of 3
    while i < len(summaries):
        batch = summaries[i:i+3] \
            if i + 2 < len(summaries) \
            else summaries[i:]
        new_summary = summarize_summaries(*batch, position=len(new_summaries))
        i += 2  # Move by 2 to create overlap
        prior_summary = new_summaries[-1] if new_summaries else None
        db.save_summary(new_summary, prior_summary=prior_summary, child_summaries=batch)
        new_summaries.append(new_summary)

    logger.info(f"Summarized layer {new_summaries[0].height}.")
    # Recursively process the new layer
    summarize_layer(new_summaries, doc)


def process_documents_folder() -> None:
    project_root = Path(__file__).parent.parent.parent.parent
    documents_path = project_root / "files" / "documents"
    documents_split_path = project_root / "files" / "documents_split"
    
    if not documents_path.exists():
        logger.info(f"Creating documents folder: {documents_path}")
        documents_path.mkdir(parents=True, exist_ok=True)
    
    if not documents_split_path.exists():
        logger.info(f"Creating documents_split folder: {documents_split_path}")
        documents_split_path.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Processing documents in: {documents_path}")
    for file_path in documents_path.iterdir():
        if not file_path.is_file():
            continue
        
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type != "application/pdf":
            logger.warning(f"Skipping {file_path} of type {mime_type}")
            continue

        logger.info(f"Found PDF: {file_path}")
        folder_name = sanitize_folder_name(file_path.name)
        output_folder = documents_split_path / folder_name
        logger.info(f"Creating output folder: {output_folder}")
        output_folder.mkdir(parents=True, exist_ok=True)

        doc = Document(
            text="", # not yet known
            height=-1,  # not yet known
            position=0,
            file_path=f"files/documents/${file_path.name}",
            file_name=file_path.stem,
            mime_type=mime_type
        )
        db.save_document(doc)

        pages = []
        summaries = []
        for idx, page_path in enumerate(split_pdf_to_images(file_path, output_folder)):
            logger.info(f"Processing page {idx}")
            page = Page(
                document_uuid=doc.uuid,
                height=0,
                position=idx,
                file_path=str(page_path),
                file_name=page_path.stem,
                mime_type="image/jpeg",
                text="",
            )
            page, summary = extract_and_summarize_page(page)
            prior_page = pages[-1] if pages else None
            db.save_page(page, doc, prior_page)
            pages.append(page)

            prior_summary = summaries[-1] if summaries else None
            db.save_page_summary(summary, page, prior_summary)
            summaries.append(summary)

        summarize_layer(summaries, doc)

    db.create_indexes()

if __name__ == "__main__":
    process_documents_folder()