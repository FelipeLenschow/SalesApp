import flet as ft
import math
import ast
import json
import os
import io
import base64
import datetime
try:
    import qrcode
except ImportError:
    qrcode = None

from src.fiscal import FiscalManager


class SalesHistoryDialog:
    def __init__(self, page, app):
        self.page = page
        self.app = app
        self.db = app.product_db
        
        # Main History View Container
        self.history_content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.ALWAYS,
        )
        self.history_view = ft.Container(
            content=self.history_content,
            width=800, # Ensure good width for history table
            height=600,
            padding=10
        )
        
        self.dialog = ft.AlertDialog(
            title=ft.Text("Histórico de Vendas"),
            content=self.history_view,
        )
        self.load_data()

    def safe_parse_products(self, products_json):
        try:
            # Handle empty or None
            if not products_json:
                return {}
            # It should be a JSON string from the new DB
            if isinstance(products_json, str):
                return json.loads(products_json)
            # Fallback if it's already dict
            if isinstance(products_json, dict):
                return products_json
            return {}
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            return {}

    def format_products(self, produtos_dict):
        # Legacy helper, keeping for safety but likely unused
        if not produtos_dict:
            return ["Nenhum produto registrado"]

        formatted_lines = []
        for product_id, details in produtos_dict.items():
            preco = details.get('preco', 0)
            if isinstance(preco, (int, float)):
                preco = f"R${preco:.2f}"
            else:
                preco = "R$0.00"

            line = (
                f"- {details.get('categoria', 'N/A')} ({details.get('sabor', 'N/A')}): "
                f"{details.get('quantidade', 0)} unidade(s) a {preco}"
            )
            formatted_lines.append(line)
        return formatted_lines

    def load_data(self):
        try:
            # Load from AWS DB
            sales_history = self.db.get_sales_history(shop_name=self.app.shop, limit=100)
            
            # Helper to safely display values
            def safe_str(val):
                return str(val) if val is not None and val != 'None' and val != 'nan' else ""

            # Clear current
            self.history_content.controls.clear()

            # Create header row
            header = ft.Row(
                controls=[
                    ft.Text("Data", width=150, weight=ft.FontWeight.BOLD),
                    ft.Text("Horário", width=100, weight=ft.FontWeight.BOLD),
                    ft.Text("Preço Final", width=150, weight=ft.FontWeight.BOLD),
                    ft.Text("Método Pagamento", width=200, weight=ft.FontWeight.BOLD),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
            self.history_content.controls.append(header)
            
            if not sales_history:
                 self.history_content.controls.append(
                    ft.Text("Nenhum histórico de vendas encontrado.", color=ft.Colors.GREY)
                )
                 return

            for row in sales_history:
                preco_final = row['Preco Final']
                if isinstance(preco_final, (int, float)):
                    preco_final = f"R${preco_final:.2f}"
                else:
                    preco_final = "R$0.00"

                row_content = ft.ListTile(
                    title=ft.Row(
                        controls=[
                            ft.Text(safe_str(row['Data']), width=150),
                            ft.Text(safe_str(row['Horario']), width=100),
                            ft.Text(preco_final, width=150),
                            ft.Text(safe_str(row['Metodo de pagamento']), width=200),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, color=ft.Colors.BLUE_GREY_400),
                    on_click=lambda e, r=row: self.show_product_details(r),
                    hover_color=ft.Colors.BLUE_GREY_800,
                    dense=True,
                )
                self.history_content.controls.append(row_content)

        except Exception as e:
            self.history_content.controls.append(
                ft.Text(f"Erro ao carregar histórico: {e}", color=ft.Colors.RED)
            )

    def show_product_details(self, row_data):
        shop_details = self.db.get_shop_details()
        shop_name = self.app.shop
        products_dict = self.safe_parse_products(row_data['Produtos'])
        
        # Helper for receipt text to ensure it's black on white paper
        def RText(text, weight=None, size=None, font_family=None, text_align=None, italic=False, width=None):
            return ft.Text(
                text, 
                color=ft.Colors.BLACK, 
                weight=weight, 
                size=size, 
                font_family=font_family,
                text_align=text_align,
                italic=italic,
                width=width
            )

        # --- Receipt Layout Construction ---
        
        # 1. Header (Logo + Shop Details)
        header_controls = []
        
        # Logo Logic
        logo_path = None
        base_path = os.path.dirname(os.path.abspath(__file__)) 
        project_root = os.path.dirname(os.path.dirname(base_path))
        assets_dir = os.path.join(project_root, "assets")
        
        if "DOKI" in shop_name.upper():
            logo_path = os.path.join(assets_dir, "doki_logo.png")
        elif "LOLLA" in shop_name.upper():
            logo_path = os.path.join(assets_dir, "lolla_logo.png")
            
        logo_img = None
        if logo_path and os.path.exists(logo_path):
            logo_img = ft.Image(src=logo_path, width=80, height=80, fit=ft.ImageFit.CONTAIN)
            
        # Shop Text
        shop_text_col = ft.Column(spacing=2, expand=True)
        shop_text_col.controls.append(RText(shop_name.upper(), weight=ft.FontWeight.BOLD, size=14, font_family="Roboto Mono"))
        
        if shop_details:
            if shop_details.get('address'):
                shop_text_col.controls.append(RText(shop_details['address'], size=10, font_family="Roboto Mono"))
            if shop_details.get('cnpj'):
                 shop_text_col.controls.append(RText(f"CNPJ: {shop_details['cnpj']}", size=10, font_family="Roboto Mono"))
            if shop_details.get('phone'):
                 shop_text_col.controls.append(RText(f"Tel: {shop_details['phone']}", size=10, font_family="Roboto Mono"))

        header_row = ft.Row(
            controls=[logo_img, shop_text_col] if logo_img else [shop_text_col],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        )
        
        header_controls.append(header_row)
        header_controls.append(ft.Divider(height=10, color=ft.Colors.BLACK))
        
        # 2. Sub-Header (DANFE)
        header_controls.append(RText("Documento Auxiliar da Nota Fiscal\nde Consumidor Eletrônica", text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD, size=12, width=380))
        header_controls.append(ft.Divider(height=5, color=ft.Colors.TRANSPARENT))
        
        # 3. Items List
        items_controls = []
        items_controls.append(RText(f"{'ITEM'.ljust(20)} {'QTD x UNIT'.center(15)} {'VALOR'.rjust(10)}", font_family="Courier New", size=12, weight=ft.FontWeight.BOLD))
        items_controls.append(ft.Divider(height=1, color=ft.Colors.BLACK))
        
        total_value = 0.0
        
        for pid, details in products_dict.items():
            name = f"{details.get('categoria', '')} {details.get('sabor', '')}".strip()
            qty = details.get('quantidade', 0)
            price = details.get('preco', 0.0)
            
            try:
                qty = float(qty)
                price = float(price)
            except:
                pass
                
            total_item = qty * price
            total_value += total_item
            
            if qty.is_integer():
                qty_str = f"{int(qty)}"
            else:
                qty_str = f"{qty:.2f}"
                
            math_str = f"{qty_str}x{price:.2f}"
            total_str = f"{total_item:.2f}"
            
            name_disp = name[:20]
            
            COL_NAME = 20
            COL_MATH = 15
            COL_TOTAL = 10
            
            line = f"{name_disp.ljust(COL_NAME)} {math_str.center(COL_MATH)} {total_str.rjust(COL_TOTAL)}"
            items_controls.append(RText(line, font_family="Courier New", size=12))
            
        items_controls.append(ft.Divider(height=1, color=ft.Colors.BLACK))
        
        # 4. Totals
        items_controls.append(ft.Row([
            RText("QTD. TOTAL DE ITENS", font_family="Courier New", size=12),
            RText(f"{len(products_dict)}", font_family="Courier New", size=12)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

        items_controls.append(ft.Row([
            RText("TOTAL:", weight=ft.FontWeight.BOLD, size=16),
            RText(f"R${total_value:.2f}", weight=ft.FontWeight.BOLD, size=16)
        ], alignment=ft.MainAxisAlignment.END, spacing=10)) # Match Printer Right Align
        
        payment_method = row_data.get('Metodo de pagamento') or 'NÃO INFORMADO'
        items_controls.append(ft.Row([
            RText(f"FORMA DE PAGAMENTO: {payment_method}", font_family="Courier New", size=12),
            RText(f"{total_value:.2f}", font_family="Courier New", size=12)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
        items_controls.append(ft.Divider(height=10, color=ft.Colors.BLACK))
        
        # 5. Footer Message
        if shop_details and shop_details.get('message'):
            items_controls.append(RText(shop_details['message'], text_align=ft.TextAlign.CENTER, size=12, italic=True, width=380))
            items_controls.append(ft.Container(height=10))

        # 6. Fiscal Info (with Placeholders)
        
        fiscal_key = row_data.get('fiscal_key')
        is_emitted = bool(fiscal_key)
        
        if is_emitted:
            display_key = fiscal_key
            # Since we don't store number/series in DB columns yet, we mock them as '1' for the view if key exists
            display_num = row_data.get('numero', '000000001')
            display_serie = row_data.get('serie', '001')
            display_date = row_data.get('Data', 'N/A')
            status_text = "EMISSÃO NORMAL (MOCK)" 
        else:
            display_key = "*** PENDENTE ***"
            display_num = "***"
            display_serie = "***"
            display_date = "***"
            status_text = "NFC-E A SER EMITIDA"

        fiscal_controls = []
        fiscal_controls.append(RText(status_text, weight=ft.FontWeight.BOLD, size=12, text_align=ft.TextAlign.CENTER, width=380))
        fiscal_controls.append(RText(f"Número: {display_num} Série: {display_serie} Emissão: {display_date}", size=12, text_align=ft.TextAlign.CENTER, width=380))
        fiscal_controls.append(RText("Consulte pela Chave de Acesso em:\nhttp://nfce.fazenda.sp.gov.br/consulta", size=12, text_align=ft.TextAlign.CENTER, width=380))
        fiscal_controls.append(RText("CHAVE DE ACESSO", weight=ft.FontWeight.BOLD, size=12, text_align=ft.TextAlign.CENTER, width=380))
        fiscal_controls.append(RText(display_key, font_family="Courier New", size=12, text_align=ft.TextAlign.CENTER, width=380))
        
        # 7. QR Code Logic
        qr_img = None
        qr_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ" # Rick Roll Default
        
        if is_emitted and row_data.get('fiscal_url_qrcode'):
             qr_url = row_data.get('fiscal_url_qrcode')

        if qrcode:
            try:
                qr = qrcode.QRCode(box_size=4, border=1)
                qr.add_data(qr_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                buffered = io.BytesIO()
                img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                # Use base64 string for Flet Image
                qr_img = ft.Image(src_base64=img_str, width=100, height=100) # Reduced to match print size
            except Exception as e:
                print(f"QR Gen Error: {e}")
                
        if qr_img:
            fiscal_controls.append(ft.Container(content=qr_img, alignment=ft.alignment.center))
        else:
            fiscal_controls.append(RText("<< QR CODE >>", text_align=ft.TextAlign.CENTER, width=380))

        fiscal_controls.append(RText("CONSUMIDOR NÃO IDENTIFICADO", text_align=ft.TextAlign.CENTER, size=12, width=380))
            
        # Compile all into a Receipt Container (White Paper)
        receipt_content = ft.Column(
            controls=header_controls + items_controls + fiscal_controls,
            scroll=ft.ScrollMode.AUTO,
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            width=380 
        )

        receipt_container = ft.Container(
            content=receipt_content,
            bgcolor=ft.Colors.WHITE,
            padding=20,
            border_radius=5,
            alignment=ft.alignment.center,
            border=ft.border.all(1, ft.Colors.GREY_300),
            shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK)),
            # height removed to allow expand
        )

        # Details View Layout (replaces entire dialog content)
        details_view = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: self.back_to_history(), tooltip="Voltar"),
                    ft.Text("Visualização da NFC-e", weight=ft.FontWeight.BOLD, size=18)
                ], alignment=ft.MainAxisAlignment.START),
                
                ft.Container(
                    content=receipt_container,
                    expand=True,
                    alignment=ft.alignment.center,
                    padding=10
                ),
                
                ft.Row(
                    controls=[
                        ft.ElevatedButton(
                            "Emitir NFC-e" if not is_emitted else "Imprimir NFC-e", # Change text based on state 
                            icon=ft.Icons.PRINT,
                            bgcolor=ft.Colors.TEAL_700 if is_emitted else ft.Colors.ORANGE_700, # Visual cue
                            color=ft.Colors.WHITE,
                            on_click=lambda e: self.emit_nfce_from_history(row_data, products_dict)
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER
                )
            ]),
            width=450,
            height=int(self.page.height * 0.85),
            padding=10
        )
        
        # Switch Dialog Content
        self.dialog.content = details_view
        self.dialog.title = None # Hide title in details view
        self.page.update()

    def back_to_history(self):
        # Restore original content
        self.dialog.content = self.history_view
        self.dialog.title = ft.Text("Histórico de Vendas") # Restore title
        self.page.update()

    def emit_nfce_from_history(self, row_data, products_dict):
        # We need to access FiscalManager from the main app
        if not hasattr(self.app, 'fiscal_manager'):
            print("FiscalManager not found on app instance.")
            return

        try:
            # 1. Reconstruct Items with FRESH fiscal data from DB
            items_payload = []
            
            # Use total and payment from row_data
            final_price = row_data['Preco Final']
            payment_method = row_data['Metodo de pagamento']
            
            for pid, details in products_dict.items():
                qty = details.get('quantidade', 0)
                price = details.get('preco', 0.0)
                
                # Fetch fresh details from DB to ensure we have NCM/CFOP/etc
                # details dict in history might be simplified.
                
                db_info = self.db.get_product_info(pid, self.app.shop)
                if not db_info:
                    # Fallback to history details if product deleted?
                    db_info = details
                
                item_data = {
                    'product_id': pid,
                    'categoria': db_info.get('categoria') or '',
                    'sabor': db_info.get('sabor') or '',
                    'price': price, # Use historical price
                    'quantity': qty, # Use historical qty
                    'ncm': db_info.get('ncm') or '',
                    'cest': db_info.get('cest') or '',
                    'cfop': db_info.get('cfop') or '',
                    'tax_rule': db_info.get('tax_rule') or '',
                    'barcode': db_info.get('barcode') or ''
                }
                items_payload.append(item_data)
            
            # 2. Build Payload
            shop_details = self.db.get_shop_details()
            
            payload = self.app.fiscal_manager.prepare_sale_data(
                sale_items=items_payload,
                total_price=final_price,
                payment_method=payment_method,
                shop_details=shop_details
            )
            
            # 3. Emit or Print?
            
            # Check if already emitted in DB (re-check to be safe)
            # In row_data we have 'fiscal_key'. If it's there, we just reprint.
            if row_data.get('fiscal_key'):
                 print("NFC-e already emitted. Re-printing.")
                 # Construct mock result from existing data to feed printer
                 result = {
                     'success': True,
                     'chave_acesso': row_data.get('fiscal_key'),
                     'url_qrcode': row_data.get('fiscal_url_qrcode'),
                     'xml_content': row_data.get('fiscal_xml'),
                     'numero': 'REPRINT',
                     'serie': 'REPRINT',
                     'data_emissao': datetime.datetime.now().isoformat()
                 }
            else:
                # Actual Emission
                result = self.app.fiscal_manager.emit_nfce(payload)
                if result.get('success'):
                     # Save to DB
                     self.db.update_sale_fiscal_data(row_data['timestamp'], result)
                     # Manually trigger unsynced?
                     if hasattr(self.app, 'mark_unsynced'):
                         self.app.mark_unsynced()

            self.back_to_history() # Return to list (will reload list and show updated data)
            self.load_data() # Force reload to pick up new key status
            
            if result.get('success'):
                self.page.snack_bar = ft.SnackBar(ft.Text(f"NFC-e Emitida! Key: {result['chave_acesso'][:10]}... Imprimindo..."), bgcolor=ft.Colors.GREEN)
                # Print Mock Receipt
                if hasattr(self.app, 'printer') and self.app.printer:
                     self.app.printer.print_nfce_mock(result, payload, shop_details)
                else:
                    print("Printer not configured in app.")
            else:
                self.page.snack_bar = ft.SnackBar(ft.Text(f"Erro NFC-e: {result.get('message')}"), bgcolor=ft.Colors.RED)
            
            self.page.snack_bar.open = True
            self.page.update()

        except Exception as e:
            print(f"Error preparing NFC-e: {e}")
            import traceback
            traceback.print_exc()
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Erro ao preparar NFC-e: {e}"), bgcolor=ft.Colors.RED)
            self.page.snack_bar.open = True
            self.page.update()

    def show(self):
        self.page.open(self.dialog)
        self.page.update()