
import flet as ft
import time
import threading

class MainWindow:
    def __init__(self, app, page: ft.Page):
        self.app = app
        self.page = page
        self.scale_factor = 1.0

    def build(self):
        self.page.title = "Sorveteria"
        self.page.bgcolor = "#1a1a2e"
        self.page.window.full_screen = True

        screen_width = self.page.window.width
        screen_height = self.page.window.height

        # Fix for transition from small window
        if screen_width < 1000:
            screen_width = 1920
            screen_height = 1080

        # Constants for UI scaling (assumed from original file)
        BASE_WIDTH = 1920
        BASE_HEIGHT = 1080
        self.scale_factor = 0.6 * min(screen_width / BASE_WIDTH, screen_height / BASE_HEIGHT)
        
        # Make scale_factor available to app if needed, or just use it locally
        self.app.scale_factor = self.scale_factor

        def close_app(e):
            self.page.window.close()

        def minimize_app(e):
            self.page.window.minimized = True
            self.page.update()

        # --- UI Elements ---
        
        # 1. Labels and Text
        self.app.final_price_label = ft.Text("R$ 0.00", size=100 * self.scale_factor, weight=ft.FontWeight.BOLD, color="white")
        self.app.status_text = ft.Text("", color="#ff8888")
        self.app.troco_text = ft.Text("", color="white")

        # 2. Controls
        self.app.valor_pago_entry = ft.TextField(
            label="Valor pago",
            width=300 * self.scale_factor,
            on_change=lambda e: self.app.calcular_troco(),
        )

        self.app.payment_method_var = ft.Dropdown(
            label="Método de pagamento",
            options=[ft.dropdown.Option(x) for x in [" ", "Débito", "Pix", "Dinheiro", "Crédito"]],
            width=300 * self.scale_factor,
            on_change=self.app.on_payment_method_change
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
            text_style=ft.TextStyle(size=30 * self.scale_factor, weight=ft.FontWeight.BOLD)
        )
        button_heigth = 60 * self.scale_factor

        self.app.cobrar_btn = ft.ElevatedButton(
            "Cobrar",
            width=200 * self.scale_factor,
            height=button_heigth,
            on_click=lambda e: self.app.cobrar(),
            style=button_style,
            disabled=True,
        )

        finalize_btn = ft.ElevatedButton(
            "Finalizar",
            height=button_heigth,
            width=200 * self.scale_factor,
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
                    ft.Container(height=100 * self.scale_factor),
                    ft.Row([self.app.payment_method_var], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row([self.app.cobrar_btn], alignment=ft.MainAxisAlignment.CENTER),
                ],
                spacing=10 * self.scale_factor,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(right=10 * self.scale_factor),
        )

        # 5. Top Bar
        top_bar = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        [
                            ft.Text("Sorveteria", size=60 * self.scale_factor, weight=ft.FontWeight.BOLD, color="white"),
                            ft.Text(f"   {self.app.shop}", size=40 * self.scale_factor, color="white"),
                        ],
                        spacing=-5
                    ),
                    ft.Container(expand=True),
                    ft.IconButton(icon="remove", icon_color="white", tooltip="Minimizar", on_click=minimize_app),
                    ft.IconButton(icon="close", icon_color="red", tooltip="Fechar", on_click=close_app),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=ft.padding.only(left=20 * self.scale_factor, right=20 * self.scale_factor, top=10 * self.scale_factor)
        )

        # 6. Search Results & Dropdown
        self.app.search_results = ft.Column(
            scroll=ft.ScrollMode.ALWAYS,
            spacing=5,
            visible=True,
        )

        self.app.barcode_dropdown = ft.Container(
            content=self.app.search_results,
            bgcolor=ft.Colors.WHITE,
            padding=10,
            border=ft.border.all(1, ft.Colors.GREY_300),
            border_radius=5,
            visible=False,
            top=100 * self.scale_factor,
            left=0,
            width=800 * self.scale_factor,
            height=400 * self.scale_factor,
            shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.BLACK54),
        )

        # 7. Barcode Entry
        # Note: references helper methods in self.app (we will need to move them or keep them)
        # If we move show_dropdown to MainWindow, we change these calls to self.show_dropdown()
        self.app.barcode_entry = ft.TextField(
            label="Código de barras",
            on_submit=lambda e: self.app.handle_barcode(),
            on_change=lambda e: self.app.handle_search(),
            width=800 * self.scale_factor,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_focus=lambda e: self.show_dropdown(),
            on_blur=lambda e: self.hide_dropdown_in_100ms(),
            height=100 * self.scale_factor,
        )

        self.app.barcode_stack = ft.Stack(
            controls=[
                self.app.barcode_entry,
                self.app.barcode_dropdown,
            ],
            height=110 * self.scale_factor,
            clip_behavior=ft.ClipBehavior.NONE
        )

        # 8. Sales Columns
        self.app.widgets_vendas = ft.Column(
            controls=[],
            width=1200 * self.scale_factor,
            spacing=10 * self.scale_factor
        )

        self.app.stored_sales_row = ft.Row(
            controls=[],
            wrap=True,
            spacing=20 * self.scale_factor,
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
                                    ft.Container(height=50 * self.scale_factor),
                                    ft.Column(
                                        [
                                            ft.Container(height=350 * self.scale_factor),
                                            self.app.widgets_vendas,
                                        ],
                                        expand=True,
                                        alignment=ft.MainAxisAlignment.START,
                                    ),
                                    ft.Column(
                                        [self.app.status_text, payment_area],
                                        width=450 * self.scale_factor,
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
                                icon_size=40 * self.scale_factor,
                                tooltip="Nova Venda",
                                on_click=lambda e: self.app.new_sale()
                            ),
                            padding=ft.padding.only(left=10 * self.scale_factor, right=10 * self.scale_factor),
                        ),
                        ft.Container(
                            content=self.app.stored_sales_row,
                            height=250 * self.scale_factor,
                            expand=True,
                            padding=ft.padding.only(bottom=0),
                            border_radius=10 * self.scale_factor,
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
            on_click=self.app.open_sync_dialog,
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
            on_click=lambda e: self.app.edit_product(),
            tooltip="Cadastrar Produto",
        )

        self.page.floating_action_button = ft.Row(
            controls=[
                self.app.register_fab,
                self.app.history_fab,
                self.app.sync_fab
            ],
            spacing=10,
            alignment=ft.MainAxisAlignment.END,
        )

        self.page.add(main_content)

    # --- UI Helper Methods (Moved from ProductApp) ---

    def show_dropdown(self):
        # We access controls via app because we assigned them to app
        if self.app.search_results.controls:
            self.app.barcode_dropdown.visible = True
            self.app.barcode_stack.height = 500 * self.scale_factor
            self.app.barcode_stack.update()
            self.app.barcode_dropdown.update()
        else:
            self.hide_dropdown()

    def hide_dropdown(self):
        self.app.barcode_dropdown.visible = False
        self.app.barcode_stack.height = 110 * self.scale_factor
        self.app.barcode_stack.update()
        self.page.update()

    def hide_dropdown_in_100ms(self):
        def hide():
            time.sleep(0.1)
            self.app.barcode_dropdown.visible = False
            self.app.barcode_stack.height = 110 * self.scale_factor
            self.page.update()

        threading.Thread(target=hide).start()
