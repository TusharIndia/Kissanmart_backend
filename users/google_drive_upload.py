import io
import os
import cloudinary
import cloudinary.uploader
import cloudinary.api

# --------------------------
# CONFIGURE YOUR CREDENTIALS
# --------------------------
CLOUDINARY_CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY = os.getenv('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.getenv('CLOUDINARY_API_SECRET')

# Initialize Cloudinary
cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET
)


def upload_image_to_drive(image_file, file_name=None, mimetype='image/jpeg'):
    """
    Uploads an image to Cloudinary and returns a public link.
    
    :param image_file: File-like object or bytes of the image
    :param file_name: Optional file name (defaults to 'uploaded_image.jpg')
    :param mimetype: MIME type of the image
    :return: Public link to access the uploaded image
    """
    if not file_name:
        file_name = 'uploaded_image.jpg'

    # Handle file input: bytes or file-like object
    if isinstance(image_file, bytes):
        # Wrap bytes into BytesIO for Cloudinary
        image_stream = io.BytesIO(image_file)
    else:
        image_stream = image_file

    # Upload to Cloudinary
    result = cloudinary.uploader.upload(
        image_stream,
        public_id=os.path.splitext(file_name)[0],  # use file name without extension
        resource_type="image"
    )

    # Return the direct URL
    return result.get("secure_url")
