import flet as ft
from src.aws_db import Database
import time
import threading

class StoreManagerApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Gerenciador de Lojas - Matriz de Preços"
        self.page.theme_mode = ft.ThemeMode.DARK # Dark Theme
        self.page.padding = 20
        
        # Initialize DB
        self.db = Database()
        
        # State
        self.current_products = [] 
        self.known_shops = []

        # Dirty Tracking
        self.dirty_prices = set() # (barcode, shop_name)
        self.dirty_metadata = set() # barcode
        
        # Review Tracking
        self.reviewed_rows = set() # barcode
        
        # UI Constants
        self.W_CODE = 140
        self.W_TEXT = 140
        self.W_CAT = 300 # Wider
        self.W_FLAVOR = 300 # Wider
        self.W_PRICE = 90
        
        # Colors
        self.COLOR_EDITED = ft.Colors.BLUE_900
        self.COLOR_REVIEWED = ft.Colors.GREEN_900
        self.COLOR_BLINK = ft.Colors.WHITE
        self.COLOR_DEFAULT = None

        # Search Indicator
        self.last_searched_barcode = None

        # Deferred Operations
        self.dirty_new_shops = set()
        self.dirty_deletes = set() # product_ids to delete

        self.build_ui()

    def show_snack(self, message, color=ft.Colors.GREEN):
        self.page.snack_bar = ft.SnackBar(ft.Text(str(message)), bgcolor=color)
        self.page.snack_bar.open = True
        self.page.update()

    def get_row_color(self, barcode):
        is_dirty_meta = barcode in self.dirty_metadata
        is_dirty_price = any(d_bc == barcode for d_bc, _ in self.dirty_prices)
        
        if is_dirty_meta or is_dirty_price:
            return self.COLOR_EDITED
        
        if barcode in self.reviewed_rows:
            return self.COLOR_REVIEWED
            
        return self.COLOR_DEFAULT

    def update_row_visuals(self, barcode):
        # Scan controls to find the row (now only product rows in list)
        for ctrl in self.products_list.controls:
            if isinstance(ctrl, ft.Container) and ctrl.key == barcode:
                ctrl.bgcolor = self.get_row_color(barcode)
                
                # Apply Indicator Border if it's the last searched item
                if barcode == self.last_searched_barcode:
                    ctrl.border = ft.border.all(3, ft.Colors.CYAN)
                else:
                    ctrl.border = None
                
                ctrl.update()
                return

    def toggle_review(self, e, barcode):
        if barcode in self.reviewed_rows:
            self.reviewed_rows.remove(barcode)
            e.control.icon = ft.Icons.CHECK_BOX_OUTLINE_BLANK
            e.control.icon_color = ft.Colors.GREY
        else:
            self.reviewed_rows.add(barcode)
            e.control.icon = ft.Icons.CHECK_BOX
            e.control.icon_color = ft.Colors.GREEN
        
        e.control.update()
        self.update_row_visuals(barcode)

    def update_metadata(self, prod, field, value, control):
        if prod.get(field) != value:
            prod[field] = value
            self.dirty_metadata.add(prod['barcode'])
            self.update_row_visuals(prod['barcode'])

    def update_price(self, prod, shop_name, value, control):
        try:
            val_str = value.replace(',', '.')
            val_float = float(val_str)
            old_val = prod['prices'].get(shop_name, 0.0)
            
            if abs(val_float - old_val) > 0.001:
                prod['prices'][shop_name] = val_float
                self.dirty_prices.add((prod['barcode'], shop_name))
                self.update_row_visuals(prod['barcode'])
                
        except ValueError:
            pass 

    def save_changes(self, e):
        if not self.dirty_prices and not self.dirty_metadata and not self.dirty_new_shops and not self.dirty_deletes:
            self.show_snack("Nenhuma alteração pendente (Azul).", ft.Colors.AMBER)
            return

        self.btn_save.disabled = True
        self.status_text.value = f"Salvando alterações..."
        self.page.update()
        
        count = 0
        errors = 0
        try:
            # 0. Sync New Shops (Deferred Creation)
            for new_shop in list(self.dirty_new_shops):
                try:
                    self.db.add_shop(new_shop)
                except Exception as ex:
                    print(f"Error creating shop {new_shop}: {ex}")
                    errors += 1

            # 0.5. Sync Deletes
            for pid in list(self.dirty_deletes):
                try:
                    self.db.delete_product_completely(pid)
                    count += 1
                except Exception as ex:
                    print(f"Error deleting product {pid}: {ex}")
                    errors += 1
            
            prod_map = {p['barcode']: p for p in self.current_products}
            processed_barcodes = set()

            # 1. Save Prices
            for barcode, shop_name in list(self.dirty_prices):
                 if barcode in prod_map:
                     p = prod_map[barcode]
                     
                     price_val = p['prices'].get(shop_name, 0.0)
                     
                     product_info = {
                         'product_id': p.get('product_id'),
                         'barcode': p['barcode'],
                         'marca': p.get('marca', ''),
                         'categoria': p.get('categoria', ''),
                         'sabor': p.get('sabor', ''),
                         'preco': price_val
                     }
                     
                     try:
                         # Update product_id if newly created
                         new_pid = self.db.add_product(product_info, shop_name)
                         if not p.get('product_id'):
                             p['product_id'] = new_pid
                         count += 1
                         processed_barcodes.add(barcode)
                     except Exception as ex:
                         print(f"Error saving {barcode}/{shop_name}: {ex}")
                         errors += 1

            # 2. Save Metadata
            for barcode in list(self.dirty_metadata):
                if barcode not in processed_barcodes and barcode in prod_map:
                    p = prod_map[barcode]
                    target_shop = list(p['prices'].keys())[0] if p['prices'] else (self.known_shops[0] if self.known_shops else None)
                    
                    if target_shop:
                        price_val = p['prices'].get(target_shop, 0.0)
                        
                        product_info = {
                            'product_id': p.get('product_id'),
                            'barcode': p['barcode'],
                            'marca': p.get('marca', ''),
                            'categoria': p.get('categoria', ''),
                            'sabor': p.get('sabor', ''),
                            'preco': price_val
                        }
                        try:
                            new_pid = self.db.add_product(product_info, target_shop)
                            if not p.get('product_id'):
                                p['product_id'] = new_pid
                            count += 1
                        except Exception as ex:
                             print(f"Error saving metadata {barcode}: {ex}")
                             errors += 1
            
            self.dirty_prices.clear()
            self.dirty_metadata.clear()
            self.dirty_new_shops.clear()
            self.dirty_deletes.clear()
            
            self.status_text.value = f"Salvo! {count} operações. {errors} erros."
            self.show_snack(f"Sucesso: {count} registros atualizados!", ft.Colors.GREEN)
            
            self.refresh_table()

        except Exception as ex:
            self.show_snack(f"Erro ao salvar: {ex}", ft.Colors.RED)
            
        self.btn_save.disabled = False
        self.page.update()

    def delete_product_click(self, barcode):
        def close_dlg(e):
            self.dlg_modal.open = False
            self.page.update()
            
        def confirm_delete(e):
            # Remove from local list
            # We need to find the item in self.current_products
            for i, p in enumerate(self.current_products):
                if p['barcode'] == barcode:
                    pid = p.get('product_id')
                    if pid:
                        self.dirty_deletes.add(pid)
                    
                    self.current_products.pop(i)
                    break
            
            # Remove from UI by refreshing (expensive but safe) or just list
            self.refresh_table()
            self.show_snack(f"Produto {barcode} removido da lista local.", ft.Colors.AMBER)
            
            # Note: We are NOT deleting from DB yet, as per request "Push only the lines I have edited".
            # If user wants to delete from DB, they might need a specific "Delete from Cloud" or we track deletions.
            # For now, local removal seems to be the intent for "editing".
            
            close_dlg(e)

        self.dlg_modal = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirmar Exclusão"),
            content=ft.Text(f"Tem certeza que deseja remover o produto '{barcode}' da lista?"),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dlg),
                ft.TextButton("Remover", on_click=confirm_delete, style=ft.ButtonStyle(color=ft.Colors.RED)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.overlay.append(self.dlg_modal)
        self.dlg_modal.open = True
        self.page.update()



    def refresh_table(self):
        # 1. Rebuild Headers (Static Row)
        self.header_container.controls.clear()
        
        header_controls = [
            ft.Text("Ações", width=80, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Text("Código", width=self.W_CODE, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Text("Marca", width=self.W_TEXT, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Text("Categoria", width=self.W_CAT, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Text("Sabor", width=self.W_FLAVOR, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
        ]
        
        for shop in self.known_shops:
            # Check if this shop is "New" (local only)
            is_new = shop in self.dirty_new_shops
            color = ft.Colors.BLUE if is_new else None
            
            # Just simple text, no menu
            header_controls.append(ft.Text(shop, width=self.W_PRICE, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, color=color))
            
        self.header_container.controls.append(ft.Row(controls=header_controls))
        self.header_container.controls.append(ft.Divider())
        self.header_container.update()

        # 2. Rebuild List (Virtual-like)
        self.products_list.controls.clear()

        # Build ROWS
        for p in self.current_products:
            bc = p['barcode']
            row_color = self.get_row_color(bc)

            # Check Button
            is_checked = bc in self.reviewed_rows
            icon = ft.Icons.CHECK_BOX if is_checked else ft.Icons.CHECK_BOX_OUTLINE_BLANK
            icon_col = ft.Colors.GREEN if is_checked else ft.Colors.GREY
            
            btn_check = ft.IconButton(
                icon=icon, 
                icon_color=icon_col,
                width=35,
                tooltip="Marcar como Revisado",
                on_click=lambda e, b=bc: self.toggle_review(e, b)
            )

            # Delete Button
            btn_delete = ft.IconButton(
                icon=ft.Icons.DELETE,
                icon_color=ft.Colors.RED_400,
                width=35,
                tooltip="Remover Linha",
                on_click=lambda e, b=bc: self.delete_product_click(b)
            )

            # Fields
            # Barcode is now Editable
            txt_barcode = ft.TextField(
                value=bc, width=self.W_CODE, 
                border=ft.InputBorder.NONE, text_size=13, bgcolor=ft.Colors.TRANSPARENT,
                on_change=lambda e, prod=p: self.update_metadata(prod, 'barcode', e.control.value, e.control)
            )
            
            txt_brand = ft.TextField(
                value=p.get('marca', ''), width=self.W_TEXT, content_padding=5, text_size=13,
                bgcolor=ft.Colors.TRANSPARENT, border_color=ft.Colors.TRANSPARENT,
                on_change=lambda e, prod=p: self.update_metadata(prod, 'marca', e.control.value, e.control)
            )
            txt_cat = ft.TextField(
                value=p.get('categoria', ''), width=self.W_CAT, content_padding=5, text_size=13,
                bgcolor=ft.Colors.TRANSPARENT, border_color=ft.Colors.TRANSPARENT,
                 on_change=lambda e, prod=p: self.update_metadata(prod, 'categoria', e.control.value, e.control)
            )
            txt_flavor = ft.TextField(
                value=p.get('sabor', ''), width=self.W_FLAVOR, content_padding=5, text_size=13,
                bgcolor=ft.Colors.TRANSPARENT, border_color=ft.Colors.TRANSPARENT,
                 on_change=lambda e, prod=p: self.update_metadata(prod, 'sabor', e.control.value, e.control)
            )

            row_controls = [
                ft.Row([btn_check, btn_delete], spacing=0, width=80),
                txt_barcode,
                txt_brand,
                txt_cat,
                txt_flavor
            ]
            
            for shop in self.known_shops:
                price_val = p['prices'].get(shop, 0.0)
                
                txt_price = ft.TextField(
                    value=f"{price_val:.2f}", 
                    width=self.W_PRICE, 
                    content_padding=5,
                    text_align=ft.TextAlign.RIGHT,
                    text_size=13,
                    bgcolor=ft.Colors.TRANSPARENT,
                    border_color=ft.Colors.TRANSPARENT,
                    on_change=lambda e, prod=p, s=shop: self.update_price(prod, s, e.control.value, e.control)
                )
                row_controls.append(txt_price)
                
            # Indicator Border
            border = ft.border.all(3, ft.Colors.CYAN) if bc == self.last_searched_barcode else None

            row_container = ft.Container(
                content=ft.Row(controls=row_controls, spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                key=str(bc),
                padding=ft.padding.only(left=5, right=5, top=2, bottom=2),
                height=50, 
                bgcolor=row_color,
                border=border,
                border_radius=5
            )
            self.products_list.controls.append(row_container)
            
        self.products_list.update()

    def load_matrix(self, e):
        self.status_text.value = "Carregando Matriz Global..."
        self.btn_load.disabled = True
        self.page.update()
        
        try:
            shops = self.db.get_shops()
            shops.sort()
            self.known_shops.clear()
            self.known_shops.extend(shops)
            
            flat_products = self.db.get_all_products(shop_name=None)
            
            pivot_map = {}
            
            for item in flat_products:
                bc = item['barcode']
                s_name = item.get('shop_name')
                price = item.get('preco', 0.0)
                
                if bc not in pivot_map:
                    pivot_map[bc] = {
                        'product_id': item.get('product_id'),
                        'barcode': bc,
                        'marca': item.get('marca', ''),
                        'categoria': item.get('categoria', ''),
                        'sabor': item.get('sabor', ''),
                        'prices': {}
                    }
                
                if not pivot_map[bc]['marca'] and item.get('marca'): pivot_map[bc]['marca'] = item.get('marca')
                if not pivot_map[bc]['categoria'] and item.get('categoria'): pivot_map[bc]['categoria'] = item.get('categoria')

                if s_name:
                    pivot_map[bc]['prices'][s_name] = price
            
            self.current_products.clear()
            self.current_products.extend(list(pivot_map.values()))
            self.current_products.sort(key=lambda x: x['barcode'])
            
            self.dirty_prices.clear()
            self.dirty_metadata.clear()
            self.reviewed_rows.clear()
            self.dirty_new_shops.clear()
            self.dirty_deletes.clear()
            self.last_searched_barcode = None
            
            self.refresh_table()
            
            self.status_text.value = f"Carregado: {len(self.current_products)} produtos, {len(self.known_shops)} lojas."
            self.show_snack("Download concluído.", ft.Colors.GREEN)
            
        except Exception as ex:
            print(ex)
            self.status_text.value = f"Erro: {ex}"
            self.show_snack(f"Erro de conexão: {ex}", ft.Colors.RED)
            
        self.btn_load.disabled = False
        self.page.update()

    def add_store_click(self, e):
        def close_dlg(e):
            self.dlg_modal.open = False
            self.page.update()
            
        def confirm_add_store(e):
            name = txt_store_name.value.strip()
            if not name: return
            
            source_shop = dd_copy_from.value
            
            try:
                if name in self.known_shops:
                    self.show_snack("Loja já existe!", ft.Colors.RED)
                    return

                # DEFER CREATION: Only add to local lists
                self.known_shops.append(name)
                self.known_shops.sort()
                self.dirty_new_shops.add(name) # Mark for saving on PUSH
                
                # Copy Logic (Local update only)
                if source_shop:
                    count_copied = 0
                    for p in self.current_products:
                        src_price = p['prices'].get(source_shop)
                        if src_price is not None:
                             p['prices'][name] = src_price
                             self.dirty_prices.add((p['barcode'], name))
                             count_copied += 1
                    self.show_snack(f"Loja '{name}' criada (Local*). Preços copiados: {count_copied}", ft.Colors.BLUE)
                else:
                    self.show_snack(f"Loja '{name}' adicionada (Local*) !", ft.Colors.BLUE)

                self.refresh_table()
                close_dlg(e)
            except Exception as ex:
                self.show_snack(f"Erro: {ex}", ft.Colors.RED)

        txt_store_name = ft.TextField(label="Nome da Loja", autofocus=True, on_submit=confirm_add_store)
        
        # Dropdown options
        opts = [ft.dropdown.Option(s) for s in self.known_shops]
        dd_copy_from = ft.Dropdown(
            label="Copiar preços de (Opcional)",
            options=opts,
        )

        self.dlg_modal = ft.AlertDialog(
            modal=True,
            title=ft.Text("Adicionar Nova Loja"),
            content=ft.Column([txt_store_name, dd_copy_from], tight=True, height=150),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dlg),
                ft.TextButton("Adicionar", on_click=confirm_add_store),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.overlay.append(self.dlg_modal)
        self.dlg_modal.open = True
        self.page.update()

    def add_product_click(self, e):
        # Direct Add: Insert line, scroll to top
        new_barcode = f"NEW_{int(time.time())}" # Temp unique
        new_p = {
            'product_id': None,
            'barcode': new_barcode, # Will be edited by user
            'marca': '',
            'categoria': '',
            'sabor': '',
            'prices': {}
        }
        
        self.current_products.insert(0, new_p)
        # Mark dirty immediately so it gets saved as new?
        # Ideally user edits it first.
        # But we need to track it.
        self.dirty_metadata.add(new_barcode)
        
        self.refresh_table()
        self.products_list.scroll_to(offset=0, duration=300)
        
        # Ideally focus on the barcode field of the first item
        # But we need reference. The refresh_table rebuilds controls.
        # We can try to access controls[0] but structure is:
        # container -> row -> [actions, txt_barcode, ...]
        # controls[0] is the container for the first item.
        try:
            # controls[0] is the newItem container
            # content is Row
            # controls[1] is txt_barcode
             first_row_container = self.products_list.controls[0]
             # Row controls: 0=actions_row, 1=txt_barcode
             txt_bc = first_row_container.content.controls[1]
             # We want to clear the 'NEW_...' text so user can type? 
             # Or keep it as placeholder? User said "barcode prefilled" in original prompt for scan, 
             # but here "add the line directly... like no barcode found".
             # Let's select all text so typing replaces it?
             txt_bc.focus()
             # Flet TextField selection support is limited in Python API sometimes, 
             # but focus works.
             txt_bc.value = "" # Clear it for them
             txt_bc.update()
        except:
             pass

    def process_barcode(self, barcode):
        barcode = barcode.strip()
        if not barcode: return

        # 1. Search in Local List
        found_idx = -1
        for i, p in enumerate(self.current_products):
            if p['barcode'] == barcode:
                found_idx = i
                break
        
        if found_idx != -1:
            self.show_snack(f"Produto localizado: {barcode}", ft.Colors.CYAN)
            
            try:
                # Update selection state
                previous = self.last_searched_barcode
                self.last_searched_barcode = barcode
                
                # Update visuals for both (Previous - remove border, New - add border)
                if previous and previous != barcode:
                    self.update_row_visuals(previous)
                
                self.update_row_visuals(barcode) # Updates new one

                # Scroll
                self.products_list.scroll_to(offset=found_idx * 55, duration=500)
                
            except Exception as ex:
                print(f"Scroll/Highlight error: {ex}")
            return

        # 2. Not Found -> Create
        try:
            template = self.db.get_template_by_barcode(barcode)
            if template:
                new_p = {
                    'product_id': template['product_id'],
                    'barcode': barcode,
                    'marca': template.get('marca',''),
                    'categoria': template.get('categoria',''),
                    'sabor': template.get('sabor',''),
                    'prices': {}
                }
                self.show_snack("Produto importado do Cloud.", ft.Colors.CYAN)
            else:
                new_p = {
                    'product_id': None,
                    'barcode': barcode,
                    'marca': '',
                    'categoria': '',
                    'sabor': '',
                    'prices': {}
                }
                self.show_snack(f"Novo produto criado: {barcode}", ft.Colors.GREEN)
            
            self.current_products.insert(0, new_p)
            self.dirty_metadata.add(barcode) 
            
            self.refresh_table()
            
            # Scroll to top (Offset 0)
            self.products_list.scroll_to(offset=0, duration=300)

        except Exception as ex:
            self.show_snack(f"Erro: {ex}", ft.Colors.RED)

    def search_submit(self, e):
        bc = self.input_search.value
        self.process_barcode(bc)
        self.input_search.value = ""
        self.input_search.focus()
        self.page.update()

    def build_ui(self):
        self.btn_load = ft.ElevatedButton("PULL (Baixar)", icon=ft.Icons.DOWNLOAD, on_click=self.load_matrix)
        self.btn_save = ft.ElevatedButton("PUSH (Salvar Editados)", icon=ft.Icons.UPLOAD, on_click=self.save_changes, bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE)
        
        self.btn_add_store = ft.ElevatedButton("Nova Loja", icon=ft.Icons.STORE, on_click=self.add_store_click)
        self.btn_add_prod = ft.ElevatedButton("Novo item manual", icon=ft.Icons.ADD, on_click=self.add_product_click)

        self.input_search = ft.TextField(
            label="Pesquisar / Criar (Código de Barras)", 
            expand=True, 
            on_submit=self.search_submit, 
            autofocus=True,
            prefix_icon=ft.Icons.QR_CODE_SCANNER,
            bgcolor=ft.Colors.GREY_900
        )

        self.status_text = ft.Text("Pronto.")
        
        self.header_container = ft.Column() 
        self.products_list = ft.ListView(expand=True, spacing=5, item_extent=50)

        self.page.add(
            ft.Row([
                ft.Text("Gerenciador de Estoque", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True), 
                self.btn_add_prod,
                self.btn_add_store,
                ft.VerticalDivider(),
                self.btn_load,
                self.btn_save
            ]),
            ft.Divider(),
            ft.Row([self.input_search], alignment=ft.MainAxisAlignment.CENTER),
            self.status_text,
            self.header_container,
            self.products_list
        )

def main(page: ft.Page):
    StoreManagerApp(page)

if __name__ == "__main__":
    ft.app(target=main)
