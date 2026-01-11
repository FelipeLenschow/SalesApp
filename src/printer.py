import serial
import serial.tools.list_ports
import time
import unicodedata
import os
import os
from PIL import Image, ImageDraw, ImageFont
import datetime



class Printer:
    def __init__(self, port=None, baudrate=9600):
        self.port = port
        self.baudrate = baudrate

    @staticmethod
    def find_printer_port():
        """
        Attempts to find the Elgin printer based on description or VID:PID if known.
        """
        ports = serial.tools.list_ports.comports()
        for port in ports:
            desc = port.description.upper()
            # Elgin usually shows up as "Elgin" or generic USB Serial depending on driver
            # Common PL2303 or CH340 also possible
            if "ELGIN" in desc:
                return port.device
        
        # Fallback: Look for generic USB Serial if not found?
        # Maybe dangerous to auto-pick generic ones as it might be the scanner.
        # Let's check for PROLIFIC which is common for some serial printers
        for port in ports:
             if "PROLIFIC" in desc.upper():
                 return port.device
                 
        return None

    def print_image(self, image_input, ser):
        """
        Prints a monochrome image using GS v 0 command.
        image_input: Can be a file path (str) or a PIL Image object.
        """
        try:
            if isinstance(image_input, str):
                if not os.path.exists(image_input):
                     print(f"Image not found: {image_input}")
                     return
                img = Image.open(image_input)
            else:
                img = image_input
            
            # Resize logic:
            # Max width for 58mm printer is ~384 dots usually.
            MAX_WIDTH = 384
            if img.width > MAX_WIDTH:
                ratio = MAX_WIDTH / img.width
                # Use nearest or box for speed/simplicity with text? Lanczos is fine.
                new_height = int(img.height * ratio)
                img = img.resize((MAX_WIDTH, new_height), Image.Resampling.LANCZOS)

            
            # Convert to monochrome (1-bit)
            # We use a threshold to convert to pure black/white
            img = img.convert('L') # Grayscale
            img = img.point(lambda x: 0 if x < 128 else 255, '1') # Threshold
            
            width = img.width
            height = img.height
            
            # Pad width to be multiple of 8
            if width % 8 != 0:
                width += (8 - (width % 8))
                new_img = Image.new('1', (width, height), 255) # White bg
                new_img.paste(img, (0, 0))
                img = new_img
                
            # Get raster data
            data = img.tobytes(encoder_name='raw')
            # The '1' mode packs 8 pixels per byte, which is what we need.
            
            # Invert bits if needed? usually 0=Black, 1=White for PIL?
            # ESC/POS usually expects 1=Black (Print), 0=White.
            # PIL '1' mode: 0 is black, 255 is white.
            # But the raw bytes from tobytes() with mode '1' packs pixels.
            # Usually we need to invert data for some printers, but let's try standard first.
            # Actually standard GS v 0 expects 1 for print point.
            # If PIL 0=Black, we need to invert.
            
            inverted_data = bytearray()
            for b in data:
                inverted_data.append(~b & 0xFF)
             
            # Command: GS v 0 m xL xH yL yH d1...dk
            # m = 0 (Normal)
            # xL, xH = width in bytes
            # yL, yH = height in dots
            
            x_bytes = width // 8
            xL = x_bytes & 0xFF
            xH = (x_bytes >> 8) & 0xFF
            
            yL = height & 0xFF
            yH = (height >> 8) & 0xFF
            
            ser.write(b'\x1d\x76\x30\x00') # GS v 0 0
            ser.write(bytes([xL, xH, yL, yH]))
            ser.write(inverted_data)
            ser.write(b'\n') # Reduced from \n\n

            
        except Exception as e:
            print(f"Error printing image: {e}")


    def check_connection(self):

        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=1)
            if ser.is_open:
                ser.close()
                return True
            return False
        except serial.SerialException:
            return False


    def _normalize(self, text):
        """Removes accents and ensures ascii compatible text for basic thermal printers."""
        return unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode('utf-8')

    def print_receipt(self, sale_data, shop_name, shop_details=None):
        """
        Prints the receipt. 
        Args:
           sale_data: Sale object or dict
           shop_name: String
           shop_details: Dict with 'address', 'phone', 'cnpj', 'message'
        """

        if not self.port:
            print("Printer port not set.")
            return False
            
        print(f"DEBUG: Printing receipt for {shop_name}")
        print(f"DEBUG: Shop Details: {shop_details}")

            
        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=1)
            
            # Init
            # ser.write(b'\x1b\x40') # Commented out to reduce top feed
            
            # ENSURE LEFT ALIGNMENT (Reset from previous receipt's center footer)
            ser.write(b'\x1b\x61\x00') 


            
            # --- HEADER GENERATION ---
            # Create a combined image: Logo (Left) + Text (Right)
            
            # Canvas Settings
            PAGE_WIDTH = 375
            # Start with a tall canvas, then crop
            HEADER_HEIGHT = 100 
            
            img = Image.new('RGB', (PAGE_WIDTH, HEADER_HEIGHT), color='white')



            draw = ImageDraw.Draw(img)
            
            # 1. Load Logo
            logo_path = None
            if "DOKI" in shop_name.upper():
                 logo_path = os.path.join("assets", "doki_logo.png")
            elif "LOLLA" in shop_name.upper():
                 logo_path = os.path.join("assets", "lolla_logo.png")
            
            logo_width = 0
            if logo_path and os.path.exists(logo_path):
                logo = Image.open(logo_path)
                
                # Auto-crop whitespace
                # Convert to grayscale for bbox detection if needed, or just use alpha/inv
                # Assuming white background, we need to invert to find content?
                # Or if transparent?
                # The generated logos are usually black on white.
                # Invert to treat black as content
                try:
                    gray = logo.convert('L')
                    # Invert: content is black (0), bg is white (255) -> Invert: content (255)
                    from PIL import ImageOps
                    inverted = ImageOps.invert(gray)
                    bbox = inverted.getbbox()
                    if bbox:
                        logo = logo.crop(bbox)
                except:
                    pass # Keep original if crop fails

                # Resize logo to fit nicely on left (e.g., up to 120px wide)
                # But maintain aspect ratio.
                # Max width: 120, Max Height: HEADER_HEIGHT (130)
                
                MAX_W = 120
                MAX_H = HEADER_HEIGHT - 10
                
                logo.thumbnail((MAX_W, MAX_H), Image.Resampling.LANCZOS)
                
                # Paste at (0, 5) padding
                # Center vertically?
                y_pos = (HEADER_HEIGHT - logo.height) // 2
                img.paste(logo, (0, y_pos))
                logo_width = logo.width + 30 # Increased Padding


            
            # 2. Draw Text on Right
            # Try to load a font, or default
            try:
                # Force Windows Font Path for reliability
                font_path = "C:/Windows/Fonts/arial.ttf"
                if not os.path.exists(font_path):
                     # Try generic name if path doesn't exist
                     font_path = "arial.ttf"

                font_title = ImageFont.truetype(font_path, 22) # Slightly larger
                font_text = ImageFont.truetype(font_path, 18)
                font_small = ImageFont.truetype(font_path, 16)
                print(f"Loaded font: {font_path}")
            except Exception as e:
                print(f"Font load warning: {e}. Using default.")
                font_title = ImageFont.load_default()
                font_text = ImageFont.load_default()
                font_small = ImageFont.load_default()

            text_x = logo_width
            current_y = 5
            
            # Draw black text (0,0,0) explicitly
            # Shop Name
            draw.text((text_x, current_y), self._normalize(shop_name), font=font_title, fill=(0,0,0))

            current_y += 25
            
            # Address & Details
            if shop_details:
                if shop_details.get('address'):
                    # Simple wrap or truncation?
                    addr = self._normalize(shop_details['address'])
                    draw.text((text_x, current_y), addr, font=font_text, fill=(0,0,0))
                    current_y += 22
                
                if shop_details.get('cnpj'):
                    draw.text((text_x, current_y), f"CNPJ: {shop_details['cnpj']}", font=font_small, fill=(0,0,0))
                    current_y += 20
                    
                if shop_details.get('phone'):
                     draw.text((text_x, current_y), f"Tel: {shop_details['phone']}", font=font_small, fill=(0,0,0))
                     current_y += 20

            
            # Add Payment/Time into the image or print below? 
            # User said: "to the right... and then the time, the header, payment method"
            # It seems like "Store Info" is right of logo.
            # "Time, Header (what header?), Payment Method" might be below?
            # Let's put Time/Payment below the graphical header to keep it clean.
            
            # Auto-crop the whole header image to remove unused white space
            try:
                # Convert to grayscale -> Invert -> BBox
                from PIL import ImageOps
                gray_header = img.convert('L')
                inv_header = ImageOps.invert(gray_header)
                header_bbox = inv_header.getbbox()
                if header_bbox:
                    # Crop to content height, keeping full width? 
                    # Usually we want full width for align, but vertical crop is key.
                    # bbox is (left, top, right, bottom)
                    # We want (0, top, 384, bottom) to avoid shift? 
                    # Yes, keep X=0 to maintain relative structure if we want centered-ish look?
                    # The logo is at X=0, so left should be close to 0. 
                    # Let's crop full width: (0, bbox[1], PAGE_WIDTH, bbox[3])
                    # Add small padding
                    top = max(0, header_bbox[1] - 5)
                    bottom = min(HEADER_HEIGHT, header_bbox[3] + 5)
                    img = img.crop((0, top, PAGE_WIDTH, bottom))
            except Exception as e:
                print(f"Header crop error: {e}")

            # Print the generated Header
            self.print_image(img, ser)

            
            # --- SUB-HEADER (Time, Payment) ---
            ser.write(b'\x1b\x61\x00') # Left align
            ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            payment = sale_data.payment_method if hasattr(sale_data, 'payment_method') else "Dinheiro"
            
            ser.write(f"Data: {ts}\n".encode('utf-8'))
            ser.write(f"Metodo de pagamento: {self._normalize(payment)}\n".encode('utf-8'))
            ser.write(b"------------------------------------------------\n")


            # --- ITEMS ---
            # Columns Header
            # Assuming 48 cols. 
            # ITEM (Left) ................. TOTAL (Right)
            # Adjust widths to sum to ~48
            # Name (20) + gap(1) + QtyPrice(15) + gap(1) + Total(10) = 47
            
            ser.write(f"{'ITEM'.ljust(20)} {'QTD x UNIT'.center(15)} {'VALOR'.rjust(10)}\n".encode('utf-8'))
            ser.write(b"------------------------------------------------\n")
            
            for product_id, item in sale_data.current_sale.items():
                name = f"{item['categoria']} {item['sabor']}".strip()
                name = self._normalize(name)
                qty = item['quantidade']
                price = item['preco']
                total_item = qty * price
                
                # Format quantities
                if isinstance(qty, float):
                    qty_str = f"{qty:.0f}" if qty.is_integer() else f"{qty:.2f}"
                else:
                    qty_str = str(qty)
                
                # Math string: "2x5.00" (remove spaces to save room)
                math_str = f"{qty_str}x{price:.2f}"
                
                # Total string: "10.00"
                total_str = f"{total_item:.2f}"
                
                # Calculate available width for Name
                # Total 48
                # We definitively need: len(math_str) + len(total_str) + 2 spaces
                # But let's stick to fixed columns for cleanness if possible, or flexible?
                # Fixed columns are safer for alignment.
                
                COL_NAME = 20
                COL_MATH = 15
                COL_TOTAL = 10
                
                # Truncate Name
                name_disp = name[:COL_NAME]
                
                # Compose Line
                # Name (Left 20) | Math (Center 15) | Total (Right 10)
                line = f"{name_disp.ljust(COL_NAME)} {math_str.center(COL_MATH)} {total_str.rjust(COL_TOTAL)}\n"
                ser.write(line.encode('utf-8'))



            ser.write(b"------------------------------------------------\n")

            
            # Totals
            ser.write(b'\x1b\x61\x02') # Right align
            ser.write(b'\x1b\x21\x10') # Double height
            total = sale_data.calculate_total() # Assuming sale_data is a Sale object
            ser.write(f"TOTAL: R${total:.2f}\n".encode('utf-8'))
            ser.write(b'\x1b\x21\x00') # Reset
            
            if shop_details and shop_details.get('message'):
                ser.write(b'\x1b\x61\x01') # Center
                ser.write(f"\n{self._normalize(shop_details['message'])}\n".encode('utf-8'))

            ser.write(b'\x1b\x61\x01') # Center (ensure center for feed)
            ser.write(b"\n\n\n") # Reduced feed


            
            # --- CUT ---
            # GS V 66 0
            ser.write(b'\x1d\x56\x42\x00')
            # Only partial cut or feed? Let's just feed for now as user commented out cut in test.
            
            ser.close()
            return True

        except Exception as e:
            print(f"Printer Error: {e}")
            return False
