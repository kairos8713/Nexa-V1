import os
import uuid
from PIL import Image
from werkzeug.utils import secure_filename
from flask import current_app

class ImageService:
    @staticmethod
    def save_image(file_storage, folder='uploads', optimize=True, quality=85):
        """
        Saves an image file, converting it to WebP format if optimize is True.
        
        :param file_storage: The FileStorage object from Flask request.
        :param folder: The subfolder within static/img to save to.
        :param optimize: Whether to convert to WebP and optimize.
        :param quality: WebP quality setting (0-100).
        :return: Public URL path to the saved image.
        """
        if not file_storage:
            return None

        # Ensure upload directory exists
        upload_dir = os.path.join(current_app.root_path, 'static', 'img', folder)
        os.makedirs(upload_dir, exist_ok=True)

        filename = secure_filename(file_storage.filename)
        name, ext = os.path.splitext(filename)
        
        # Generate unique name
        unique_name = f"{name}_{uuid.uuid4().hex[:8]}"
        
        if optimize:
            # Convert to WebP
            target_filename = f"{unique_name}.webp"
            target_path = os.path.join(upload_dir, target_filename)
            
            try:
                img = Image.open(file_storage)
                # Convert RGBA to RGB if saving as JPEG, but WebP supports transparency.
                # However, for consistency/safety:
                # if img.mode in ("RGBA", "P"): img = img.convert("RGB") 
                
                img.save(target_path, 'WEBP', quality=quality, optimize=True)
                return f"/static/img/{folder}/{target_filename}"
            except Exception as e:
                print(f"Image optimization failed: {e}")
                # Fallback to original save if conversion fails
                pass
        
        # Fallback or non-optimized save
        target_filename = f"{unique_name}{ext}"
        target_path = os.path.join(upload_dir, target_filename)
        file_storage.seek(0) # Reset pointer
        file_storage.save(target_path)
        
        return f"/static/img/{folder}/{target_filename}"
