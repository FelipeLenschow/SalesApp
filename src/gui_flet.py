
import flet as ft
import pandas as pd
from datetime import datetime
import threading
import time
import unicodedata
import src.history as hist

# Local imports
import src.db_sqlite as db  # Changed import
import src.sale as sale
import src.payment as payment
import src.sync_client as sync_client

# Constants for UI scaling
BASE_WIDTH = 1920
BASE_HEIGHT = 1080
Version = "0.6.0"  # Increment version


class ProductApp:
    def __init__(self, page: ft.Page):
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
        self.page.on_resized = self.on_resize
        self._resize_timer = None

        # Initialize UI
        saved_shop = self.product_db.get_config('current_shop')
        if saved_shop:
             self.shop = saved_shop
             self.pay = payment.Payment(self, self.shop)
             self.build_main_window(page)
             self.new_sale()
        else:
            self.select_shop_window(self.page)

        # Start auto-sync thread
        self.stop_sync_thread = False
        threading.Thread(target=self.start_auto_sync, daemon=True).start()

    def on_resize(self, e):
        if self._resize_timer:
            self._resize_timer.cancel()
        self._resize_timer = threading.Timer(0.2, self._perform_resize)
        self._resize_timer.start()

    def _perform_resize(self):
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
        self.scale_factor = 0.6 * min(screen_width / BASE_WIDTH, screen_height / BASE_HEIGHT)

        # Rebuild UI
        self.page.clean()
        self.product_widgets = {} 
        self.build_main_window(self.page)
        
        # Restore Data Display
        if self.sale:
             self.update_sale_display()
        
        self.page.update()

    def select_shop_window(self, page: ft.Page):
        page.bgcolor = "#8b0000"
        page.window.full_screen = False  # Windowed for selection
        page.window.width = 600
        page.window.height = 500
        page.window.center()
        page.vertical_alignment = ft.MainAxisAlignment.CENTER
        page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

        shops = []
        
        # If no local shops, try to fetch from server
        if not shops:
            try:
                # SERVER URL - HARDCODED FOR NOW or use config default
                SERVER_URL = "http://localhost:8000" 
                client = sync_client.SyncClient(SERVER_URL, self.product_db)
                server_shops = client.get_shops()
                if server_shops:
                    shops = [s['name'] for s in server_shops]
            except Exception as e:
                print(f"Failed to fetch shops from server: {e}")
                shops = ["Erro ao conectar ao servidor"]

        selected_shop = ft.Ref[ft.Dropdown]()
        password_field = ft.TextField(label="Senha da Loja", password=True, can_reveal_password=True, width=280)

        def on_select(e):
            e.control.disabled = True
            e.control.update()
            self.shop = selected_shop.current.value
            password = password_field.value
            
            if not self.shop or self.shop == "Erro ao conectar ao servidor":
                page.snack_bar = ft.SnackBar(ft.Text("Selecione uma loja válida."), bgcolor="red")
                page.snack_bar.open = True
                page.update()
                e.control.disabled = False
                e.control.update()
                return

            # Allow empty password if user intends to send it (server validates)
            
            # Initial Sync to populate DB and Verify Password
            page.snack_bar = ft.SnackBar(ft.Text("Autenticando e baixando dados..."), bgcolor="blue")
            page.snack_bar.open = True
            page.update()
            
            try:
                SERVER_URL = "http://localhost:8000"
                client = sync_client.SyncClient(SERVER_URL, self.product_db)
                # Pass shop_name explicitly as it is not yet in config
                client.sync(password=password, shop_name=self.shop)
                
                # If sync succeeds, save config
                self.product_db.set_config('current_shop', self.shop)
                self.product_db.set_config('shop_password', password)
                
                page.snack_bar = ft.SnackBar(ft.Text("Dados sincronizados com sucesso!"), bgcolor="green")
            except Exception as ex:
                import requests
                error_msg = f"Erro ao sincronizar: {ex}"
                
                # Try to get detailed error message from server response
                if isinstance(ex, requests.exceptions.HTTPError):
                    try:
                        if ex.response is not None:
                            detail = e.response.json().get('detail')
                            if detail:
                                error_msg = f"{detail}"
                    except:
                         pass

                # Use AlertDialog for better visibility of errors
                # Use AlertDialog for better visibility of errors
                error_dialog = ft.AlertDialog(
                    title=ft.Text("Erro na Sincronização"),
                    content=ft.Text(error_msg),
                    actions=[
                    ],
                )
                # Define close action dynamically to reference the dialog instance
                error_dialog.actions.append(
                    ft.TextButton("OK", on_click=lambda e: page.close(error_dialog) if hasattr(page, 'close') else page.close_dialog())
                )

                try:
                    page.open(error_dialog)
                except AttributeError:
                    page.dialog = error_dialog
                    error_dialog.open = True
                    page.update()
                e.control.disabled = False
                e.control.update()
                return
            
            page.snack_bar.open = True
            page.update()
            time.sleep(1)

            page.snack_bar.open = True
            page.update()
            time.sleep(1)

            # Simulate saving selection and building main UI
            page.clean()
            self.pay = payment.Payment(self, self.shop)
            self.page = page
            self.build_main_window(page)
            self.new_sale()

        def open_create_shop_dialog(e):
            
            new_shop_name = ft.TextField(label="Nome da Nova Loja")
            new_shop_pass = ft.TextField(label="Senha da Nova Loja", password=True, can_reveal_password=True)
            
            copy_check = ft.Checkbox(label="Copiar dados de outra loja?", value=False)
            source_shop_dropdown = ft.Dropdown(label="Loja de Origem", options=[ft.dropdown.Option(shop) for shop in shops if shop != "Erro ao conectar ao servidor" and shop != "Nenhuma loja cadastrada"], disabled=True, width=500) ## Shouldn't have this width, but its needed to make the dialog look good
            source_shop_pass = ft.TextField(label="Senha da Loja de Origem", password=True, can_reveal_password=True, disabled=True)

            def on_copy_check_change(e):
                source_shop_dropdown.disabled = not copy_check.value
                source_shop_pass.disabled = not copy_check.value
                page.update()

            copy_check.on_change = on_copy_check_change
            
            def confirm_create_shop(e):
                if not new_shop_name.value:
                    page.snack_bar = ft.SnackBar(ft.Text("Digite o nome da nova loja."), bgcolor="red")
                    page.snack_bar.open = True
                    page.update()
                    return

                source_name = None
                source_pass = None
                
                if copy_check.value:
                    if not source_shop_dropdown.value:
                        page.snack_bar = ft.SnackBar(ft.Text("Selecione a loja de origem."), bgcolor="red")
                        page.snack_bar.open = True
                        page.update()
                        return
                    source_name = source_shop_dropdown.value
                    source_pass = source_shop_pass.value # Can be empty if allowed

                try:
                    SERVER_URL = "http://localhost:8000"
                    client = sync_client.SyncClient(SERVER_URL, self.product_db)
                    
                    page.snack_bar = ft.SnackBar(ft.Text("Criando loja..."), bgcolor="blue")
                    page.snack_bar.open = True
                    page.update()
                    
                    resp = client.create_shop(new_shop_name.value, new_shop_pass.value, source_name, source_pass)
                    
                    page.snack_bar = ft.SnackBar(ft.Text(f"Loja criada! {resp.get('message', '')}"), bgcolor="green")
                    page.snack_bar.open = True
                    
                    # Close dialog
                    if hasattr(page, 'close'):
                         page.close(create_dialog)
                    else:
                         page.close_dialog()
                    
                    # Refresh shop list (hacky: just restart or re-fetch?) 
                    # For a clean experience, we should re-fetch.
                    # Re-fetch shops
                    try:
                        new_shops = client.get_shops()
                        if new_shops:
                            selected_shop.current.options = [ft.dropdown.Option(s['name']) for s in new_shops]
                            # Update source dropdown too just in case
                            source_shop_dropdown.options = [ft.dropdown.Option(s['name']) for s in new_shops]
                            page.update()
                    except:
                        pass # Ignore refresh error
                        
                    page.update()

                except Exception as ex:
                    import requests
                    err_msg = str(ex)
                    if isinstance(ex, requests.exceptions.HTTPError):
                        try:
                            if ex.response is not None:
                                detail = ex.response.json().get('detail')
                                if detail:
                                    err_msg = detail
                        except:
                            pass
                    
                    page.snack_bar = ft.SnackBar(ft.Text(f"Erro ao criar loja: {err_msg}"), bgcolor="red")
                    page.snack_bar.open = True
                    page.update()

            create_dialog = ft.AlertDialog(
                title=ft.Text("Criar Nova Loja"),
                content=ft.Column([
                    new_shop_name,
                    new_shop_pass,
                    copy_check,
                    source_shop_dropdown,
                    source_shop_pass
                ], tight=True, width=500),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda e: page.close(create_dialog) if hasattr(page, 'close') else page.close_dialog()),
                    ft.ElevatedButton("Criar", on_click=confirm_create_shop)
                ]
            )
            
            try:
                page.open(create_dialog)
            except AttributeError:
                page.dialog = create_dialog
                create_dialog.open = True
                page.update()

        page.add(
            ft.Column(
                [
                    ft.Text("Selecione a loja", size=25, weight="bold", color="white"),
                    ft.Text(f"Versão: {Version}", size=10, color="white"),
                    ft.Dropdown(
                        ref=selected_shop,
                        options=[ft.dropdown.Option(shop) for shop in shops],
                        width=280,
                        autofocus=True,
                    ),
                    password_field,
                    ft.Container(height=20),
                    ft.ElevatedButton("Selecionar", on_click=on_select),
                    ft.Container(height=10),
                    ft.TextButton("Criar Nova Loja", on_click=open_create_shop_dialog)
                ],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

    def build_main_window(self, page: ft.Page):
        page.title = "Sorveteria"

        # Fullscreen for desktop
        page.bgcolor = "#1a1a2e"
        page.window.full_screen = True

        def close_app(e):
            page.window.close()

        def minimize_app(e):
            page.window.minimized = True
            page.update()

        screen_width = page.window.width
        screen_height = page.window.height

        # Fix for transition from small window: if size is small, assume 1080p
        if screen_width < 1000:
            screen_width = 1920
            screen_height = 1080

        self.scale_factor = 0.6 * min(screen_width / BASE_WIDTH, screen_height / BASE_HEIGHT)

        # Other UI elements
        self.final_price_label = ft.Text("R$ 0.00", size=100 * self.scale_factor, weight=ft.FontWeight.BOLD,
                                         color="white")
        self.status_text = ft.Text("", color="#ff8888")
        self.troco_text = ft.Text("", color="white")

        self.valor_pago_entry = ft.TextField(
            label="Valor pago",
            width=300 * self.scale_factor,
            on_change=lambda e: self.calcular_troco(),
        )

        self.payment_method_var = ft.Dropdown(
            label="Método de pagamento",
            options=[ft.dropdown.Option(x) for x in [" ", "Débito", "Pix", "Dinheiro", "Crédito"]],
            width=300 * self.scale_factor
        )

        button_style = ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DISABLED: ft.Colors.BLUE_GREY_400,
                ft.ControlState.DEFAULT: ft.Colors.BLUE_600,
            },
            color={
                ft.ControlState.DISABLED: ft.Colors.WHITE54,
                ft.ControlState.DEFAULT: ft.Colors.WHITE,
            },
            text_style=ft.TextStyle(size=30 * self.scale_factor, weight=ft.FontWeight.BOLD)
        )

        button_width = 200 * self.scale_factor
        button_heigth = 60 * self.scale_factor # Slightly larger for modern feel

        # Define individual buttons for reference
        self.cobrar_btn = ft.ElevatedButton(
            "Cobrar",
            width=200 * self.scale_factor, # Consistent with others, or full width if preferred
            height=button_heigth,
            on_click=lambda e: self.cobrar(),
            style=button_style,
            disabled=True, # Initially disabled
        )

        finalize_btn = ft.ElevatedButton(
            "Finalizar",
            height=button_heigth,
            width=200 * self.scale_factor, # Same width
            on_click=lambda e: self.finalize_sale(self.sale.id),
            style=button_style
        )
        
        self.payment_method_var.on_change = self.on_payment_method_change

        payment_area = (
            ft.Container(
                ft.Column(
                    [
                        # NEW ORDER:
                        # 1. Total (Centered)
                        ft.Row([self.final_price_label], alignment=ft.MainAxisAlignment.CENTER),
                        
                        # 2. Valor Pago
                        ft.Row([self.valor_pago_entry], alignment=ft.MainAxisAlignment.CENTER),
                        
                        # 3. Troco (Centered)
                        ft.Row([self.troco_text], alignment=ft.MainAxisAlignment.CENTER),
                        
                        # 4. Finalizar
                        ft.Row([finalize_btn], alignment=ft.MainAxisAlignment.CENTER),

                        # 5. Spacer
                        ft.Container(
                            height=100 * self.scale_factor,
                        ),
                        # ft.Divider(),
                        
                        # 6. Payment Method
                        ft.Row([self.payment_method_var], alignment=ft.MainAxisAlignment.CENTER),
                        
                        # 7. Cobrar (Conditional)
                        ft.Row([self.cobrar_btn], alignment=ft.MainAxisAlignment.CENTER),

                    ],
                    spacing=10 * self.scale_factor,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                padding=ft.padding.only(right=10 * self.scale_factor),
                # visual debug
                # border=ft.border.all(1, ft.Colors.WHITE) 
            )
        )

        # Top bar with title and window controls
        top_bar = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        [
                            ft.Text("Sorveteria", size=60 * self.scale_factor, weight=ft.FontWeight.BOLD,
                                    color="white"),
                            ft.Text(f"   {self.shop}", size=40 * self.scale_factor, color="white"),
                        ],
                        spacing=-5
                    ),
                    ft.Container(expand=True),  # Push buttons to the right
                    ft.IconButton(icon="remove", icon_color="white", tooltip="Minimizar", on_click=minimize_app),
                    ft.IconButton(icon="close", icon_color="red", tooltip="Fechar", on_click=close_app),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=ft.padding.only(left=20 * self.scale_factor, right=20 * self.scale_factor,
                                    top=10 * self.scale_factor)
        )

        self.search_results = ft.Column(
            scroll=ft.ScrollMode.ALWAYS,
            spacing=5,
            visible=True,
        )

        self.barcode_dropdown = ft.Container(
            content=self.search_results,
            bgcolor=ft.Colors.WHITE,
            padding=10,
            border=ft.border.all(1, ft.Colors.GREY_300),
            border_radius=5,
            visible=False,  # Start hidden until needed
            top=100 * self.scale_factor,
            left=0,
            width=800 * self.scale_factor,
            height=400 * self.scale_factor,  # Increased height
            shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.BLACK54),
        )

        # Modified barcode entry with dropdown
        self.barcode_entry = ft.TextField(
            label="Código de barras",
            on_submit=lambda e: self.handle_barcode(),
            on_change=lambda e: self.handle_search(),
            width=800 * self.scale_factor,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_focus=lambda e: self.show_dropdown(),
            on_blur=lambda e: self.hide_dropdown_in_100ms(),
            height=100 * self.scale_factor,  # User set this to 100
        )

        # In your layout, place the dropdown near the barcode entry
        self.barcode_stack = ft.Stack(
            controls=[
                self.barcode_entry,  # TextField comes first (bottom layer)
                self.barcode_dropdown,  # Dropdown comes after (top layer)
            ],
            height=110 * self.scale_factor,
            clip_behavior=ft.ClipBehavior.NONE
        )

        self.widgets_vendas = ft.Column(
            controls=[],
            width=1200 * self.scale_factor,
            spacing=10 * self.scale_factor
        )

        self.stored_sales_row = ft.Row(
            controls=[],
            wrap=True,
            spacing=20 * self.scale_factor,
            scroll=ft.ScrollMode.ALWAYS,
            alignment=ft.MainAxisAlignment.START,
        )

        main_content = ft.Column(
            [
                # Top section
                ft.Column(
                    [
                        top_bar,
                        ft.Stack([
                            ft.Row(
                                [
                                    ft.Container(height=50 * self.scale_factor),
                                    ft.Column(
                                        [
                                            ft.Container(height=350 * self.scale_factor),
                                            self.widgets_vendas,
                                        ],
                                        expand=True,
                                        alignment=ft.MainAxisAlignment.START,
                                    ),
                                    ft.Column(
                                        [self.status_text, payment_area], # Removed final_price_label (now in payment_area)
                                        width=450 * self.scale_factor,
                                        alignment=ft.MainAxisAlignment.START,
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.START,
                                expand=True,
                            ),
                            ft.Row([self.barcode_stack], alignment=ft.MainAxisAlignment.CENTER),
                        ])
                    ],
                    expand=True,
                ),
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.IconButton(
                                icon=ft.Icons.ADD,
                                icon_color="white",
                                icon_size=40 * self.scale_factor,
                                tooltip="Nova Venda",
                                on_click=lambda e: self.new_sale()
                            ),
                            padding=ft.padding.only(left=10 * self.scale_factor, right=10 * self.scale_factor),
                        ),
                        ft.Container(
                            content=self.stored_sales_row,
                            height=250 * self.scale_factor,
                            expand=True, # Allow it to take remaining space
                            padding=ft.padding.only(bottom=0),
                            border_radius=10 * self.scale_factor,
                            alignment=ft.alignment.bottom_left,
                        )
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.END, # Align with bottom
                )
            ],
            expand=True,
            spacing=0,
        )


        self.sync_fab = ft.FloatingActionButton(
            icon=ft.Icons.SAVE,
            bgcolor=ft.Colors.BLUE,
            on_click=self.open_sync_dialog,
            tooltip="Sincronizar",
        )

        # Additional FABs for History and Register
        self.history_fab = ft.FloatingActionButton(
            icon=ft.Icons.HISTORY,
            bgcolor=ft.Colors.BLUE,
            on_click=self.show_sales_history,
            tooltip="Histórico",
        )

        self.register_fab = ft.FloatingActionButton(
            icon=ft.Icons.ADD_BOX,
            bgcolor=ft.Colors.BLUE,
            on_click=lambda e: self.edit_product(),
            tooltip="Cadastrar Produto",
        )

        page.floating_action_button = ft.Row(
            controls=[
                self.register_fab,
                self.history_fab,
                self.sync_fab
            ],
            spacing=10,
            alignment=ft.MainAxisAlignment.END,
        )

        page.add(main_content)

    def show_dropdown(self):
        if self.search_results.controls:
            self.barcode_dropdown.visible = True
            # Expand stack to allow clicking on dropdown
            self.barcode_stack.height = 500 * self.scale_factor
            self.barcode_stack.update()
            self.barcode_dropdown.update()
        else:
            self.hide_dropdown()

    def hide_dropdown(self):
        self.barcode_dropdown.visible = False
        # Collapse stack to unblock underlying controls
        self.barcode_stack.height = 110 * self.scale_factor
        self.barcode_stack.update()
        self.page.update()

    def hide_dropdown_in_100ms(self):
        # Delay hiding to allow click events on dropdown items
        def hide():
            time.sleep(0.1)
            self.barcode_dropdown.visible = False
            self.barcode_stack.height = 110 * self.scale_factor
            self.page.update()

        threading.Thread(target=hide).start()

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
        print("Open Sync Dialog clicked")
        # Pre-fill IP from config
        saved_ip = self.product_db.get_config('server_ip') or "http://localhost:8000"
        
        # Dialog to ask for Server URL/IP
        server_ip = ft.TextField(label="IP do Servidor", value=saved_ip)
        
        def start_sync(e):
            print("Start Sync clicked")
            # Close dialog handling
            if hasattr(self.page, 'close'):
                 self.page.close(dialog)
            else:
                 self.page.close_dialog()
            # process the sync
            self.run_sync(server_ip.value)

        def reset_shop(e):
            self.product_db.reset_config('current_shop')
            self.show_error("Loja resetada! Reinicie o programa para selecionar novamente.")
            if hasattr(self.page, 'close'):
                 self.page.close(dialog)
            else:
                 self.page.close_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text("Sincronização"),
            content=ft.Column([
                ft.Text("Digite o endereço do servidor (Ex: http://192.168.0.10:8000)"),
                server_ip,
                ft.Divider(),
                ft.TextButton("Trocar/Resetar Loja (Dev)", on_click=reset_shop, style=ft.ButtonStyle(color="red"))
            ], height=150),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.close(dialog) if hasattr(self.page, 'close') else self.page.close_dialog()),
                ft.ElevatedButton("Sincronizar", on_click=start_sync)
            ],
        )

        # Attempt to open dialog using modern or legacy method
        try:
            self.page.open(dialog)
        except AttributeError:
             self.page.dialog = dialog
             dialog.open = True
        
        self.page.update()

    def start_auto_sync(self):
        while not self.stop_sync_thread:
            try:
                # Wait 30 minutes (1800 seconds)
                # Check smaller intervals to allow faster exit
                for _ in range(1800):
                    if self.stop_sync_thread: break
                    time.sleep(1)
                
                if self.stop_sync_thread: break

                saved_ip = self.product_db.get_config('server_ip')
                if saved_ip:
                   print("Auto-sync triggering...")
                   self.run_sync(saved_ip, silent=True)
            except Exception as e:
                print(f"Auto-sync loop error: {e}")
                time.sleep(60) # Wait a bit on error

    def update_fab_status(self, color, tooltip):
        try:
             if hasattr(self, 'sync_fab'):
                self.sync_fab.bgcolor = color
                self.sync_fab.tooltip = tooltip
                self.sync_fab.update()
        except:
            pass
    
    def mark_unsynced(self):
        """Marks the UI as having unsynced data (Blue Icon)"""
        self.update_fab_status(ft.Colors.BLUE, "Sincronizar (Dados pendentes)")

    def run_sync(self, server_url, silent=False):
        print(f"Running sync with {server_url}")
        
        if not silent:
            self.page.snack_bar = ft.SnackBar(content=ft.Text("Iniciando sincronização..."), bgcolor="blue")
            self.page.snack_bar.open = True
            self.page.update()
            
            # Show loading
            loading = ft.AlertDialog(
                title=ft.Text("Sincronizando..."),
                content=ft.ProgressRing(),
                modal=True
            )
            self.page.dialog = loading
            loading.open = True
            self.page.update()

        self.update_fab_status(ft.Colors.YELLOW, "Sincronizando...")

        def sync_process():
            try:
                print("Sync thread started")
                import src.sync_client as sc
                client = sc.SyncClient(server_url, self.product_db)
                result = client.sync()
                print(f"Sync result: {result}")
                
                # Save successful IP
                self.product_db.set_config('server_ip', server_url)
                
                if not silent:
                    # Close loading
                    loading.open = False
                    try:
                        self.page.update()
                    except Exception as e:
                        print(f"Error closing loading dialog: {e}")
                
                # Show result
                final_msg = f"Sincronização concluída!\nEnviados: {result.get('uploaded')}\nRecebidos: {result.get('downloaded')}\nMsg: {result.get('message')}"
                if not silent:
                     self.page.snack_bar = ft.SnackBar(ft.Text(final_msg), bgcolor="green")
                     self.page.snack_bar.open = True
                     self.page.update()
                
                self.update_fab_status(ft.Colors.GREEN, "Sincronizado: " + result.get('message', 'OK'))

            except Exception as e:
                print(f"Sync failed with exception: {e}")
                if not silent:
                    loading.open = False
                    try:
                        self.page.update()
                    except:
                        pass
                    self.page.snack_bar = ft.SnackBar(ft.Text(f"Erro interno na sincronização: {e}"), bgcolor="red")
                    self.page.snack_bar.open = True
                    self.page.update()
                
                self.update_fab_status(ft.Colors.RED, f"Erro: {str(e)}")

        threading.Thread(target=sync_process).start()

    def select_product(self, product):
        self.hide_dropdown()
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

            self.show_dropdown()
        else:
            self.hide_dropdown()

        self.page.update()

    def handle_search(self):
        barcode = self.barcode_entry.value.strip()  # Use single variable
        if not barcode.isdigit():
            self.search_products(search_term=barcode)
            self.show_dropdown()
        else:
            self.hide_dropdown()

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
                    ('Metadata', 'Excel Row'): f'Manual_{self.manual_add_count}',
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
                    self.show_dropdown()
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
        for excel_row in self.sale.current_sale.keys():
            details = None
            product_series = None

            if type(excel_row) != str:
                # Assuming excel_row is now product_id (int)
                product_series = self.product_db.get_product_info(excel_row, self.sale.shop)
            else:
                # Quando ha produtos manualmente adicionados
                for product in self.manual_add_list:
                    if excel_row == product[('Metadata', 'Excel Row')]:
                        product_series = product
            
            if product_series is None:
                 print(f"Product not found for ID: {excel_row}")
                 continue # Skip if not found


            details = {
                'categoria': product_series[('Todas', 'Categoria')],
                'sabor': product_series[('Todas', 'Sabor')],
                'preco': self.sale.current_sale[excel_row]['preco'],
                'quantidade': self.sale.current_sale[excel_row]['quantidade'],
                'indexExcel': excel_row
            }
            self.create_or_update_product_widget(excel_row, details, skip_price_update=(excel_row == skip_price_update_for))

        # Se um produto foi passado, focar no widget de quantidade correspondente
        if focus_on_ is not None:
            excel_row = focus_on_[('Metadata', 'Excel Row')]
            if excel_row in self.product_widgets:
                self.product_widgets[excel_row]['quantity_field'].focus = True
                self.widgets_vendas.update()

        if self.valor_pago_entry.value:
            self.calcular_troco()

        self.create_or_update_sale_widgets()
        self.page.update()

    def create_or_update_product_widget(self, excel_row, details, skip_price_update=False):

        if excel_row not in self.product_widgets:
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
                on_change=lambda e, row=excel_row: self.update_quantity_dynamic(row, e.control.value)
            )

            # Price display
            price_text = ft.TextField(
                value=f"{details['preco']:.2f}",
                width=180 * self.scale_factor,
                text_size=font_size,
                text_align=ft.TextAlign.RIGHT,
                prefix_text="R$ ",
                on_change=lambda e, row=excel_row: self.update_price_dynamic(row, e.control.value)
            )

            # Delete button
            delete_button = ft.IconButton(
                icon=ft.Icons.DELETE_FOREVER,
                icon_color="red",
                on_click=lambda e, row=excel_row: self.delete_product(row)
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
            if not str(excel_row).startswith('Manual'):
                edit_button = ft.IconButton(
                    icon=ft.Icons.EDIT,
                    icon_color="blue",
                    on_click=lambda e, row=excel_row: self.edit_product(row)
                )
                product_row.controls.insert(3, edit_button)

            # Add row to container
            self.widgets_vendas.controls.append(product_row)
            self.widgets_vendas.update()

            # Store reference in dictionary
            self.product_widgets[excel_row] = {
                'product_text': product_text,
                'quantity_field': quantity_field,
                'price_text': price_text,
                'delete_button': delete_button,
                'row': product_row
            }

        else:
            # Update existing widgets
            widgets = self.product_widgets[excel_row]

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



    def update_quantity_dynamic(self, index_excel, quantity_var):
        try:
            new_quantity = int(quantity_var)
            if new_quantity <= 0:
                new_quantity = 0
                self.delete_product(index_excel)
            if index_excel in self.sale.current_sale:
                self.sale.current_sale[index_excel]['quantidade'] = max(new_quantity, 0)
            self.update_sale_display()
        except ValueError:
            if quantity_var != "":
                self.show_error(f"Por favor, insira um número válido. ({quantity_var})")

    def update_price_dynamic(self, index_excel, price_var):
        try:
            # Handle comma/dot and currency symbols if present
            clean_price = price_var.replace('R$', '').replace(' ', '').replace(',', '.')
            if not clean_price: 
                return

            new_price = float(clean_price)
            if new_price < 0:
                new_price = 0.0
            
            self.sale.update_price(index_excel, new_price)
            # Update entire display to recalculate totals, but be careful with focus
            # For now, we update everything to ensure consistency
            self.update_sale_display(skip_price_update_for=index_excel)
        except ValueError:
            pass # Allow user to type unfinished numbers

    def delete_product(self, excel_row):
        self.sale.remove_product(excel_row)
        if excel_row in self.product_widgets:
            product_row = self.product_widgets[excel_row]['row']
            self.widgets_vendas.controls.remove(product_row)
            del self.product_widgets[excel_row]
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

    def cobra(self):
        # Alias if needed, or remove.
        self.cobrar()

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

    def edit_product(self, index_excel=None, barcode=None, prefill_store=None):
        shop = self.sale.shop if prefill_store is None else prefill_store
        
        # Set editing flag to block F12 from focusing main window
        self.is_editing = True
        
        # Track if close was intentional (Save or Discartar button)
        explicit_close = False

        if index_excel and index_excel != 'Manual' and not str(index_excel).startswith('Manual'):
            product_series = self.product_db.get_product_info(index_excel, shop)
            if product_series is None:
                self.show_error("Produto não encontrado para edição")
                return
            
            current_data = {
                'titulo_da_aba': 'Editar Produto',
                'barcode': product_series[('Todas', 'Codigo de Barras')],
                'sabor': product_series[('Todas', 'Sabor')],
                'categoria': product_series[('Todas', 'Categoria')],
                'preco': product_series[(shop, 'Preco')],
                'preco': product_series[(shop, 'Preco')]
            }
        else:
            current_data = {
                'titulo_da_aba': 'Cadastrar Produto',
                'barcode': barcode or '',
                'sabor': '',
                'categoria': '',
                'preco': ''
            }

        # Create TextFields and store references
        barcode_field = ft.TextField(
            label="Codigo de barras", 
            value=str(current_data['barcode']),
            autofocus=True # Focus this field specifically
        )
        categoria_field = ft.TextField(label="Categoria", value=current_data['categoria'])
        sabor_field = ft.TextField(label="Sabor", value=current_data['sabor'])
        preco_field = ft.TextField(label="Preco", value=str(current_data['preco']))

        explicit_close = False

        def check_dirty():
            # Check if any field other than barcode has content
            fields = [categoria_field, sabor_field, preco_field]
            return any(str(f.value).strip() != "" for f in fields)

        def handle_dismiss(e):
            nonlocal explicit_close
            
            # If closed by button (Save/Discard), allow it
            if explicit_close:
                self.is_editing = False
                self.page.update()
                return

            # If closed by clicking outside
            if check_dirty():
                # User tried to close a dirty form by clicking outside.
                # "Not allowing it" -> Re-open immediately.
                self.page.open(edit_product_window)
                self.page.update()
            else:
                # Clean form -> Allow close
                self.is_editing = False
                self.page.update()

        def save_changes(e):
            try:
                # Get and sanitize input values
                new_barcode = barcode_field.value.strip()
                new_sabor = sabor_field.value.strip()
                new_categoria = categoria_field.value.strip()
                new_preco = preco_field.value.strip().replace(',', '.')

                # Validate required fields
                if not all([new_barcode, new_sabor, new_categoria, new_preco]):
                    self.show_error("Preencha todos os campos necessários")
                    return

                # Parse numerical values
                def parse_float(value):
                    if not value:
                        return None
                    try:
                        return float(value)
                    except ValueError:
                        raise ValueError(f"Valor inválido: {value}")
                
                def parse_int(value):
                    if not value:
                        return None
                    try:
                        return int(value)
                    except ValueError:
                        # Check if it's a float with .0
                        float_val = float(value)
                        if float_val.is_integer():
                            return int(float_val)
                        else:
                            raise ValueError(f"Valor inteiro inválido: {value}")

                preco_val = parse_float(new_preco)

                # Prepare product data
                product_info = {
                    'barcode': new_barcode,
                    'sabor': new_sabor,
                    'categoria': new_categoria,
                    'preco': preco_val,
                    'indexExcel': index_excel
                }

                # Update product in database
                self.product_db.add_product(product_info, shop)
                self.mark_unsynced()

                # Update price in current sale if item exists
                if index_excel and index_excel in self.sale.current_sale:
                    self.sale.update_price(index_excel, preco_val)

                self.update_sale_display()

                # Close dialog
                close()
            except Exception as ex:
                self.show_error(f"Erro ao salvar: {str(ex)}")

        def close(e=None):
            nonlocal explicit_close
            explicit_close = True
            self.page.close(edit_product_window)
            self.is_editing = False # Reset flag
            self.page.update()

        # Create the dialog with actions linked to the functions
        edit_product_window = ft.AlertDialog(
            modal=False, # Always allow click outside to trigger 'on_dismiss'
            on_dismiss=handle_dismiss,
            title=ft.Text(current_data['titulo_da_aba']),
            content=ft.Column(
                controls=[
                    barcode_field,
                    categoria_field,
                    sabor_field,
                    preco_field,
                ],
                scroll=ft.ScrollMode.ADAPTIVE,
                height=350,
                tight=True,
            ),
            actions=[
                ft.TextButton("Salvar", on_click=save_changes),
                ft.TextButton("Descartar", on_click=close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        # Open the dialog
        self.page.open(edit_product_window)
        self.page.update()

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
