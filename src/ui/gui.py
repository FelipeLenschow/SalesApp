import flet as ft
from datetime import datetime
import threading
import time
import unicodedata
import src.ui.history as hist

# Local imports
from src.aws_db import Database
import src.aws_db as aws_db_module
import src.ui.main_window
import src.ui.product_editor
import src.ui.shop_selection
import src.sale as sale
import src.payment as payment
import src.ui.sync_client as sync_client

import src.db_sqlite as sqlite_db

Version = "1.1.0"


class ProductApp:
    def __init__(self, page: ft.Page):
        self.Version = Version
        self.page = page

        self.product_widgets = {}
        self.sale_frame = ft.Column()

        # Initialize
        self.sale = None
        self.pay = None
        self.stored_sales = []

        # Dictionary to keep track of widgets for each product
        self.product_widgets = {}

        self.manual_add_count = 0
        self.manual_add_list = []
        # State flags
        self.is_editing = False # Flag to track if edit dialog is open
        self.last_barcode_scan = 0 # Timestamp of last barcode scan to prevent instant closing
        
        # Global Scanner Buffer
        self.scan_buffer = ""
        self.is_scanning = False
        self.last_scan_time = 0
        
        # Initialize Cloud DB for price suggestions
        try:
            self.aws_db = Database()
        except:
            self.aws_db = None
            print("Failed to init AWS DB for suggestions")


        # Keyboard event handling
        self.page.on_keyboard_event = self.on_key_event
        self.page.on_resized = self._handle_resize
        self.page.on_window_event = self.on_window_event

        # Initialize UI

        # Check for saved shop in LOCAL DB
        local_conn = sqlite_db.Database()
        saved_shop = local_conn.get_config('current_shop')
        
        if saved_shop:
             self.product_db = local_conn  # Use local DB
             self.shop = saved_shop
             self.pay = payment.Payment(self, self.shop)
             
             self.ui = src.ui.main_window.MainWindow(self, page)
             self.ui.build()
             self.page.window.full_screen = True
             self.page.window.min_width = 1000
             self.page.window.min_height = 650
             if hasattr(self.ui, 'update_custom_buttons_visibility'):
                self.ui.update_custom_buttons_visibility()
             self.page.update()
             self.editor = src.ui.product_editor.ProductEditor(self)
             self.editor = src.ui.product_editor.ProductEditor(self)
             self.new_sale()
        else:
            # Check if we need to download DB (first run or reset)
            need_download = True
            try:
                # Check if we have any products locally
                with local_conn.get_connection() as conn:
                    count = conn.execute("SELECT count(*) FROM products").fetchone()[0]
                    if count > 0:
                        need_download = False
            except:
                pass

            if need_download:
                self.show_loading_screen()
            else:
                self.product_db = local_conn # Use local DB even for selection (it has data now)
                selection_ui = src.ui.shop_selection.ShopSelection(self, self.page)
                selection_ui.show()

        # Start auto-sync thread
        self.sync_manager = sync_client.SyncManager(self)
        threading.Thread(target=self.sync_manager.start_auto_sync, daemon=True).start()


    def show_loading_screen(self):
        self.page.clean()
        self.page.bgcolor = "#8b0000"
        self.page.window.full_screen = False
        self.page.window.width = 400
        self.page.window.height = 300
        self.page.window.center()
        
        status_text = ft.Text("Conectando ao servidor...", color="white", size=16)
        progress_bar = ft.ProgressBar(width=300, color="amber", bgcolor="#440000")
        
        self.page.add(
            ft.Column(
                [
                    ft.Text("Configuração Inicial", size=24, weight="bold", color="white"),
                    ft.Text("Baixando banco de dados completo...", color="white70"),
                    ft.Container(height=20),
                    progress_bar,
                    ft.Container(height=10),
                    status_text
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True
            )
        )
        self.page.update()
        
        def download_task():
            try:
                # 1. Connect AWS
                status_text.value = "Conectando AWS..."
                self.page.update()
                aws_conn = aws_db_module.Database()
                
                # 2. Fetch
                status_text.value = "Baixando produtos (Isso pode demorar)..."
                self.page.update()
                
                def on_progress(count):
                    status_text.value = f"Baixado: {count} produtos..."
                    self.page.update()

                products = aws_conn.get_all_products_grouped(progress_callback=on_progress)
                
                # 3. Save Local
                status_text.value = "Salvando no cache local..."
                self.page.update()
                local_conn = sqlite_db.Database()
                local_conn.replace_all_products(products)
                
                # FIX: Set timestamp so next sync is Delta, not Full
                local_conn.set_last_sync_timestamp(datetime.now().isoformat())
                
                # 4. Proceed
                status_text.value = "Concluído!"
                self.page.update()
                time.sleep(1)
                
                self.product_db = local_conn
                selection_ui = src.ui.shop_selection.ShopSelection(self, self.page)
                
                # Must run UI updates on main thread usually, but Flet often handles simple app struct.
                # Ideally we clear and show selection.
                self.page.clean()
                selection_ui.show()
                
            except Exception as e:
                status_text.value = f"Erro: {e}"
                status_text.color = "red"
                progress_bar.value = 0
                self.page.update()
                print(f"Download error: {e}")

        threading.Thread(target=download_task, daemon=True).start()


    def _handle_resize(self, e=None):
        # Check if window was maximized by OS and switch to full screen
        if self.page.window.maximized:
            self.page.window.maximized = False
            self.page.window.full_screen = True
            if hasattr(self, 'ui') and hasattr(self.ui, 'update_custom_buttons_visibility'):
                self.ui.update_custom_buttons_visibility()
            self.page.update()



    def on_window_event(self, e):
        if e.data == "maximize":
            self.page.window.maximized = False
            self.page.window.full_screen = True
            if hasattr(self, 'ui') and hasattr(self.ui, 'update_custom_buttons_visibility'):
                self.ui.update_custom_buttons_visibility()
            self.page.update()

    def show_error(self, message):
        print(f"Showing message: {message}")
        is_error = "Erro" in message or "error" in message.lower() or "exception" in message.lower()
        color = ft.Colors.RED if is_error else ft.Colors.GREEN
        
        try:
            if hasattr(self, 'status_text') and self.status_text:
                # Use a short message for the status text area
                short_msg = "Sincronização realizada com sucesso!" if not is_error else "Erro na sincronização."
                if len(message) < 50: short_msg = message
                
                self.status_text.value = short_msg
                self.status_text.color = color
                self.status_text.update()

                def clear_status():
                    time.sleep(10)
                    try:
                        if self.status_text.value == short_msg:
                            self.status_text.value = ""
                            self.status_text.update()
                    except:
                        pass
                threading.Thread(target=clear_status, daemon=True).start()

        except Exception as e:
            print(f"Failed to update status_text: {e}")

        self.page.snack_bar = ft.SnackBar(content=ft.Text(message), bgcolor=color, duration=10000)
        self.page.snack_bar.open = True
        self.page.update()

    def run_sync(self, e):
        """
        Trigger Manual Sync via SyncManager.
        """
        self.sync_manager.run_sync()

    def mark_unsynced(self):
        self.sync_manager.mark_unsynced()

    def select_product(self, product):
        self.ui.hide_dropdown()
        self.sale.add_product(product)
        self.update_sale_display(focus_on_=product)
        self.search_results.controls.clear()
        self.barcode_entry.value = ""
        self.page.update()

    def search_products(self, e=None, search_term=None):
        # Clear previous results
        self.search_results.controls.clear()

        if search_term:
            # Normalize search term
            search_term = self.strip_accents(search_term.lower())
            if ',' in search_term:
                search_term = search_term.replace(',', '.')

            # Filter products
            filtered = self.product_db.search_products(search_term, self.shop)

            # Store filtered products
            self.filtered_products = filtered

            # Populate dropdown with ListTiles
            for product in filtered:
                self.search_results.controls.append(
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.SEARCH),
                        title=ft.Text(
                            f"{product['categoria']} "
                            f"({product['sabor']})",
                            weight=ft.FontWeight.BOLD,
                        ),
                        subtitle=ft.Text(
                            f"R${product['preco']:.2f} | "
                            f"Cod: {product['barcode']}"
                        ),
                        on_click=lambda e, p=product: self.select_product(p),
                        text_color=ft.Colors.BLACK
                    )
                )

            self.ui.show_dropdown()
        else:
            self.ui.hide_dropdown()

        self.page.update()

    def handle_search(self):
        barcode = self.barcode_entry.value.strip()  # Use single variable
        if not barcode.isdigit():
            self.search_products(search_term=barcode)
            self.ui.show_dropdown()
        else:
            self.ui.hide_dropdown()

    def handle_barcode(self, event=None, override_barcode=None):
        if self.is_editing:
             return

        # Update timestamp to prevent on_blur from closing logic
        self.last_barcode_scan = time.time()
        
        if override_barcode is not None:
            barcode = override_barcode.strip()
        else:
            barcode = self.barcode_entry.value.strip()

        if not barcode:
            return

        # Do NOT clear value here immediately

        # Handle manual value entry
        if ',' in barcode or '.' in barcode:
            try:
                value = float(barcode.replace(",", "."))
                self.manual_add_count += 1
                product = {
                    'product_id': f'Manual_{self.manual_add_count}',
                    'categoria': 'Não cadastrado',
                    'sabor': '',
                    'preco': value,
                    'barcode': f'Manual_{self.manual_add_count}'
                }
                self.manual_add_list.append(product)
                self.sale.add_product(product)
                self.update_sale_display(focus_on_=product)
                
                # Clear value only after successful manual add
                self.barcode_entry.value = ""
                self.page.update()
                return
            except ValueError:
                pass

        # Handle barcode input
        if barcode.isdigit():
            # Handle barcode search
            matching_products = self.product_db.get_products_by_barcode_and_shop(barcode, self.shop)

            if matching_products: # check if list is not empty
                if len(matching_products) == 1:
                    # Adiciona unico produto encontrado
                    product = matching_products[0]
                    self.sale.add_product(product)
                    self.update_sale_display(focus_on_=product)
                    
                    # Clear value after successful single product add
                    self.barcode_entry.value = ""

                    # CHECK FOR ZERO PRICE AND SUGGEST - REMOVED (Moved to widget creation)
                else:
                    # Varios produtos encontrados para o mesmo codigo
                    # DO NOT CLEAR VALUE HERE - keep it so dropdown stays open
                    self.search_results.controls.clear()
                    for product in matching_products:
                        self.search_results.controls.append(
                            ft.ListTile(
                                leading=ft.Icon(ft.Icons.SEARCH),
                                title=ft.Text(
                                    f"{product['categoria']} "
                                    f"({product['sabor']})",
                                    weight=ft.FontWeight.BOLD,
                                ),
                                subtitle=ft.Text(
                                    f"R${product['preco']:.2f} | "
                                    f"Cod: {product['barcode']}"
                                ),
                                on_click=lambda e, p=product: self.select_product(p),
                                text_color=ft.Colors.BLACK  # Fix: Make text visible
                            )
                        )
                    self.ui.show_dropdown()
            else:
                # Nenhum produto encontrado
                # Clear value before error dialog? Or keep it?
                # Original logic cleared it. Let's clear it to allow re-scan cleanly or manual edit in dialog.
                self.barcode_entry.value = ""
                self.confirm_read_error(barcode=barcode)
        else:
            # Handle text search enter (Done searching)
            self.ui.hide_dropdown()

        self.page.update()

    def on_key_event(self, e: ft.KeyboardEvent):
        # GLOBAL SCANNER LOGIC
        # Only enable global scanner if NOT in an editing dialog
        if not self.is_editing:
            if e.key == "F12":
                # If we are already scanning, this might be a repeat key signal from the scanner
                # Ignore it to avoid clearing the buffer mid-scan
                if self.is_scanning:
                     self.last_scan_time = time.time()
                     return
                     
                # Start of scan sequence
                self.is_scanning = True
                self.scan_buffer = ""
                self.last_scan_time = time.time()
                
                # Move focus to hidden target to prevent visual noise
                try:
                    self.scanner_focus_target.focus()
                    self.scanner_focus_target.update()
                except:
                    pass
                return

            if self.is_scanning:
                # Check for timeout (scanner is fast, manual typing is slow)
                if time.time() - self.last_scan_time > 0.3: # 300ms timeout
                    self.is_scanning = False
                    self.scan_buffer = ""
                    # Fallthrough to normal handling (maybe it was just a manual F12 press?)
                else:
                    self.last_scan_time = time.time()
                    if e.key == "Enter":
                        # End of scan sequence
                        # Sanitize: Strip non-digits (e.g. trailing 'C' or other headers)
                        raw_code = self.scan_buffer
                        final_code = "".join(filter(str.isdigit, raw_code))
                        
                        self.is_scanning = False
                        self.scan_buffer = ""
                        
                        if final_code:
                            # Force update to clear any garbage from focused fields
                            # (The characters might have been typed into the field before we caught them)
                            # We rely on update_sale_display to reset the values from backend
                            self.handle_barcode(override_barcode=final_code)
                        return
                    else:
                        # Append character to buffer
                        if len(e.key) == 1:
                            self.scan_buffer += e.key
                        return

        # Normal Key Handling
        # REMOVED "End" key binding as requested
        if e.key == "Tab" and not self.is_editing:
             self.handle_barcode()
        elif e.key == "F11":
            self.finalize_sale(self.sale.id)
        elif e.key == "F12" or e.key == "\x02" or (e.ctrl and e.key == "B"):
            if not self.is_editing:
                self.barcode_entry.focus()
        elif (e.key == "\x03" or e.key == "Tab") and not self.is_editing:
             self.handle_barcode()
        self.page.update()

    def update_sale_display(self, focus_on_=None, skip_price_update_for=None):
        # Aplica promoções e calcula o preço final
        final_price = self.sale.calculate_total()
        self.final_price_label.value = f"R${final_price:.2f}"

        self.payment_method_var.value = self.sale.payment_method
        self.page.update()

        # Atualiza widgets existentes ou cria novos
        for product_id in self.sale.current_sale.keys():
            details = None
            product_series = None

            # Try to fetch from DB first (UUIDs are strings now)
            product_series = self.product_db.get_product_info(product_id, self.sale.shop)

            # If not in DB, check manual add list
            if not product_series:
                 for product in self.manual_add_list:
                    if product_id == product['product_id']:
                        product_series = product
                        break
            
            if product_series is None:
                 print(f"Product not found for ID: {product_id}")
                 continue # Skip if not found


            details = {
                'categoria': product_series.get('categoria', ''),
                'sabor': product_series.get('sabor', ''),
                'preco': self.sale.current_sale[product_id]['preco'],
                'quantidade': self.sale.current_sale[product_id]['quantidade'],
                'product_id': product_id,
                'barcode': product_series.get('barcode', '')
            }
            self.create_or_update_product_widget(product_id, details, skip_price_update=(product_id == skip_price_update_for))

        # Se um produto foi passado, focar no widget de quantidade correspondente
        if focus_on_ is not None:
            product_id = focus_on_['product_id']
            if product_id in self.product_widgets:
                qty_field = self.product_widgets[product_id]['quantity_field']
                qty_field.focus()
                qty_field.selection_start = 0
                qty_field.selection_end = len(qty_field.value)
                qty_field.update()

        if self.valor_pago_entry.value:
            self.calcular_troco()

        self.create_or_update_sale_widgets()
        self.page.update()

    def create_or_update_product_widget(self, product_id, details, skip_price_update=False):

        if product_id not in self.product_widgets:
            product_text = ft.Text(
                value=f"{details['categoria']} - {details['sabor']}" if details['sabor']
                else details['categoria'],
                color="white",
                size=22,
                weight="bold",
                expand=True
            )

            # Layout vars
            font_size = 18

            # Product Name (implied by previous context, but target is specific controls)
            
            # Create quantity controls
            quantity_field = ft.TextField(
                value=str(details['quantidade']),
                width=70,
                text_size=font_size,
                on_change=lambda e, row=product_id: self.update_quantity_dynamic(row, e.control.value)
            )

            # Price display
            price_text = ft.TextField(
                value=f"{details['preco']:.2f}",
                width=120,
                text_size=font_size,
                text_align=ft.TextAlign.RIGHT,
                prefix_text="R$ ",
                on_change=lambda e, row=product_id: self.update_price_dynamic(row, e.control.value)
            )

            # Delete button
            delete_button = ft.IconButton(
                icon=ft.Icons.DELETE_FOREVER,
                icon_color="red",
                on_click=lambda e, row=product_id: self.delete_product(row)
            )

            # Create row
            product_row = ft.Row(
                controls=[
                    product_text,
                    quantity_field,
                    price_text,
                    delete_button,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True
            )

            # Add edit button if not manual entry
            if not str(product_id).startswith('Manual'):
                edit_button = ft.IconButton(
                    icon=ft.Icons.EDIT,
                    icon_color="blue",
                    on_click=lambda e, row=product_id: self.editor.open(product_id=row)
                )
                product_row.controls.insert(3, edit_button)
            else:
                 # Spacer to keep alignment
                 spacer = ft.IconButton(
                    icon=ft.Icons.EDIT,
                    icon_color=ft.Colors.TRANSPARENT,
                    disabled=True
                 )
                 product_row.controls.insert(3, spacer)

            # Add row to container
            self.widgets_vendas.controls.append(product_row)
            self.widgets_vendas.update()

            # Store reference in dictionary
            self.product_widgets[product_id] = {
                'product_text': product_text,
                'quantity_field': quantity_field,
                'price_text': price_text,
                'delete_button': delete_button,
                'row': product_row
            }

            # Check for Zero Price and Suggest (Moved from handle_barcode)
            if details.get('preco', 0) <= 0 and self.aws_db:
                barcode = details.get('barcode', '')
                # Ensure we have a valid barcode to check
                if barcode and str(barcode).isdigit():
                    def check_other_prices():
                        try:
                            # We need product dict for the dialog
                            # Re-construct minimal product dict or pass 'details' if adapted
                            # 'show_price_suggestions' uses 'product' dict for update logic
                            # It expects 'product_id' and 'categoria' for text
                            
                            suggestions = self.aws_db.get_prices_from_other_stores(barcode)
                            if suggestions:
                                # Show Dialog
                                # Pass 'details' because it has product_id and others
                                self.show_price_suggestions(suggestions, details)
                        except Exception as e:
                            print(f"Error suggesting prices: {e}")

                    threading.Thread(target=check_other_prices, daemon=True).start()

        else:
            # Update existing widgets
            widgets = self.product_widgets[product_id]

            # Update product text
            widgets['product_text'].value = (
                f"{details['categoria']} - {details['sabor']}"
                if details['sabor']
                else details['categoria']
            )

            # Update quantity field
            widgets['quantity_field'].value = str(details['quantidade'])

            # Determine price and color
            price = details['preco']
            color = "white"

            # Update price display
            if not skip_price_update:
                if widgets['price_text'].value != f"{price:.2f}":
                    widgets['price_text'].value = f"{price:.2f}"
            # widgets['price_text'].color = color

            # Force UI updates
            widgets['product_text'].update()
            widgets['quantity_field'].update()
            widgets['price_text'].update()

    def calcular_troco(self, event=None):
        try:
            valor_pago = float(self.valor_pago_entry.value.replace(",", "."))
            troco = valor_pago - self.sale.final_price
            if troco < 0.0:
                self.troco_text.value = f"Troco: R${troco:.2f}"
                self.troco_text.color = ft.Colors.RED
            else:
                self.troco_text.value = f"Troco: R${troco:.2f}"
                self.troco_text.color = ft.Colors.GREEN
        except ValueError:
            self.troco_text.value = ""
        self.troco_text.update()

    def strip_accents(self, text):
        text = unicodedata.normalize('NFD', text) \
            .encode('ascii', 'ignore') \
            .decode("utf-8")
        return str(text)

    def confirm_read_error(self, barcode):
        self.is_editing = True

        def reset_editing(e=None):
            self.is_editing = False
            self.page.update()

        def close_dlg(e=None):
            self.page.close(dlg)
            reset_editing()

        def compare(e):
            entered_barcode = barcode_input.value
            if entered_barcode:
                if entered_barcode == barcode:
                    self.page.close(dlg)
                    self.is_editing = False # Reset before opening editor
                    self.editor.open(barcode=entered_barcode)
                else:
                    self.page.close(dlg)
                    self.is_editing = False
                    self.barcode_entry.value = entered_barcode
                    self.handle_barcode()

        barcode_input = ft.TextField(
            label="Código de Barras",
            autofocus=True,
            on_submit=compare
        )

        dlg = ft.AlertDialog(
            title=ft.Text("Possível erro de leitura"),
            content=ft.Column([
                ft.Text("Escaneie novamente", size=12, weight="bold"),
                barcode_input
            ], height=150, tight=True),
            actions=[
                ft.TextButton("Confirmar", on_click=compare),
                ft.TextButton("Cancelar", on_click=close_dlg)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=reset_editing
        )

        self.page.open(dlg)
        self.page.update()

    def update_quantity_dynamic(self, product_id, quantity_var):
        if self.is_scanning:
            return
        try:
            new_quantity = int(quantity_var)
            if new_quantity <= 0:
                new_quantity = 0
                self.delete_product(product_id)
            if product_id in self.sale.current_sale:
                self.sale.current_sale[product_id]['quantidade'] = max(new_quantity, 0)
            self.update_sale_display()
        except ValueError:
            if quantity_var != "":
                self.show_error(f"Por favor, insira um número válido. ({quantity_var})")

    def update_price_dynamic(self, product_id, price_var):
        if self.is_scanning:
            return
        try:
            # Handle comma/dot and currency symbols if present
            clean_price = price_var.replace('R$', '').replace(' ', '').replace(',', '.')
            if not clean_price: 
                return

            new_price = float(clean_price)
            if new_price < 0:
                new_price = 0.0
            
            self.sale.update_price(product_id, new_price)
            # Update entire display to recalculate totals, but be careful with focus
            # For now, we update everything to ensure consistency
            self.update_sale_display(skip_price_update_for=product_id)
        except ValueError:
            # Allow "unfinished" numbers that are just a decimal point (from . or ,)
            if clean_price == '.':
                pass
            elif price_var != "":
                self.show_error(f"Por favor, insira um preço válido. ({price_var})")

    def delete_product(self, product_id):
        self.sale.remove_product(product_id)
        if product_id in self.product_widgets:
            product_row = self.product_widgets[product_id]['row']
            self.widgets_vendas.controls.remove(product_row)
            del self.product_widgets[product_id]
            self.widgets_vendas.update()

        self.update_sale_display()

    def open_sale(self, id, save_current=True):
        sale_to_open = next((sale for sale in self.stored_sales if sale.id == id), None)
        if sale_to_open:
            self.new_sale(sale_to_open=sale_to_open, save_current=save_current)
            self.update_sale_display()

    def create_or_update_sale_widgets(self):
        # Scaled dimensions
        tab_height = 40
        tab_width = 210
        icon_size = 24
        font_size = 24

        for sale in self.stored_sales:
            sale_key = f"tab_{sale.id}"
            existing = next(
                (c for c in self.stored_sales_row.controls
                 if getattr(c, 'key', None) == sale_key),
                None
            )

            if not existing:
                # Create main tab container
                tab_container = ft.Container(
                    key=sale_key,
                    height=tab_height,
                    width=tab_width,
                    border_radius=ft.border_radius.only(top_left=10, top_right=10),
                    bgcolor=ft.Colors.BLUE_900,
                    on_click=lambda e, s=sale: self.open_sale(s.id),
                    padding=ft.padding.only(left=18),
                    content=ft.Row(
                        controls=[
                            # Text with left padding
                            ft.Container(
                                content=ft.Text(
                                    f"R${sale.final_price:.2f}",
                                    weight=ft.FontWeight.W_700,
                                    size=font_size,
                                ),
                            ),
                            # Button group with minimal spacing
                            ft.Row(
                                controls=[
                                    ft.IconButton(
                                        icon=ft.Icons.CHECK,
                                        icon_size=icon_size,
                                        icon_color=ft.Colors.GREEN_300,
                                        on_click=lambda e, s=sale: self.finalize_sale(s.id),
                                        tooltip="Finalize Sale",
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.CLOSE,
                                        icon_size=icon_size,
                                        icon_color=ft.Colors.RED_300,
                                        on_click=lambda e, s=sale: self.delete_stored_sale(s.id),
                                        tooltip="Close Tab"
                                    )
                                ],
                                spacing=0,
                                tight=True,
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )

                self.stored_sales_row.controls.append(tab_container)
            else:
                # Update existing tab
                row = existing.content
                text_container = row.controls[0]
                price_text = text_container.content
                price_text.value = f"R${sale.final_price:.2f}"
                if self.sale.id == sale.id:
                    existing.bgcolor = ft.Colors.BLUE_900
                else:
                    existing.bgcolor = ft.Colors.BLUE_700

        self.stored_sales_row.update()
        self.page.update()

    def delete_stored_sale(self, sale_id):
        print(f"DEBUG: delete_stored_sale called for {sale_id}")
        print(f"DEBUG: Before delete, stored_sales IDs: {[s.id for s in self.stored_sales]}")
        
        # 1. Remove from internal list FIRST
        len_before = len(self.stored_sales)
        self.stored_sales = [s for s in self.stored_sales if s.id != sale_id]
        len_after = len(self.stored_sales)
        print(f"DEBUG: Removed {len_before - len_after} items. Current IDs: {[s.id for s in self.stored_sales]}")

        # 2. Try to remove the tab container
        try:
            self.stored_sales_row.controls = [
                tab for tab in self.stored_sales_row.controls
                if getattr(tab, 'key', "") != f"tab_{sale_id}"
            ]
            self.page.update()
        except Exception as e:
            print(f"Error removing tab from UI: {e}")

        # 3. Switch/New
        if self.sale and self.sale.id == sale_id: # Check self.sale exists
            print("DEBUG: Deleting current sale, switching/creating new.")
            if self.stored_sales:
                self.open_sale(self.stored_sales[-1].id, save_current=False)
            else:
                self.new_sale(save_current=False)

    def cobrar(self):
        if not self.sale.current_sale:
            self.show_error("Nenhum produto na venda!")
            return

        final_price = self.sale.calculate_total()

        payment_content = ft.Column([
            ft.Text(f"Valor Total: R${final_price:.2f}", size=18),
            ft.Dropdown(
                label="Método de Pagamento",
                options=[
                    ft.dropdown.Option("Dinheiro"),
                    ft.dropdown.Option("Pix"),
                    ft.dropdown.Option("Cartão")
                ],
                value=self.sale.payment_method,
                on_change=lambda e: self.update_payment_method(method=e.control.value),
                disabled=True
            ),
            ft.TextField(
                label="Valor Recebido",
                on_change=self.calcular_troco
            )
        ])

        def confirm_payment(e):
            self.page.close(dlg)
            self.finalize_sale(self.sale.id)
            self.page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Confirmar Pagamento"),
            content=payment_content,
            actions=[
                ft.TextButton("Confirmar", on_click=confirm_payment),
                ft.TextButton("Cancelar", on_click=lambda e: self.page.close(dlg))
            ]
        )
        self.page.open(dlg)
        self.page.update()

    def show_price_suggestions(self, suggestions, product):
        """
        Shows a dialog with price suggestions from other stores.
        """
        
        def apply_price(e, price_val):
            # Close dialog first
            self.page.close(dlg)
            
            # Open editor with suggested price
            if product.get('product_id'):
                # Pass suggested_price to editor
                self.editor.open(
                    product_id=product['product_id'], 
                    suggested_price=price_val
                )
            
            self.page.update()

        rows = []
        for shop, price in suggestions.items():
            rows.append(
                ft.Row([
                    ft.Text(f"{shop}:", weight="bold", size=16),
                    ft.OutlinedButton(
                        text=f"R$ {price:.2f}",
                        on_click=lambda e, p=price: apply_price(e, p),
                        style=ft.ButtonStyle(
                            color="green",
                            padding=10
                        )
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            )

        content = ft.Column(
            [   
                ft.Text(f"O produto '{product.get('categoria', 'Desconhecido')}' está sem preço.", size=14),
                ft.Text("Clique no preço para aplicar:", size=14),
                ft.Divider(),
                ft.Column(rows),
            ],
            tight=True,
            width=300
        )

        dlg = ft.AlertDialog(
            title=ft.Text("Sugestão de Preços"),
            content=content,
            actions=[
                ft.TextButton("Fechar", on_click=lambda e: self.page.close(dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)
        self.page.update()

    def finalize_sale(self, internal_id):
        def process_sale():
            # Record sale to SQLite
            print(f"DEBUG FINALIZED: ID={internal_id}, Price={final_price:.2f}, Time={datetime.now()}")
            try:
                self.product_db.record_sale(
                    final_price=final_price, 
                    payment_method=sale.payment_method, 
                    products_dict=sale.current_sale
                )
                self.mark_unsynced()
            except Exception as e:
                print(f"Error saving sale: {e}")
                # You might want to show an error on UI here

        sale = next((sale for sale in self.stored_sales if sale.id == internal_id), None)

        if not sale:
            # Already finalized or invalid ID. Silently ignore to prevent double-click errors.
            return

        if not sale.current_sale:
            self.show_error("Sem produtos nas vendas!")
            return

        # Apply promotion and calculate final price
        final_price = sale.calculate_total()

        # Save sale details
        # Save sale logic moved to record_sale
        # Save sale details
        # Save sale logic moved to record_sale
        threading.Thread(target=process_sale).start()

        try:
            print(f"DEBUG: Starting UI cleanup for sale {internal_id}")
            self.product_widgets.clear()
            self.widgets_vendas.controls.clear()
            self.delete_stored_sale(internal_id)
            self.update_sale_display()
            print(f"DEBUG: Finished UI cleanup for sale {internal_id}")
        except Exception as e:
            print(f"ERROR in finalize_sale UI cleanup: {e}")
            import traceback
            traceback.print_exc()

    def show_sales_history(self, e=None):
        hist.SalesHistoryDialog(self.page, self).show()
        self.page.update()

    def on_payment_method_change(self, e):
        method = self.payment_method_var.value
        # Logic: Enable Cobrar only for Pix, Debit, Credit
        if method in ["Pix", "Débito", "Crédito"]:
            self.cobrar_btn.disabled = False
        else:
            self.cobrar_btn.disabled = True
        
        self.cobrar_btn.update()
        self.update_payment_method(method=method)

    def update_payment_method(self, e=None, method=None):
        if method:
            self.payment_method_var.value = method
            self.sale.payment_method = method
            # Re-calculate final price (though it shouldn't change without promos, it's safe to keep)
            self.sale.calculate_total() 
            self.update_sale_display()

        if self.payment_method_var.value == "Dinheiro":
            self.valor_pago_entry.focus()

    def store_sale(self):
        if not any(s.id == self.sale.id for s in self.stored_sales):
            self.stored_sales.append(self.sale)
            self.create_or_update_sale_widgets()

    def new_sale(self, e=None, sale_to_open=None, save_current=True):

        if sale_to_open is None:
            if save_current and self.sale: # Save old if requested and exists
                 self.store_sale()
            self.sale = sale.Sale(self.product_db, self.shop)
            self.store_sale() # Store the NEW one
        else:
            if save_current:
                self.store_sale()
            self.sale = sale_to_open

        # Clear UI elements
        self.product_widgets.clear()
        self.widgets_vendas.controls.clear()
        self.valor_pago_entry.value = ""
        self.payment_method_var.value = ""
        self.troco_text.value = ""

        # Refresh displays
        self.update_sale_display()
        self.barcode_entry.focus()

    def update_status(self, new_status):
        status_mapping = {
            "OPEN": "Em aberto",
            "FINISHED": "Finalizado",
            "ON_TERMINAL": "Na maquininha",
            "CANCELED": "Cancelada",
            "PROCESSING": "Processando"
        }
        self.status_text.value = status_mapping.get(new_status, new_status)
        self.status_text.update()
