
import flet as ft
import pandas as pd
from datetime import datetime
import threading
import time
import unicodedata
import src.ui.history as hist

# Local imports
import src.db_sqlite as db  # Changed import
import src.ui.main_window
import src.ui.product_editor
import src.ui.shop_selection
import src.sale as sale
import src.payment as payment
import src.ui.sync_client as sync_client

# Constants for UI scaling
BASE_WIDTH = 1920
BASE_HEIGHT = 1080
Version = "0.6.0"  # Increment version


class ProductApp:
    def __init__(self, page: ft.Page):
        self.Version = Version
        self.page = page

        self.product_widgets = {}
        self.sale_frame = ft.Column()

        # Initialize product database
        self.product_db = db.Database()  # Use new SQLite Database

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

        # Keyboard event handling
        self.page.on_keyboard_event = self.on_key_event
        self.page.on_resized = self._perform_resize
        self._resize_timer = None

        # Initialize UI
        saved_shop = self.product_db.get_config('current_shop')
        if saved_shop:
             self.shop = saved_shop
             self.pay = payment.Payment(self, self.shop)
             self.ui = src.ui.main_window.MainWindow(self, page)
             self.ui.build()
             self.editor = src.ui.product_editor.ProductEditor(self)
             self.new_sale()
        else:
            selection_ui = src.ui.shop_selection.ShopSelection(self, self.page)
            selection_ui.show()

        # Start auto-sync thread
        # Start auto-sync thread
        self.sync_manager = sync_client.SyncManager(self)
        threading.Thread(target=self.sync_manager.start_auto_sync, daemon=True).start()

    def _perform_resize(self, e=None):
        # Only resize if we are in the main app (shop selected)
        if not getattr(self, 'shop', None):
            return

        screen_width = self.page.window.width
        screen_height = self.page.window.height
        
        # Guard against transition glitches
        if screen_width < 1000:
            screen_width = 1920
            screen_height = 1080

        # Update scale factor
        self.scale_factor = 0.8 * min(screen_width / BASE_WIDTH, screen_height / BASE_HEIGHT)

        # Rebuild UI
        self.page.clean()
        self.product_widgets = {} 
        self.ui = src.ui.main_window.MainWindow(self, self.page)
        self.ui.build()
        self.editor = src.ui.product_editor.ProductEditor(self)
        
        # Restore Data Display
        if self.sale:
             self.update_sale_display()
        
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

    def open_sync_dialog(self, e):
        self.sync_manager.open_sync_dialog(e)

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
            for _, product in filtered.iterrows():
                self.search_results.controls.append(
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.SEARCH),
                        title=ft.Text(
                            f"{product[('Todas', 'Categoria')]} "
                            f"({product[('Todas', 'Sabor')]})",
                            weight=ft.FontWeight.BOLD,
                        ),
                        subtitle=ft.Text(
                            f"R${product[(self.shop, 'Preco')]:.2f} | "
                            f"Cod: {product[('Todas', 'Codigo de Barras')]}"
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

    def handle_barcode(self, event=None):
        barcode = self.barcode_entry.value.strip()

        if not barcode:
            return

        self.barcode_entry.value = ""

        # Handle manual value entry
        if ',' in barcode or '.' in barcode:
            try:
                value = float(barcode.replace(",", "."))
                self.manual_add_count += 1
                product = {
                    ('Metadata', 'Product ID'): f'Manual_{self.manual_add_count}',
                    ('Todas', 'Categoria'): 'Não cadastrado',
                    ('Todas', 'Sabor'): '',
                    (self.shop, 'Preco'): value,
                    (self.shop, 'Preco'): value
                }
                self.manual_add_list.append(product)
                self.sale.add_product(product)
                self.update_sale_display(focus_on_=product)
                return
            except ValueError:
                pass

        # Handle barcode input
        if barcode.isdigit():
            # Handle barcode search
            matching_products = self.product_db.get_products_by_barcode_and_shop(barcode, self.shop)

            if not matching_products.empty:
                if len(matching_products) == 1:
                    # Adiciona unico produto encontrado
                    product = matching_products.iloc[0]
                    self.sale.add_product(product)
                    self.update_sale_display(focus_on_=product)
                else:
                    # Varios produtos encontrados para o mesmo codigo
                    for _, product in matching_products.iterrows():
                        self.search_results.controls.append(
                            ft.ListTile(
                                title=ft.Text(product[('Todas', 'Sabor')]),
                                subtitle=ft.Text(f"R${product[(self.shop, 'Preco')]}"),
                                on_click=lambda e, p=product: self.select_product(p),
                            )
                        )
                    self.ui.show_dropdown()
            else:
                # Nenhum produto encontrado
                self.confirm_read_error(barcode=barcode)

            self.page.update()

    def on_key_event(self, e: ft.KeyboardEvent):
        if e.key == "Enter":
            self.handle_barcode()
        elif e.key == "F5":
            self.update_payment_method(method="Débito")
        elif e.key == "F6":
            self.update_payment_method(method="Crédito")
        elif e.key == "F7":
            self.update_payment_method(method="Pix")
        elif e.key == "F8":
            self.update_payment_method(method="Dinheiro")
        elif e.key == "F9":
            self.cobrar()
        elif e.key == "F10":
            self.new_sale()
        elif e.key == "F11":
            self.finalize_sale(self.sale.id)
        elif e.key == "F12":
            if not self.is_editing:
                self.barcode_entry.focus()
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

            if type(product_id) != str:
                # Assuming product_id (int)
                product_series = self.product_db.get_product_info(product_id, self.sale.shop)
            else:
                # Quando ha produtos manualmente adicionados
                for product in self.manual_add_list:
                    if product_id == product[('Metadata', 'Product ID')]:
                        product_series = product
            
            if product_series is None:
                 print(f"Product not found for ID: {product_id}")
                 continue # Skip if not found


            details = {
                'categoria': product_series[('Todas', 'Categoria')],
                'sabor': product_series[('Todas', 'Sabor')],
                'preco': self.sale.current_sale[product_id]['preco'],
                'quantidade': self.sale.current_sale[product_id]['quantidade'],
                'product_id': product_id
            }
            self.create_or_update_product_widget(product_id, details, skip_price_update=(product_id == skip_price_update_for))

        # Se um produto foi passado, focar no widget de quantidade correspondente
        if focus_on_ is not None:
            product_id = focus_on_[('Metadata', 'Product ID')]
            if product_id in self.product_widgets:
                self.product_widgets[product_id]['quantity_field'].focus = True
                self.widgets_vendas.update()

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
                size=18,
                weight="bold",
                expand=True
            )

            # Layout vars
            font_size = 30 * self.scale_factor

            # Product Name (implied by previous context, but target is specific controls)
            
            # Create quantity controls
            quantity_field = ft.TextField(
                value=str(details['quantidade']),
                width=120 * self.scale_factor,
                text_size=font_size,
                on_change=lambda e, row=product_id: self.update_quantity_dynamic(row, e.control.value)
            )

            # Price display
            price_text = ft.TextField(
                value=f"{details['preco']:.2f}",
                width=180 * self.scale_factor,
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
        def compare(e):
            entered_barcode = barcode_input.value
            if entered_barcode:
                if entered_barcode == barcode:
                    self.page.close(dlg)
                    self.edit_product(barcode=entered_barcode)
                else:
                    self.page.close(dlg)
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
                ft.Text("Escaneie novamente", size=20, weight="bold"),
                barcode_input
            ], height=150, tight=True),
            actions=[
                ft.TextButton("Confirmar", on_click=compare),
                ft.TextButton("Cancelar", on_click=lambda e: self.page.close(dlg))
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.open(dlg)
        self.page.update()

    def update_quantity_dynamic(self, product_id, quantity_var):
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

    def open_sale(self, id):
        sale_to_open = next((sale for sale in self.stored_sales if sale.id == id), None)
        if sale_to_open:
            self.new_sale(sale_to_open=sale_to_open)
            self.update_sale_display()

    def create_or_update_sale_widgets(self):
        # Scaled dimensions
        tab_height = 70 * self.scale_factor
        tab_width = 350 * self.scale_factor
        icon_size = 40 * self.scale_factor
        font_size = 40 * self.scale_factor

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
                    padding=ft.padding.only(left=30 * self.scale_factor),
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
        # Remove the tab container
        self.stored_sales_row.controls = [
            tab for tab in self.stored_sales_row.controls
            if tab.key != f"tab_{sale_id}"
        ]

        # Remove from internal list
        self.stored_sales = [s for s in self.stored_sales if s.id != sale_id]

        # Update interface
        self.page.update()

        # If deleting the current sale, switch to another or create new if empty
        if self.sale.id == sale_id:
            if self.stored_sales:
                self.open_sale(self.stored_sales[-1].id)
            else:
                self.new_sale()

    def cobrar(self):
        if not self.sale.current_sale:
            self.show_error("Nenhum produto na venda!")
            return

        final_price = self.sale.calculate_total()

        payment_content = ft.Column([
            ft.Text(f"Valor Total: R${final_price:.2f}", size=4),
            ft.Dropdown(
                label="Método de Pagamento",
                options=[
                    ft.dropdown.Option("Dinheiro"),
                    ft.dropdown.Option("Pix"),
                    ft.dropdown.Option("Cartão")
                ],
                value=self.sale.payment_method,
                on_change=lambda e: self.update_payment_method(method=e.control.value)
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

    def finalize_sale(self, internal_id):
        def process_sale():
            # Record sale to SQLite
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

        if not sale or not sale.current_sale:
            self.show_error("Sem produtos nas vendas!")
            return

        # Apply promotion and calculate final price
        final_price = sale.calculate_total()

        # Save sale details
        # Save sale logic moved to record_sale
        threading.Thread(target=process_sale).start()

        self.new_sale()
        self.product_widgets.clear()
        self.widgets_vendas.controls.clear()
        self.delete_stored_sale(internal_id)
        self.update_sale_display()

    def show_sales_history(self, e=None):
        hist.SalesHistoryDialog(self.page).show()
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

    def new_sale(self, e=None, sale_to_open=None):

        if sale_to_open is None:
            self.sale = sale.Sale(self.product_db, self.shop)
            self.store_sale()
        else:
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
