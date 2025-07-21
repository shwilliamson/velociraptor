from dotenv import load_dotenv
load_dotenv()

import asyncio
import mimetypes
import re
import time
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
BATCH_SIZE = 15

def sanitize_folder_name(filename: str) -> str:
    """Replace illegal directory characters with underscores."""
    # Remove file extension and replace illegal characters
    name = Path(filename).stem
    return re.sub(r'[<>:"/\\|?*]', '_', name)


async def summarize_layer(summaries: list[Summary], doc: Document) -> None:
    """Recursively summarizes layers of summaries up to the root document."""
    if len(summaries) < 4:
        # base case, we've reached the root doc
        summary = await summarize_summaries(*summaries, position=0)
        doc.text = summary.text
        doc.height = summary.height
        logger.info(f"Summarized root document layer {doc.height}.")
        await db.save_document(doc, summaries)
        return

    i = 0
    new_summaries: list[Summary] = []
    # Process summaries in overlapping batches of 3
    while i < len(summaries):
        batch = summaries[i:i+3] \
            if i + 2 < len(summaries) \
            else summaries[i:]
        new_summary = await summarize_summaries(*batch, position=len(new_summaries))
        i += 2  # Move by 2 to create overlap
        prior_summary = new_summaries[-1] if new_summaries else None
        await db.save_summary(new_summary, prior_summary=prior_summary, child_summaries=batch)
        new_summaries.append(new_summary)

    logger.info(f"Summarized layer {new_summaries[0].height}.")
    # Recursively process the new layer
    await summarize_layer(new_summaries, doc)


async def process_documents_folder() -> None:
    start_time = time.time()
    logger.info("Starting document processing")
    
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
            file_path=str(file_path),
            file_name=file_path.stem,
            mime_type=mime_type
        )
        await db.save_document(doc)

        # Collect all pages first
        page_paths = list(split_pdf_to_images(file_path, output_folder))
        page_nodes = []
        for idx, page_path in enumerate(page_paths):
            page = Page(
                document_uuid=doc.uuid,
                height=0,
                position=idx,
                file_path=str(page_path),
                file_name=page_path.stem,
                mime_type="image/jpeg",
                text="",
            )
            page_nodes.append(page)

        # Process in batches
        pages = []
        summaries = []
        for i in range(0, len(page_nodes), BATCH_SIZE):
            batch = page_nodes[i:i + BATCH_SIZE]
            logger.info(f"Processing batch {i // BATCH_SIZE + 1}/{(len(page_nodes) + BATCH_SIZE - 1) // BATCH_SIZE} with {len(batch)} pages")
            
            # Process batch in parallel
            batch_tasks = [extract_and_summarize_page(page) for page in batch]
            batch_results = await asyncio.gather(*batch_tasks)
            
            # Save results sequentially to maintain order
            for page, (processed_page, summary) in zip(batch, batch_results):
                prior_page = pages[-1] if pages else None
                await db.save_page(processed_page, doc, prior_page)
                pages.append(processed_page)

                prior_summary = summaries[-1] if summaries else None
                await db.save_page_summary(summary, processed_page, prior_summary)
                summaries.append(summary)

        logger.info("Beginning to summarize hierarchical layers")
        await summarize_layer(summaries, doc)
        logger.info("Finished summarizing hierarchical layers")

    await db.create_indexes()
    
    end_time = time.time()
    processing_time_ms = int((end_time - start_time) * 1000)
    logger.info(f"Finished document processing in {processing_time_ms}ms")

if __name__ == "__main__":
    asyncio.run(process_documents_folder())