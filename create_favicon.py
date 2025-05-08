from PIL import Image, ImageDraw, ImageFont
import os

def create_favicon():
    # Create directory if it doesn't exist
    img_dir = os.path.join(os.path.dirname(__file__), 'static', 'img')
    os.makedirs(img_dir, exist_ok=True)
    
    # Create a blank image with blue background (size 64x64)
    size = (64, 64)
    background_color = (0, 123, 255)  # Bootstrap primary blue
    
    # Create image with blue background
    img = Image.new('RGB', size, color=background_color)
    draw = ImageDraw.Draw(img)
    
    # Add "SF" text in white color
    try:
        font = ImageFont.truetype("Arial", 36)  # Try to use Arial font
    except IOError:
        font = ImageFont.load_default()  # Use default font if Arial not available
    
    draw.text((16, 12), "SF", fill="white", font=font)
    
    # Save in multiple sizes for different devices
    for icon_size in [(16, 16), (32, 32), (48, 48), (64, 64)]:
        resized_img = img.resize(icon_size, Image.Resampling.LANCZOS)
        
        # Save individual PNG files for different sizes
        resized_img.save(os.path.join(img_dir, f'favicon-{icon_size[0]}x{icon_size[1]}.png'))
    
    # Save as ICO (supports multiple sizes in one file)
    icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64)]
    img.save(
        os.path.join(img_dir, 'favicon.ico'), 
        sizes=icon_sizes
    )
    
    print(f"Favicon created successfully in {img_dir}")

if __name__ == "__main__":
    create_favicon()
