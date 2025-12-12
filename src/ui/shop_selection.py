
import flet as ft
import time
import src.ui.sync_client as sync_client
import src.payment as payment
import src.ui.main_window

class ShopSelection:
    def __init__(self, app, page: ft.Page):
        self.app = app
        self.page = page

    def show(self):
        self.page.bgcolor = "#8b0000"
        self.page.window.full_screen = False  # Windowed for selection
        self.page.window.width = 600
        self.page.window.height = 500
        self.page.window.center()
        self.page.vertical_alignment = ft.MainAxisAlignment.CENTER
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

        shops = []
        
        # If no local shops, try to fetch from server
        if not shops:
            try:
                # SERVER URL - HARDCODED FOR NOW or use config default
                SERVER_URL = "http://localhost:8000" 
                client = sync_client.SyncClient(SERVER_URL, self.app.product_db)
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
            shop_name = selected_shop.current.value
            password = password_field.value
            
            if not shop_name or shop_name == "Erro ao conectar ao servidor":
                self.page.snack_bar = ft.SnackBar(ft.Text("Selecione uma loja válida."), bgcolor="red")
                self.page.snack_bar.open = True
                self.page.update()
                e.control.disabled = False
                e.control.update()
                return

            # Allow empty password if user intends to send it (server validates)
            
            # Initial Sync to populate DB and Verify Password
            self.page.snack_bar = ft.SnackBar(ft.Text("Autenticando e baixando dados..."), bgcolor="blue")
            self.page.snack_bar.open = True
            self.page.update()
            
            try:
                SERVER_URL = "http://localhost:8000"
                client = sync_client.SyncClient(SERVER_URL, self.app.product_db)
                # Pass shop_name explicitly as it is not yet in config
                client.sync(password=password, shop_name=shop_name)
                
                # If sync succeeds, save config
                self.app.product_db.set_config('current_shop', shop_name)
                self.app.product_db.set_config('shop_password', password)
                
                self.page.snack_bar = ft.SnackBar(ft.Text("Dados sincronizados com sucesso!"), bgcolor="green")
            except Exception as ex:
                import requests
                error_msg = f"Erro ao sincronizar: {ex}"
                
                # Try to get detailed error message from server response
                if isinstance(ex, requests.exceptions.HTTPError):
                    try:
                        if ex.response is not None:
                            detail = ex.response.json().get('detail')
                            if detail:
                                error_msg = f"{detail}"
                    except:
                         pass

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
            self.app.new_sale()

        def open_create_shop_dialog(e):
            
            new_shop_name = ft.TextField(label="Nome da Nova Loja")
            new_shop_pass = ft.TextField(label="Senha da Nova Loja", password=True, can_reveal_password=True)
            
            copy_check = ft.Checkbox(label="Copiar dados de outra loja?", value=False)
            source_shop_dropdown = ft.Dropdown(label="Loja de Origem", options=[ft.dropdown.Option(shop) for shop in shops if shop != "Erro ao conectar ao servidor" and shop != "Nenhuma loja cadastrada"], disabled=True, width=500)
            source_shop_pass = ft.TextField(label="Senha da Loja de Origem", password=True, can_reveal_password=True, disabled=True)

            def on_copy_check_change(e):
                source_shop_dropdown.disabled = not copy_check.value
                source_shop_pass.disabled = not copy_check.value
                self.page.update()

            copy_check.on_change = on_copy_check_change
            
            def confirm_create_shop(e):
                if not new_shop_name.value:
                    self.page.snack_bar = ft.SnackBar(ft.Text("Digite o nome da nova loja."), bgcolor="red")
                    self.page.snack_bar.open = True
                    self.page.update()
                    return

                source_name = None
                source_pass = None
                
                if copy_check.value:
                    if not source_shop_dropdown.value:
                        self.page.snack_bar = ft.SnackBar(ft.Text("Selecione a loja de origem."), bgcolor="red")
                        self.page.snack_bar.open = True
                        self.page.update()
                        return
                    source_name = source_shop_dropdown.value
                    source_pass = source_shop_pass.value # Can be empty if allowed

                try:
                    SERVER_URL = "http://localhost:8000"
                    # Pass app's database
                    client = sync_client.SyncClient(SERVER_URL, self.app.product_db)
                    
                    self.page.snack_bar = ft.SnackBar(ft.Text("Criando loja..."), bgcolor="blue")
                    self.page.snack_bar.open = True
                    self.page.update()
                    
                    resp = client.create_shop(new_shop_name.value, new_shop_pass.value, source_name, source_pass)
                    
                    self.page.snack_bar = ft.SnackBar(ft.Text(f"Loja criada! {resp.get('message', '')}"), bgcolor="green")
                    self.page.snack_bar.open = True
                    
                    # Close dialog
                    if hasattr(self.page, 'close'):
                         self.page.close(create_dialog)
                    else:
                         self.page.close_dialog()
                    
                    # Refresh shop list
                    try:
                        new_shops = client.get_shops()
                        if new_shops:
                            shops_names = [s['name'] for s in new_shops]
                            selected_shop.current.options = [ft.dropdown.Option(s) for s in shops_names]
                            # Update source dropdown too just in case
                            source_shop_dropdown.options = [ft.dropdown.Option(s) for s in shops_names]
                            self.page.update()
                    except:
                        pass # Ignore refresh error
                        
                    self.page.update()

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
                    
                    self.page.snack_bar = ft.SnackBar(ft.Text(f"Erro ao criar loja: {err_msg}"), bgcolor="red")
                    self.page.snack_bar.open = True
                    self.page.update()

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
                    ft.TextButton("Cancelar", on_click=lambda e: self.page.close(create_dialog) if hasattr(self.page, 'close') else self.page.close_dialog()),
                    ft.ElevatedButton("Criar", on_click=confirm_create_shop)
                ]
            )
            
            try:
                self.page.open(create_dialog)
            except AttributeError:
                self.page.dialog = create_dialog
                create_dialog.open = True
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
