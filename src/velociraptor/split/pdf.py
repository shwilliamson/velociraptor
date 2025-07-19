from pathlib import Path
from typing import Union, Generator
import fitz
import shutil

from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)


def split_pdf_to_images(pdf_path: Union[str, Path], output_dir: Union[str, Path, None] = None) -> Generator[Path, None, None]:
    """
    Split a PDF file into individual JPG images for each page.
    Creates a 'pages' folder in the same directory as the PDF, or in specified output directory.
    Uses control files to track processing status and avoid reprocessing.
    """
    pdf_path = Path(pdf_path)
    
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file '{pdf_path}' not found.")
    
    if not pdf_path.suffix.lower() == '.pdf':
        raise ValueError(f"'{pdf_path}' is not a PDF file.")
    
    if output_dir:
        control_dir = Path(output_dir)
        pages_dir = control_dir / "pages"
    else:
        control_dir = pdf_path.parent
        pages_dir = control_dir / "pages"
    
    # Control file paths
    control_success = control_dir / "control.success"
    control_in_progress = control_dir / "control.in-progress"
    control_error = control_dir / "control.error"
    
    # Check for existing control files
    if control_success.exists():
        logger.info(f"PDF '{pdf_path.name}' already processed successfully. Yielding existing pages.")
        for page_file in sorted(pages_dir.glob("*.jpg")):
            yield page_file
        return
    
    if control_in_progress.exists():
        logger.info(f"PDF '{pdf_path.name}' is currently being processed. Skipping.")
        return
    
    # Handle error case - delete pages folder and start fresh
    if control_error.exists():
        logger.info(f"Found error control file for '{pdf_path.name}'. Cleaning up and starting fresh.")
        if pages_dir.exists():
            shutil.rmtree(pages_dir)
        control_error.unlink()
    
    # Create control.in-progress file
    control_in_progress.touch()
    logger.info(f"Started processing '{pdf_path.name}'")
    
    try:
        pages_dir.mkdir(parents=True, exist_ok=True)
        
        pdf_document = fitz.open(pdf_path)
        page_count = len(pdf_document)
        
        logger.info(f"Processing {page_count} pages from '{pdf_path.name}'...")
        
        for page_num in range(page_count):
            page = pdf_document[page_num]
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            
            filename = f"{page_num + 1:05d}.jpg"
            output_path = pages_dir / filename
            pix.save(output_path, jpg_quality=50)
            logger.debug(f"Saved page {page_num + 1} as {filename}")
            yield output_path
        
        pdf_document.close()
        
        # Success - rename control file
        control_in_progress.rename(control_success)
        logger.info(f"Successfully split PDF into {page_count} JPG files in '{pages_dir}'")
        
    except Exception as e:
        logger.error(f"Error processing PDF '{pdf_path.name}': {e}", exc_info=True)
        
        # Error - rename control file
        if control_in_progress.exists():
            control_in_progress.rename(control_error)
        
        raise
