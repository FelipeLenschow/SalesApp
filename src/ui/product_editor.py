
import flet as ft
import time

class ProductEditor:
    def __init__(self, app):
        self.app = app
        self.page = app.page

    def open(self, product_id=None, barcode=None, prefill_store=None, suggested_price=None):
        shop = self.app.sale.shop if prefill_store is None else prefill_store
        
        # Set editing flag to block F12 from focusing main window
        self.app.is_editing = True
        self.app.active_input = None # Reset
        
        # Track if close was intentional (Save or Discartar button)
        explicit_close = False

        if product_id and product_id != 'Manual' and not str(product_id).startswith('Manual'):
            product_series = self.app.product_db.get_product_info(product_id, shop)
            if product_series is None:
                self.app.show_error("Produto não encontrado para edição")
                self.app.is_editing = False # Ensure flag is reset
                return
            
            p_price = product_series.get('preco', 0)
            if suggested_price is not None:
                p_price = suggested_price

            current_data = {
                'titulo_da_aba': 'Editar Produto',
                'barcode': product_series.get('barcode', ''),
                'sabor': product_series.get('sabor', ''),
                'categoria': product_series.get('categoria', ''),
                'preco': p_price,
            }
        else:
            current_data = {
                'titulo_da_aba': 'Cadastrar Produto',
                'barcode': barcode or '',
                'sabor': '',
                'categoria': '',
                'preco': ''
            }

        # Helper to set active input
        def set_active_input(e):
             self.app.active_input = e.control

        # Create TextFields and store references
        barcode_field = ft.TextField(
            label="Codigo de barras", 
            value=str(current_data['barcode']),
            autofocus=True, # Focus this field specifically
            on_focus=set_active_input
        )
        categoria_field = ft.TextField(
            label="Categoria", 
            value=current_data['categoria'],
            on_focus=set_active_input
        )
        sabor_field = ft.TextField(
            label="Sabor", 
            value=current_data['sabor'],
            on_focus=set_active_input
        )
        preco_field = ft.TextField(
            label="Preco", 
            value=str(current_data['preco']),
            on_focus=set_active_input
        )

        def check_dirty():
            # Check if any field other than barcode has content
            fields = [categoria_field, sabor_field, preco_field]
            return any(str(f.value).strip() != "" for f in fields)

        def close(e=None):
            nonlocal explicit_close
            explicit_close = True
            
            # Using new close mechanism if available or falling back
            if hasattr(self.page, 'close'):
               self.page.close(edit_product_window)
            else:
               self.page.close_dialog()
               
            self.app.is_editing = False
            self.page.update()

        def handle_dismiss(e):
            nonlocal explicit_close
            
            # If closed by button (Save/Discard), allow it
            if explicit_close:
                self.app.is_editing = False
                self.page.update()
                return

            # If closed by clicking outside
            if check_dirty():
                # User tried to close a dirty form by clicking outside.
                # "Not allowing it" -> Re-open immediately.
                # NOTE: This creates recursion issues if not careful.
                # A better approach for "modal" preventing click-away is `modal=True` on AlertDialog.
                # But user wants "click outside to cancel" only if NOT dirty.
                
                # Re-open or keep open
                # Ideally, we should set modal=False initially, and if check_dirty() is true, we simply ignore dismiss?
                # Flet AlertDialog dismiss is hard to cancel.
                # Workaround: Re-open it.
                self.page.open(edit_product_window)
                self.page.update()
                
                # Show generic "Discard?" prompt?
                # confirm_discard() # This would trigger the prompt on accidental click-away
            else:
                # Clean form -> Allow close
                self.app.is_editing = False
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
                    self.app.show_error("Preencha todos os campos necessários")
                    return

                # Parse numerical values
                def parse_float(value):
                    if not value:
                        return None
                    try:
                        return float(value)
                    except ValueError:
                        raise ValueError(f"Valor inválido: {value}")
                
                preco_val = parse_float(new_preco)

                # Prepare product data
                product_info = {
                    'barcode': new_barcode,
                    'sabor': new_sabor,
                    'categoria': new_categoria,
                    'preco': preco_val,
                    'product_id': product_id
                }

                # Update product in database
                self.app.product_db.add_product(product_info, shop)
                self.app.mark_unsynced()

                # Update price in current sale if item exists
                if product_id and product_id in self.app.sale.current_sale:
                    self.app.sale.update_price(product_id, preco_val)

                self.app.update_sale_display()

                # Close dialog
                close()
                self.app.show_error("Produto salvo com sucesso") # Feedback
            except Exception as ex:
                self.app.show_error(f"Erro ao salvar: {str(ex)}")

        # Dialog Content
        content = ft.Column(
            [
                barcode_field,
                categoria_field,
                sabor_field,
                preco_field
            ],
            tight=True,
            width=500
        )

        edit_product_window = ft.AlertDialog(
            title=ft.Text(current_data['titulo_da_aba']),
            content=content,
            actions=[
                ft.TextButton("Descartar", on_click=close, style=ft.ButtonStyle(color=ft.Colors.RED)),
                ft.ElevatedButton("Salvar", on_click=save_changes),
            ],
            on_dismiss=handle_dismiss,
            modal=False # We handle "modality" via handle_dismiss check
        )

        if hasattr(self.page, 'open'):
            self.page.open(edit_product_window)
        else:
            self.page.dialog = edit_product_window
            edit_product_window.open = True
            self.page.update()
