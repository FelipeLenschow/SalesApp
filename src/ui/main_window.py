
import flet as ft
import time
import threading

class MainWindow:
    def __init__(self, app, page: ft.Page):
        self.app = app
        self.page = page
        self.custom_restore_btn = None
        self.custom_close_btn = None

    def update_custom_buttons_visibility(self):
        if self.custom_restore_btn and self.custom_close_btn:
            is_full_screen = self.page.window.full_screen
            self.custom_restore_btn.visible = is_full_screen
            self.custom_close_btn.visible = is_full_screen
            
            if self.custom_restore_btn.page:
                self.custom_restore_btn.update()
            if self.custom_close_btn.page:
                self.custom_close_btn.update()

    def build(self):
        self.page.title = "Sorveteria"
        self.page.bgcolor = "#1a1a2e"


        def close_app(e):
            self.page.window.close()

        def minimize_app(e):
            self.page.window.minimized = True
            self.page.update()

        # --- UI Elements ---
        
        # 1. Labels and Text
        self.app.final_price_label = ft.Text("R$ 0.00", size=60, weight=ft.FontWeight.BOLD, color="white")
        self.app.status_text = ft.Text("", color="#ff8888")
        self.app.troco_text = ft.Text("", color="white")

        # 2. Controls
        self.app.valor_pago_entry = ft.TextField(
            label="Valor pago",
            width=300 * 0.6,
            on_change=lambda e: self.app.calcular_troco(),
        )

        self.app.payment_method_var = ft.Dropdown(
            label="Método de pagamento",
            options=[ft.dropdown.Option(x) for x in [" ", "Débito", "Pix", "Dinheiro", "Crédito"]],
            width=180,
            on_change=self.app.on_payment_method_change,
            disabled=True
        )

        # 3. Buttons
        button_style = ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DISABLED: ft.Colors.BLUE_GREY_400,
                ft.ControlState.DEFAULT: ft.Colors.BLUE_600,
            },
            color={
                ft.ControlState.DISABLED: ft.Colors.WHITE54,
                ft.ControlState.DEFAULT: ft.Colors.WHITE,
            },
            text_style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD)
        )
        button_heigth = 36

        self.app.cobrar_btn = ft.ElevatedButton(
            "Cobrar",
            width=200 * 0.6,
            height=button_heigth,
            on_click=lambda e: self.app.cobrar(),
            style=button_style,
            disabled=True,
        )

        finalize_btn = ft.ElevatedButton(
            "Finalizar",
            height=button_heigth,
            width=120,
            on_click=lambda e: self.app.finalize_sale(self.app.sale.id) if self.app.sale else None,
            style=button_style
        )

        # 4. Payment Area Layout
        payment_area = ft.Container(
            ft.Column(
                [
                    ft.Row([self.app.final_price_label], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row([self.app.valor_pago_entry], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row([self.app.troco_text], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row([finalize_btn], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Container(height=60),
                    ft.Row([self.app.payment_method_var], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row([self.app.cobrar_btn], alignment=ft.MainAxisAlignment.CENTER),
                ],
                spacing=6,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(right=6),
        )

        # 5. Top Bar

        self.custom_restore_btn = ft.IconButton(
            icon=ft.Icons.FULLSCREEN_EXIT, 
            icon_color="white", 
            tooltip="Sair da Tela Cheia", 
            visible=False, # Managed by update_custom_buttons
        )

        self.custom_close_btn = ft.IconButton(
            icon="close", 
            icon_color="red", 
            tooltip="Fechar", 
            on_click=close_app,
            visible=False, # Managed by update_custom_buttons
        )

        def toggle_full_screen(e):
            self.page.window.full_screen = False
            self.page.window.maximized = False
            self.update_custom_buttons_visibility()
            self.page.update()

        self.custom_restore_btn.on_click = toggle_full_screen
        
        # Initialize visibility
        self.update_custom_buttons_visibility()

        top_bar = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        [
                            ft.Text("Sorveteria", size=36, weight=ft.FontWeight.BOLD, color="white"),
                            ft.Text(f"   {self.app.shop}", size=24, color="white"),
                        ],
                        spacing=-3
                    ),
                    ft.Container(expand=True),
                    self.custom_restore_btn,
                    self.custom_close_btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=ft.padding.only(left=12, right=12, top=6)
        )

        # 6. Search Results & Dropdown
        self.app.search_results = ft.Column(
            scroll=ft.ScrollMode.ALWAYS,
            spacing=3,
            visible=True,
        )

        self.app.barcode_dropdown = ft.Container(
            content=self.app.search_results,
            bgcolor=ft.Colors.WHITE,
            padding=6,
            border=ft.border.all(1, ft.Colors.GREY_300),
            border_radius=3,
            visible=False,
            top=60,
            left=0,
            width=480,
            height=240,
            shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK54),
        )

        # 7. Barcode Entry
        # Note: references helper methods in self.app (we will need to move them or keep them)
        # If we move show_dropdown to MainWindow, we change these calls to self.show_dropdown()
        self.app.barcode_entry = ft.TextField(
            label="Código de barras",
            on_submit=lambda e: self.app.handle_barcode(),
            on_change=lambda e: self.app.handle_search(),
            width=480,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_focus=lambda e: self.show_dropdown(),
            on_blur=lambda e: self.hide_dropdown_in_100ms(),
            height=60,
        )

        self.app.barcode_stack = ft.Stack(
            controls=[
                self.app.barcode_entry,
                self.app.barcode_dropdown,
            ],
            height=66,
            clip_behavior=ft.ClipBehavior.NONE
        )

        # 8. Sales Columns
        self.app.widgets_vendas = ft.Column(
            controls=[],
            width=1000,
            spacing=6
        )

        self.app.stored_sales_row = ft.Row(
            controls=[],
            wrap=True,
            spacing=12,
            scroll=ft.ScrollMode.ALWAYS,
            alignment=ft.MainAxisAlignment.START,
        )

        # 9. Main Content Layout
        main_content = ft.Column(
            [
                ft.Column(
                    [
                        top_bar,
                        ft.Stack([
                            ft.Row(
                                [
                                    ft.Container(height=30),
                                    ft.Column(
                                        [
                                            ft.Container(height=210),
                                            self.app.widgets_vendas,
                                        ],
                                        expand=True,
                                        alignment=ft.MainAxisAlignment.START,
                                    ),
                                    ft.Column(
                                        [self.app.status_text, payment_area],
                                        width=270,
                                        alignment=ft.MainAxisAlignment.START,
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.START,
                                expand=True,
                            ),
                            ft.Row([self.app.barcode_stack], alignment=ft.MainAxisAlignment.CENTER),
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
                                icon_size=24,
                                tooltip="Nova Venda",
                                on_click=lambda e: self.app.new_sale()
                            ),
                            padding=ft.padding.only(left=6, right=6),
                        ),
                        ft.Container(
                            content=self.app.stored_sales_row,
                            height=150,
                            expand=True,
                            padding=ft.padding.only(bottom=0),
                            border_radius=6,
                            alignment=ft.alignment.bottom_left,
                        )
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.END,
                )
            ],
            expand=True,
            spacing=0,
        )

        # 10. FABs
        self.app.sync_fab = ft.FloatingActionButton(
            icon=ft.Icons.SAVE,
            bgcolor=ft.Colors.BLUE,
            on_click=self.app.run_sync,
            tooltip="Sincronizar",
        )

        self.app.history_fab = ft.FloatingActionButton(
            icon=ft.Icons.HISTORY,
            bgcolor=ft.Colors.BLUE,
            on_click=self.app.show_sales_history,
            tooltip="Histórico",
        )

        self.app.register_fab = ft.FloatingActionButton(
            icon=ft.Icons.ADD_BOX,
            bgcolor=ft.Colors.BLUE,
            on_click=lambda e: self.app.editor.open(),
            tooltip="Cadastrar Produto",
        )

        self.page.floating_action_button = ft.Row(
            controls=[
                self.app.register_fab,
                self.app.history_fab,
                self.app.sync_fab
            ],
            spacing=6,
            alignment=ft.MainAxisAlignment.END,
        )

        self.page.add(main_content)

    # --- UI Helper Methods (Moved from ProductApp) ---

    def show_dropdown(self):
        # We access controls via app because we assigned them to app
        if self.app.search_results.controls:
            self.app.barcode_dropdown.visible = True
            self.app.barcode_stack.height = 300
            self.app.barcode_stack.update()
            self.app.barcode_dropdown.update()
        else:
            self.hide_dropdown()

    def hide_dropdown(self):
        self.app.barcode_dropdown.visible = False
        self.app.barcode_stack.height = 66
        self.app.barcode_stack.update()
        self.page.update()

    def hide_dropdown_in_100ms(self):
        def hide():
            time.sleep(0.1)
            # Check if a scan happened recently (within 500ms)
            if time.time() - self.app.last_barcode_scan < 0.5:
                return
            
            self.app.barcode_dropdown.visible = False
            self.app.barcode_stack.height = 66
            self.page.update()

        threading.Thread(target=hide).start()
