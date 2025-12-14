
import flet as ft
import time
import src.ui.sync_client as sync_client
import src.payment as payment
import src.ui.main_window
import src.ui.product_editor

class ShopSelection:
    def __init__(self, app, page: ft.Page):
        self.app = app
        self.page = page

    def show(self):
        self.page.bgcolor = "#8b0000"
        self.page.window.full_screen = False  # Windowed for selection
        self.page.window.width = 400
        self.page.window.height = 300
        self.page.window.center()
        self.page.vertical_alignment = ft.MainAxisAlignment.CENTER
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

        shops = []
        
        # If no local shops, try to fetch from server
        if not shops:
            try:
                # SERVER_URL is ignored by new SyncClient
                client = sync_client.SyncClient(self.app.product_db)
                server_shops = client.get_shops()
                if server_shops:
                    # server_shops is already a list of strings ['ShopA', 'ShopB']
                    shops = server_shops
            except Exception as e:
                print(f"Failed to fetch shops from server: {e}")
                shops = ["Erro ao conectar ao servidor"]

        selected_shop = ft.Ref[ft.Dropdown]()
        # Password field removed

        def on_select(e):
            e.control.disabled = True
            e.control.update()
            shop_name = selected_shop.current.value
            
            if not shop_name or shop_name == "Erro ao conectar ao servidor":
                self.page.snack_bar = ft.SnackBar(ft.Text("Selecione uma loja válida."), bgcolor="red")
                self.page.snack_bar.open = True
                self.page.update()
                e.control.disabled = False
                e.control.update()
                return

            # Initial Sync to populate DB
            self.page.snack_bar = ft.SnackBar(ft.Text("Autenticando e baixando dados..."), bgcolor="blue")
            self.page.snack_bar.open = True
            self.page.update()
            
            try:
                # SERVER_URL ignored
                client = sync_client.SyncClient(self.app.product_db)
                # Pass shop_name explicitly
                client.sync(shop_name=shop_name)
                
                # If sync succeeds, save config
                self.app.product_db.set_config('current_shop', shop_name)
                # Password saving removed
                
                self.page.snack_bar = ft.SnackBar(ft.Text("Dados sincronizados com sucesso!"), bgcolor="green")
            except Exception as ex:
                error_msg = f"Erro ao sincronizar: {ex}"
                
                # Use AlertDialog for better visibility of errors
                error_dialog = ft.AlertDialog(
                    title=ft.Text("Erro na Sincronização"),
                    content=ft.Text(error_msg),
                    actions=[
                    ],
                )
                # Define close action dynamically to reference the dialog instance
                error_dialog.actions.append(
                    ft.TextButton("OK", on_click=lambda e: self.page.close(error_dialog) if hasattr(self.page, 'close') else self.page.close_dialog())
                )

                try:
                    self.page.open(error_dialog)
                except AttributeError:
                    self.page.dialog = error_dialog
                    error_dialog.open = True
                    self.page.update()
                e.control.disabled = False
                e.control.update()
                return
            
            self.page.snack_bar.open = True
            self.page.update()
            time.sleep(1)

            self.page.snack_bar.open = True
            self.page.update()
            time.sleep(1)

            # Simulate saving selection and building main UI
            self.app.shop = shop_name
            self.page.clean()
            self.app.pay = payment.Payment(self.app, self.app.shop)
            self.app.page = self.page # Ensure app has correct page
            # Initialize Main Window
            self.app.ui = src.ui.main_window.MainWindow(self.app, self.page)
            self.app.ui.build()
            self.app.editor = src.ui.product_editor.ProductEditor(self.app)
            self.app.new_sale()
            
            # Reset window size for Main App usage (in case user exits full screen)
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
                    ft.ElevatedButton("Selecionar", on_click=on_select),
                    ft.Container(height=10)
                ],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
