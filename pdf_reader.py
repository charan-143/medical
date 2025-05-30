import os
import io
import uuid
import logging
import base64
from pathlib import Path
from typing import Optional, Dict, List, Union, Any
from PIL import Image
import fitz  # PyMuPDF
import PyPDF2

# Setup logging
logger = logging.getLogger(__name__)

def extract_pdf_images(pdf_path: str, output_dir: Optional[str] = None) -> Dict[str, Union[bool, List[Dict[str, Any]], str]]:
    """
    Extracts images from a PDF file using PyMuPDF.
    
    Args:
        pdf_path (str): Path to the PDF file
        output_dir (Optional[str]): Directory to save extracted images. 
                                    If None, images are not saved to disk.
        
    Returns:
        Dict[str, Union[bool, List[Dict[str, Any]], str]]: Dictionary containing:
            - 'success' (bool): Whether the extraction was successful
            - 'images' (list): List of image data dictionaries with:
                - 'data' (bytes/str): Image data as bytes or base64 string
                - 'format' (str): Image format (e.g., 'jpeg', 'png')
                - 'page_num' (int): Page number where image was found
                - 'path' (str): Path where image was saved (if output_dir provided)
            - 'message' (str): Success or error message
    """
    try:
        if not os.path.exists(pdf_path):
            return {'success': False, 'images': [], 'message': f"Error: File not found at {pdf_path}"}
            
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
        images = []
        doc = fitz.open(pdf_path)
        
        if len(doc) == 0:
            return {'success': False, 'images': [], 'message': "Error: PDF has no pages"}
        
        for page_num, page in enumerate(doc):
            image_list = page.get_images(full=True)
            if not image_list:
                continue
                
            for img_idx, img_info in enumerate(image_list):
                try:
                    xref = img_info[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_format = base_image["ext"]
                    
                    image_path = None
                    if output_dir:
                        image_filename = f"page{page_num+1}_img{img_idx+1}_{uuid.uuid4().hex}.{image_format}"
                        image_path = os.path.join(output_dir, image_filename)
                        with open(image_path, "wb") as f:
                            f.write(image_bytes)
                    
                    images.append({
                        'data': base64.b64encode(image_bytes).decode('utf-8') if not output_dir else None,
                        'format': image_format,
                        'page_num': page_num + 1,
                        'path': image_path
                    })
                    
                except Exception as img_err:
                    logger.error(f"Error extracting image {img_idx} from page {page_num+1}: {str(img_err)}")
                    continue
        
        if not images:
            return {'success': True, 'images': [], 'message': "No images found in the PDF document."}
            
        return {'success': True, 'images': images, 'message': f"Successfully extracted {len(images)} images from PDF."}
            
    except fitz.FileDataError:
        return {'success': False, 'images': [], 'message': "Error: The PDF file is corrupted or invalid"}
    except PermissionError:
        return {'success': False, 'images': [], 'message': "Error: Permission denied when trying to access the file"}
    except Exception as e:
        logger.error(f"Unexpected error extracting images: {str(e)}", exc_info=True)
        return {'success': False, 'images': [], 'message': f"Error: An unexpected error occurred: {str(e)}"}

def extract_pdf_text(pdf_path: str) -> str:
    """
    Extracts text content from a PDF file.
    
    Args:
        pdf_path (str): Path to the PDF file
        
    Returns:
        str: Extracted text content or error message
    """
    try:
        if not os.path.exists(pdf_path):
            return f"Error: File not found at {pdf_path}"
            
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            num_pages = len(pdf_reader.pages)
            
            if num_pages == 0:
                return "Error: PDF has no pages"
            
            text = ""
            for page_num in range(num_pages):
                page = pdf_reader.pages[page_num]
                text += page.extract_text() + "\n\n"
            
            if not text.strip():
                return "Warning: No text could be extracted from the PDF. The PDF might be scanned images without OCR or have content restrictions."
                
            return text
            
    except PyPDF2.errors.PdfReadError:
        return "Error: The PDF file is corrupted or invalid"
    except PermissionError:
        return "Error: Permission denied when trying to access the file"
    except Exception as e:
        logger.error(f"Error extracting PDF text: {str(e)}", exc_info=True)
        return f"Error: An unexpected error occurred: {str(e)}"
        
def extract_pdf_content(pdf_path: str, extract_images: bool = True, images_output_dir: Optional[str] = None) -> Dict[str, Union[bool, str, List[Dict[str, Any]], int]]:
    """
    Extracts both text and images from a PDF file.
    
    Args:
        pdf_path (str): Path to the PDF file
        extract_images (bool): Whether to extract images
        images_output_dir (Optional[str]): Directory to save extracted images
        
    Returns:
        Dict[str, Union[bool, str, List[Dict[str, Any]], int]]: Dictionary containing:
            - 'success' (bool): Whether the extraction was successful
            - 'text' (str): Extracted text content
            - 'text_status' (str): Text extraction status
            - 'images' (list): List of image data dictionaries
            - 'images_status' (str): Image extraction status
            - 'page_count' (int): Number of pages in the PDF
    """
    result = {
        'success': False,
        'text': "",
        'text_status': "",
        'images': [],
        'images_status': "",
        'page_count': 0
    }
    
    try:
        if not os.path.exists(pdf_path):
            result['text_status'] = f"Error: File not found at {pdf_path}"
            return result
            
        text_result = extract_pdf_text(pdf_path)
        
        if text_result.startswith("Error:"):
            result['text_status'] = text_result
            return result
            
        result['text'] = text_result
        result['text_status'] = "Text extracted successfully"
        
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            result['page_count'] = len(pdf_reader.pages)
        
        if extract_images:
            images_result = extract_pdf_images(pdf_path, images_output_dir)
            result['images'] = images_result['images']
            result['images_status'] = images_result['message']
        
        result['success'] = True
        return result
        
    except Exception as e:
        logger.error(f"Error in extract_pdf_content: {str(e)}", exc_info=True)
        result['text_status'] = f"Error: An unexpected error occurred: {str(e)}"
        return result
        
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    pdf_path = r"D:\medical project\medical\static\uploads\1\LR_W_2f29a972e8849f6083a929b0faeb3436_560933afba5e4c72bd065e34910629fc.pdf"
    
    result = extract_pdf_content(
        pdf_path, 
        extract_images=True,
        images_output_dir="extracted_images"
    )
    
    if not result['success']:
        print(f"Error processing PDF: {result['text_status']}")
    else:
        print("\n--- PDF CONTENT SUMMARY ---\n")
        if result['text']:
            preview = result['text'][:1000] + "..." if len(result['text']) > 1000 else result['text']
            print(preview)
            
            output_file = "pdf_text_output.txt"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(result['text'])
            print(f"\nComplete text saved to {output_file}")
        
        if result['images']:
            print(f"\n--- EXTRACTED {len(result['images'])} IMAGES ---")
            for i, img in enumerate(result['images']):
                print(f"Image {i+1}: Format={img['format']}, Page={img['page_num']}, Path={img['path']}")
        else:
            print("\nNo images found in PDF.")
