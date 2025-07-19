import mimetypes
import re
from pathlib import Path

from velociraptor.db.neo4j import Neo4jDb
from velociraptor.models.document import Document
from velociraptor.models.edge import EdgeType
from velociraptor.models.page import Page
from velociraptor.models.summary import Summary
from velociraptor.split.pdf import split_pdf_to_images
from velociraptor.summarize.summarize import summarize_page, summarize_summaries
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
    if len(summaries) < 3:
        # base case, we've reached the root doc
        summary = summarize_summaries(*summaries)
        doc.summary = summary.summary
        doc.height = summary.height
        db.save_node(doc)
        for s in summaries:
            db.create_edge(doc, s, EdgeType.SUMMARIZES)
        return

    new_summaries = []
    # Process summaries in overlapping batches of 3
    i = 0
    while i < len(summaries):
        batch = summaries[i:i+3] \
            if i + 2 < len(summaries) \
            else summaries[i:]
        new_summary = summarize_summaries(*batch)
        i += 2  # Move by 2 to create overlap

        new_summaries.append(new_summary)
        db.save_node(new_summary)
        if new_summaries and len(new_summaries) > 1:
            db.link(new_summaries[-2], new_summaries[-1])
        for b in batch:
            db.create_edge(new_summary, b, EdgeType.SUMMARIZES)
    
    # Recursively process the new layer if we have enough summaries
    if len(new_summaries) >= 3:
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
        doc = Document(
            summary="", # not yet known
            height=-1,  # not yet known
            position=0,
            file_path=f"files/documents/${file_path.name}",
            file_name=file_path.stem,
            mime_type=mime_type
        )
        db.save_node(doc)

        if mime_type != "application/pdf":
            logger.warning(f"Skipping {file_path} of type {mime_type}")
            continue

        logger.info(f"Found PDF: {file_path}")
        folder_name = sanitize_folder_name(file_path.name)
        output_folder = documents_split_path / folder_name
        logger.info(f"Creating output folder: {output_folder}")
        output_folder.mkdir(parents=True, exist_ok=True)

        pages = []
        summaries = []
        for idx, page_path in enumerate(split_pdf_to_images(file_path, output_folder)):
            logger.info(f"Processing page {idx}")
            page = Page(
                document_uuid=doc.uuid,
                height=0,
                position=idx,
                file_path=f"files/documents/page/${page_path.name}",
                file_name=page_path.stem,
                mime_type="image/jpeg"
            )
            db.save_node(page)
            if pages:
                db.link(pages[-1], page)
            pages.append(page)

            summary = summarize_page(page)
            db.save_node(summary)
            db.create_edge(summary, page, EdgeType.SUMMARIZES)
            if summaries:
                db.link(summaries[-1], summary)
            summaries.append(summary)

            summarize_layer(summaries, doc)

            logger.info(f"Successfully processed: {file_path}")


if __name__ == "__main__":
    process_documents_folder()