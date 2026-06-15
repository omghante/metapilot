"""
Media processor for handling different file types from WhatsApp.
Supports images, audio, video, and PDF documents.
"""
import base64
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class MediaProcessor:
    """
    Process different media types from WhatsApp messages.
    Uses OpenRouter for AI-based analysis and PyPDF2 for PDF extraction.
    """
    
    def __init__(self, openrouter_service=None):
        """
        Initialize media processor.
        
        Args:
            openrouter_service: OpenRouterService instance for AI analysis
        """
        self.openrouter = openrouter_service
    
    def process_pdf(self, buffer: bytes) -> str:
        """
        Extract text from PDF document.
        
        Args:
            buffer: Raw PDF bytes
            
        Returns:
            Extracted text content
        """
        try:
            from PyPDF2 import PdfReader
            from io import BytesIO
            
            pdf_file = BytesIO(buffer)
            reader = PdfReader(pdf_file)
            
            text_content = []
            # Limit to first 10 pages to avoid huge outputs
            max_pages = min(len(reader.pages), 10)
            
            for i in range(max_pages):
                page = reader.pages[i]
                text = page.extract_text()
                if text:
                    text_content.append(text.strip())
            
            if text_content:
                full_text = "\n\n".join(text_content)
                # Truncate if too long
                if len(full_text) > 3000:
                    full_text = full_text[:3000] + "... (truncated)"
                return f"PDF Content:\n{full_text}"
            else:
                return "The PDF appears to be empty or contains only images."
                
        except ImportError:
            logger.error("PyPDF2 not installed")
            return "PDF processing is not available. Please install PyPDF2."
        except Exception as e:
            logger.error(f"PDF processing error: {e}")
            return "Could not process the PDF document."
    
    def process_image(self, buffer: bytes, mime_type: str = "image/jpeg") -> str:
        """
        Analyze image using AI vision model.
        
        Args:
            buffer: Raw image bytes
            mime_type: Image MIME type
            
        Returns:
            Image description/analysis
        """
        if not self.openrouter:
            return "Image analysis is not configured."
        
        try:
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            prompt = (
                "Analyze this image and describe what you see. "
                "Be concise but comprehensive. Focus on the main subjects, "
                "any text visible, and the overall context."
            )
            
            return self.openrouter.analyze_image(image_base64, prompt)
            
        except Exception as e:
            logger.error(f"Image processing error: {e}")
            return "Could not analyze the image."
    
    def process_audio(self, buffer: bytes, mime_type: str = "audio/mpeg") -> str:
        """
        Process audio file (transcription).
        
        Args:
            buffer: Raw audio bytes
            mime_type: Audio MIME type
            
        Returns:
            Transcription or placeholder
        """
        if not self.openrouter:
            return "Audio processing is not configured."
        
        try:
            audio_base64 = base64.b64encode(buffer).decode('utf-8')
            return self.openrouter.transcribe_audio(audio_base64, mime_type)
            
        except Exception as e:
            logger.error(f"Audio processing error: {e}")
            return "Could not process the audio."
    
    def process_video(self, buffer: bytes, mime_type: str = "video/mp4") -> str:
        """
        Process video file.
        
        Note: Full video analysis requires frame extraction.
        This provides a basic acknowledgment.
        
        Args:
            buffer: Raw video bytes
            mime_type: Video MIME type
            
        Returns:
            Processing result or placeholder
        """
        # Video processing is complex - would need frame extraction
        # For now, provide a helpful response
        file_size_mb = len(buffer) / (1024 * 1024)
        
        return (
            f"I received your video ({file_size_mb:.1f} MB). "
            "Video analysis is limited. If you need help with something "
            "specific in the video, please describe it or send a screenshot."
        )
    
    def process_sticker(self, buffer: bytes, mime_type: str = "image/webp") -> str:
        """
        Process sticker (treat as image).
        
        Args:
            buffer: Raw sticker bytes
            mime_type: Sticker MIME type (usually image/webp)
            
        Returns:
            Sticker analysis
        """
        # Stickers are essentially images in WebP format
        return self.process_image(buffer, mime_type)
    
    def process_media(self, buffer: bytes, mime_type: str) -> str:
        """
        Route media to appropriate processor based on MIME type.
        
        Args:
            buffer: Raw media bytes
            mime_type: Media MIME type
            
        Returns:
            Processed result string
        """
        if not buffer:
            return "No media data received."
        
        mime_lower = mime_type.lower()
        
        if mime_lower == 'application/pdf':
            return self.process_pdf(buffer)
        
        if mime_lower.startswith('image/'):
            # Check for sticker (WebP)
            if 'webp' in mime_lower:
                return self.process_sticker(buffer, mime_type)
            return self.process_image(buffer, mime_type)
        
        if mime_lower.startswith('audio/'):
            return self.process_audio(buffer, mime_type)
        
        if mime_lower.startswith('video/'):
            return self.process_video(buffer, mime_type)
        
        return f"I received a file ({mime_type}) but I'm not able to process this file type."
    
    def get_mime_type_for_whatsapp_type(self, wa_type: str) -> str:
        """
        Get default MIME type for WhatsApp media type.
        
        Args:
            wa_type: WhatsApp media type (image, audio, document, video, sticker)
            
        Returns:
            Default MIME type
        """
        type_map = {
            'image': 'image/jpeg',
            'audio': 'audio/mpeg',
            'document': 'application/pdf',
            'video': 'video/mp4',
            'sticker': 'image/webp',
            'voice': 'audio/ogg'
        }
        return type_map.get(wa_type.lower(), 'application/octet-stream')
