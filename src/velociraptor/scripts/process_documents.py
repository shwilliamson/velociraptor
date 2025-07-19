import mimetypes
import re
from pathlib import Path

from velociraptor.splitters.pdf_splitter import split_pdf_to_images
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)


def sanitize_folder_name(filename: str) -> str:
    """Replace illegal directory characters with underscores."""
    # Remove file extension and replace illegal characters
    name = Path(filename).stem
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def process_documents_folder() -> None:
    project_root = Path(__file__).parent.parent.parent.parent
    documents_path = project_root / "documents"
    documents_split_path = project_root / "documents_split"
    
    if not documents_path.exists():
        logger.info(f"Creating documents folder: {documents_path}")
        documents_path.mkdir(parents=True, exist_ok=True)
    
    if not documents_split_path.exists():
        logger.info(f"Creating documents_split folder: {documents_split_path}")
        documents_split_path.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Processing documents in: {documents_path}")
    
    # Only process files directly in documents folder (no subdirectories)
    for file_path in documents_path.iterdir():
        if not file_path.is_file():
            continue
        
        mime_type, _ = mimetypes.guess_type(file_path)
        
        if mime_type == "application/pdf":
            logger.info(f"Found PDF: {file_path}")
            
            # Create folder structure: documents_split/filename/
            folder_name = sanitize_folder_name(file_path.name)
            output_folder = documents_split_path / folder_name
            
            logger.info(f"Creating output folder: {output_folder}")
            output_folder.mkdir(parents=True, exist_ok=True)
            
            split_pdf_to_images(file_path, output_folder)
            logger.info(f"Successfully processed: {file_path}")


if __name__ == "__main__":
    process_documents_folder()