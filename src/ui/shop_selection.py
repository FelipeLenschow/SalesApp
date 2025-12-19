
import flet as ft
import time
import src.ui.sync_client as sync_client
import src.payment as payment
import src.ui.main_window
import src.ui.product_editor

import src.db_sqlite as local_db

class ShopSelection:
    def __init__(self, app, page: ft.Page):
        self.app = app
        self.page = page
        self.local_db = local_db.Database()

    def show(self):
        self.page.bgcolor = "#8b0000"
        self.page.window.full_screen = False  # Windowed for selection
        self.page.window.width = 400
        self.page.window.height = 300
        self.page.window.center()
        self.page.vertical_alignment = ft.MainAxisAlignment.CENTER
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

        self.error_text = ft.Text("", color="red", size=14, weight="bold")
        shops = []
        
        # If no local shops, try to fetch from server
        # If no shops, try to fetch from DB
        if not shops:
            try:
                shops = self.app.product_db.get_shops()
            except Exception as e:
                print(f"Failed to fetch shops: {e}")
                shops = ["Erro ao conectar ao servidor"]
                self.error_text.value = f"Erro ao buscar lojas: {e}"

        selected_shop = ft.Ref[ft.Dropdown]()
        # Password field removed

        # Password field removed

        def on_select(e):
            e.control.disabled = True
            e.control.update()
            self.error_text.value = "" 
            self.error_text.update()
            shop_name = selected_shop.current.value
            
            if not shop_name or shop_name == "Erro ao conectar ao servidor":
                self.page.snack_bar = ft.SnackBar(ft.Text("Selecione uma loja válida."), bgcolor="red")
                self.page.snack_bar.open = True
                self.page.update()
                e.control.disabled = False
                e.control.update()
                return

            # Proceed to set shop
            try:
                # 3. SWAP DB Reference (Already done in gui.py potentially, but ensure it)
                # The app should currently be using local db
                if isinstance(self.app.product_db, local_db.Database):
                     self.app.product_db.set_config('current_shop', shop_name)
                     self.app.shop = shop_name 
                else:
                    # Fallback if somehow we are still on AWS DB or mixed state?
                    # This shouldn't happen with new flow, but let's be safe.
                    # If we are here, we probably didn't download?
                    pass

                self.page.snack_bar = ft.SnackBar(ft.Text(f"Loja {shop_name} selecionada!"), bgcolor="green")
            
            except Exception as ex:
                print(f"Selection Error: {ex}")
                self.page.snack_bar = ft.SnackBar(ft.Text(f"Erro ao selecionar: {ex}"), bgcolor="red")
            
            self.page.snack_bar.open = True
            self.page.update()
            time.sleep(0.5)

            # Proceed to Main App
            self.page.clean()
            self.app.pay = payment.Payment(self.app, self.app.shop)
            self.app.page = self.page 
            
            self.app.ui = src.ui.main_window.MainWindow(self.app, self.page)
            self.app.ui.build()
            self.app.editor = src.ui.product_editor.ProductEditor(self.app)
            self.app.new_sale()
            
            # Reset window size
            self.page.window.min_width = 1000
            self.page.window.min_height = 650
            self.page.window.width = 1024
            self.page.window.height = 768
            self.page.window.resizable = True
            self.page.update()
            
            time.sleep(0.2) 
            
            self.page.window.full_screen = True
            if hasattr(self.app.ui, 'update_custom_buttons_visibility'):
                self.app.ui.update_custom_buttons_visibility()
            self.page.update()



        self.page.add(
            ft.Column(
                [
                    ft.Text("Selecione a loja", size=25, weight="bold", color="white"),
                    ft.Text(f"Versão: {self.app.Version}", size=10, color="white"),
                    ft.Dropdown(
                        ref=selected_shop,
                        options=[ft.dropdown.Option(shop) for shop in shops],
                        width=280,
                        autofocus=True,
                    ),
                    # Password field removed
                    ft.Container(height=20),
                    self.error_text,
                    ft.ElevatedButton("Selecionar", on_click=on_select),
                    ft.Container(height=10)
                ],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
