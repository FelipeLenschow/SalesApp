import serial
import serial.tools.list_ports
import time
import unicodedata
import os
import os
from PIL import Image, ImageDraw, ImageFont
import datetime
try:
    import qrcode
except ImportError:
    qrcode = None



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
            # Max width for 58mm printer is ~384 dots.
            # Max width for 80mm printer is ~576 dots.
            # We will try to detect or default to larger if image suggests it, or keep it safe?
            # User complaint suggests 80mm paper usage.
            MAX_WIDTH = 576 
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

    def _print_header_image(self, ser, shop_name, shop_details):
        """
        Generates and prints the Shop Header (Logo + Text).
        """
        try:
            # Canvas Settings
            # 80mm printer max width is ~576 dots.
            # Using 550 to leave safe margins.
            PAGE_WIDTH = 550 
            HEADER_HEIGHT = 160 # Increased height to accommodate larger text/logo
            
            img = Image.new('RGB', (PAGE_WIDTH, HEADER_HEIGHT), color='white')
            draw = ImageDraw.Draw(img)
            
            # 1. Load Logo
            logo_path = None
            base_path = os.path.dirname(os.path.abspath(__file__)) # src/
            project_root = os.path.dirname(base_path) # Sales/
            assets_dir = os.path.join(project_root, "assets")
            
            print(f"DEBUG: Looking for logo in {assets_dir} for {shop_name}")
            
            if "DOKI" in shop_name.upper():
                 logo_path = os.path.join(assets_dir, "doki_logo.png")
            elif "LOLLA" in shop_name.upper():
                 logo_path = os.path.join(assets_dir, "lolla_logo.png")
            
            logo_width = 0
            if logo_path and os.path.exists(logo_path):
                try:
                    logo = Image.open(logo_path)
                    
                    # Handle Transparency (RGBA -> RGB with white bg)
                    if logo.mode in ('RGBA', 'LA') or (logo.mode == 'P' and 'transparency' in logo.info):
                        alpha = logo.convert('RGBA').split()[-1]
                        bg = Image.new("RGB", logo.size, (255, 255, 255))
                        bg.paste(logo, mask=alpha)
                        logo = bg
                    else:
                        logo = logo.convert("RGB")
                    
                    MAX_W = 130 # Slightly wider
                    MAX_H = 100
                    logo.thumbnail((MAX_W, MAX_H), Image.Resampling.LANCZOS)
                    
                    # Vertical Center relative to new height
                    y_pos = (HEADER_HEIGHT - logo.height) // 2
                    # If text takes up space, maybe align top? 
                    y_pos = 10 # Top padding
                    
                    img.paste(logo, (5, y_pos))
                    logo_width = logo.width + 15 # Padding
                    print(f"DEBUG: Logo loaded. W={logo.width} H={logo.height}")
                except Exception as e:
                    print(f"Logo load error: {e}")
            else:
                 print(f"DEBUG: Logo not found at {logo_path}")

            # 2. Draw Text on Right
            try:
                font_path = "C:/Windows/Fonts/arial.ttf"
                if not os.path.exists(font_path): font_path = "arial.ttf"
                
                # Increased sizes
                font_title = ImageFont.truetype(font_path, 24) 
                font_text = ImageFont.truetype(font_path, 20) # Was 18
                font_small = ImageFont.truetype(font_path, 20) # Was 16 (User wants same size)
            except:
                font_title = ImageFont.load_default()
                font_text = ImageFont.load_default()
                font_small = ImageFont.load_default()

            text_x = logo_width
            current_y = 10
            
            # Simple Text Wrapping Helper
            def draw_multiline(text, x, y, font, max_width):
                words = text.split()
                lines = []
                current_line = []
                for word in words:
                    test_line = ' '.join(current_line + [word])
                    bbox = draw.textbbox((0, 0), test_line, font=font)
                    w = bbox[2] - bbox[0]
                    if w <= max_width:
                        current_line.append(word)
                    else:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                lines.append(' '.join(current_line))
                
                dy = y
                for line in lines:
                    draw.text((x, dy), line, font=font, fill=(0,0,0))
                    bbox = draw.textbbox((0, 0), line, font=font)
                    h = bbox[3] - bbox[1]
                    dy += h + 5 # Line spacing
                return dy

            # Shop Name
            available_width = PAGE_WIDTH - text_x - 5
            
            current_y = draw_multiline(self._normalize(shop_name), text_x, current_y, font_title, available_width)
            current_y += 5 # Gap after title
            
            # Details
            if shop_details:
                if shop_details.get('address'):
                    addr = self._normalize(shop_details['address'])
                    current_y = draw_multiline(addr, text_x, current_y, font_text, available_width)
                    current_y += 5
                
                if shop_details.get('cnpj'):
                    current_y = draw_multiline(f"CNPJ: {shop_details['cnpj']}", text_x, current_y, font_small, available_width)
                    current_y += 5

                if shop_details.get('phone'):
                     current_y = draw_multiline(f"Tel: {shop_details['phone']}", text_x, current_y, font_small, available_width)

            # Auto-crop logic (same as before) logic reused...

            # Auto-crop
            try:
                from PIL import ImageOps
                gray_header = img.convert('L')
                inv_header = ImageOps.invert(gray_header)
                header_bbox = inv_header.getbbox()
                if header_bbox:
                    top = max(0, header_bbox[1] - 5)
                    bottom = min(HEADER_HEIGHT, header_bbox[3] + 5)
                    img = img.crop((0, top, PAGE_WIDTH, bottom))
            except Exception as e:
                print(f"Crop error: {e}")

            self.print_image(img, ser)
            return True
        except Exception as e:
            print(f"Header Generation Error: {e}")
            return False

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
            # Used extracted method
            self._print_header_image(ser, shop_name, shop_details)

            
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



    def print_nfce_mock(self, fiscal_result, sale_payload, shop_details=None):
        """
        Prints a simulated NFC-e receipt (DANFE Mock).
        Uses standard header styling.
        """
        if not self.port:
            print("Printer port not set.")
            return False

        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=1)
            
            # Helper to send text
            def send_text(text, align='LEFT', bold=False, size='NORMAL'):
                # Reset
                ser.write(b'\x1b\x21\x00') 
                
                # Align
                if align == 'CENTER':
                    ser.write(b'\x1b\x61\x01')
                elif align == 'RIGHT':
                    ser.write(b'\x1b\x61\x02')
                else:
                    ser.write(b'\x1b\x61\x00')
                
                # Bold / Size
                # ESC ! n
                # Bit 0: unused
                # Bit 1: unused
                # Bit 2: unused
                # Bit 3: Bold
                # Bit 4: Double Height
                # Bit 5: Double Width
                mode = 0
                if bold: mode += 8
                if size == 'LARGE': mode += 16 + 32
                if size == 'DOUBLE_H': mode += 16
                if size == 'DOUBLE_W': mode += 32
                
                ser.write(b'\x1b\x21' + bytes([mode]))
                
                ser.write(self._normalize(text).encode('utf-8', errors='ignore'))
                ser.write(b'\n')

            # --- HEADER ---
            # Use Reused Method from print_receipt
            # Construct shop_details if not passed, but we should pass it.
            emitente = sale_payload['emitente']
            shop_name = emitente.get('nome', 'LOJA')
            
            # Initialize printer for graphics? No, _print_header_image handles it
            
            # Print Graphical Header
            if shop_details:
                 self._print_header_image(ser, shop_name, shop_details)
            else:
                 # Fallback if no shop_details passed
                 details_fallback = {
                     'cnpj': emitente.get('cnpj'),
                     'address': emitente.get('endereco')
                 }
                 self._print_header_image(ser, shop_name, details_fallback)
            
            # Sub-Header specific to NFC-e
            ser.write(b'\x1b\x61\x01') # Center
            send_text("Documento Auxiliar da Nota Fiscal", 'CENTER', bold=True)
            send_text("de Consumidor Eletronica", 'CENTER', bold=True)
            ser.write(b'\n')

            # --- ITEMS ---
            # --- ITEMS ---
            # Standard Receipt Layout (Single Line, Truncated)
            # ITEM (Left 20) | QTD x UNIT (Center 15) | VALOR (Right 10)
            
            # Header
            header_line = f"{'ITEM'.ljust(20)} {'QTD x UNIT'.center(15)} {'VALOR'.rjust(10)}"
            send_text(header_line, 'LEFT')
            send_text("-" * 48, 'LEFT')
            
            items = sale_payload['itens']
            for i, item in enumerate(items):
                desc = item['descricao']
                qty = item['quantidade']
                unit_price = item['valor_unitario']
                total_item = item['valor_total']
                
                # Format Quantity
                if isinstance(qty, float):
                    qty_str = f"{qty:.0f}" if qty.is_integer() else f"{qty:.2f}"
                else:
                    qty_str = str(qty)

                # Math string: "2x5.00"
                math_str = f"{qty_str}x{unit_price:.2f}"
                
                # Total string
                total_str = f"{total_item:.2f}"
                
                # Column Widths
                COL_NAME = 20
                COL_MATH = 15
                COL_TOTAL = 10
                
                # Truncate Name
                name_disp = desc[:COL_NAME]
                
                # Compose Line
                line = f"{name_disp.ljust(COL_NAME)} {math_str.center(COL_MATH)} {total_str.rjust(COL_TOTAL)}"
                send_text(line, 'LEFT')

            send_text("-" * 48, 'LEFT') # Separator after items

            # --- TOTALS ---
            pay_info = sale_payload['pagamento']
            total = pay_info['valor'] if isinstance(pay_info['valor'], (int, float)) else 0.0
            
            send_text(f"QTD. TOTAL DE ITENS                    {len(items)}", 'LEFT')
            
            # Totals Large like receipt
            ser.write(b'\x1b\x61\x02') # Right align
            ser.write(b'\x1b\x21\x10') # Double height
            ser.write(f"TOTAL: R${total:.2f}\n".encode('utf-8'))
            ser.write(b'\x1b\x21\x00') # Reset
            
            # Translate payment code
            codes = {'01':'Dinheiro', '03':'Cartao Credito', '04':'Cartao Debito', '17':'Pix'}
            pay_desc = codes.get(pay_info['forma'], 'Outros')
            
            send_text(f"FORMA PAGAMENTO: {pay_desc}            {total:.2f}", 'LEFT')
            
            ser.write(b'\n')

            # Footer Message from Shop
            if shop_details and shop_details.get('message'):
                ser.write(b'\x1b\x61\x01') # Center
                ser.write(f"\n{self._normalize(shop_details['message'])}\n".encode('utf-8'))
                ser.write(b'\n')

            # --- FISCAL DETAILS (MOCK) ---
            send_text("EMISSAO NORMAL (MOCK)", 'CENTER', bold=True)
            send_text(f"Numero: {fiscal_result['numero']} Serie: {fiscal_result['serie']} Emissao: {fiscal_result.get('data_emissao', '')}", 'CENTER')
            send_text("Consulte pela Chave de Acesso em:", 'CENTER')
            send_text("http://nfce.fazenda.sp.gov.br/consulta", 'CENTER')
            send_text("CHAVE DE ACESSO", 'CENTER', bold=True)
            
            # Format key in groups of 4
            key = fiscal_result['chave_acesso']
            formatted_key = " ".join([key[i:i+4] for i in range(0, len(key), 4)])
            send_text(formatted_key, 'CENTER')
            
            ser.write(b'\n')

            # --- QR CODE ---
            if qrcode:
                try:
                    # Generate QR Code
                    qr_url = fiscal_result.get('url_qrcode', 'http://nfce.fazenda.sp.gov.br/qrcode')
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=4,
                        border=1,
                    )
                    qr.add_data(qr_url)
                    qr.make(fit=True)

                    img_qr = qr.make_image(fill_color="black", back_color="white")
                    
                    # Center align before image
                    ser.write(b'\x1b\x61\x01')
                    
                    # Use existing print_image logic (we need to pass 'ser' to it, or refactor)
                    # refactoring print_image to take 'ser' as argument was done in my previous thought? 
                    # No, print_image signature is: print_image(self, image_input, ser)
                    # So we can just call it.
                    self.print_image(img_qr._img, ser) # _img is the PIL image usually for qrcode lib
                    
                except Exception as e:
                     print(f"QR Gen Error: {e}")
                     send_text("<< ERRO QR CODE >>", 'CENTER', bold=True)
            else:
                send_text("<< QR CODE SIMULADO (Instale 'qrcode') >>", 'CENTER', bold=True)
            
            ser.write(b'\n')
            send_text("CONSUMIDOR NAO IDENTIFICADO", 'CENTER')
            ser.write(b'\n\n\n\n')
            
            # Cut
            ser.write(b'\x1d\x56\x00') 
            
            ser.close()
            return True
            
        except Exception as e:
            print(f"Error printing NFC-e mock: {e}")
            return False
