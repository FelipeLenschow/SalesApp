
import flet as ft
from src.aws_db import Database
import time

def main(page: ft.Page):
    page.title = "Gerenciador de Lojas - DynamoDB"
    page.theme_mode = ft.ThemeMode.DARK # Dark Theme
    page.padding = 20
    
    # Initialize DB
    db = Database()
    
    # State
    current_products = [] # List of dicts
    deleted_products = [] # Track deletions for sync
    sort_state = {"index": None, "ascending": True}
    
    # ... (skipping to functions)

    def delete_product(prod):
        if prod in current_products:
            deleted_products.append(prod)
            current_products.remove(prod)
            refresh_table()

    def delete_all_products(e):
        # Track all as deleted
        deleted_products.extend(current_products)
        current_products.clear()
        refresh_table()
        # Unlock source store and load button, disable add
        dd_source_store.disabled = False
        btn_load.disabled = False
        btn_add.disabled = True
        page.update()

    def add_new_product(e):
        # ... (rest of function)
        # Add a new empty product
        import time
        new_code = f"NEW_{int(time.time())}"
        new_prod = {
            'barcode': new_code,
            'categoria': '',
            'sabor': '',
            'preco': 0.0,
            'reviewed': True, # Mark as edited so it syncs
            'scanned': False
        }
        current_products.insert(0, new_prod) # Add to top
        refresh_table()
        # Scroll to top
        try:
             products_list.scroll_to(offset=0, duration=500)
        except: pass
        show_snack("Novo produto adicionado no topo!", ft.Colors.GREEN)

    def sync_to_dynamodb(e):
        target = input_target_store.value
        if not target:
            show_snack("Defina a loja de destino!", ft.Colors.RED)
            return

        # Filter reviewed items
        items_to_add = [p for p in current_products if p.get('reviewed', False)]
        
        # Check if there is anything to do
        if not items_to_add and not deleted_products:
            show_snack("Nada para sincronizar (apenas itens Verdes/Azuis ou Deletados são processados)!", ft.Colors.RED)
            return
        
        total_add = len(items_to_add)
        total_del = len(deleted_products)
        
        btn_sync.disabled = True
        status_text.value = f"Sincronizando: {total_add} envios, {total_del} remoções..."
        page.update()
        
        try:
            # Process Deletions
            for i, p in enumerate(deleted_products):
                status_text.value = f"Removendo {i+1}/{total_del}: {p['barcode']}..."
                page.update()
                db.delete_product(p['barcode'], target)
            
            # Clear deleted list after success (safety?)
            # deleted_products.clear() # Maybe don't clear yet in case functionality repeats? 
            # Actually standard practice is to clear if successful
            
            # Process Additions/Updates
            for i, p in enumerate(items_to_add):
                status_text.value = f"Enviando {i+1}/{total_add}: {p['barcode']}..."
                page.update()
                db.add_product(p, target)
                
            show_snack(f"Sincronização Fim: {total_add} enviados, {total_del} removidos em '{target}'.")
            
            # Clear deletion tracking after successful sync
            deleted_products.clear()
            status_text.value = "Pronto."
            
        except Exception as ex:
            print(ex)
            show_snack(f"Erro durante sincronização: {ex}", ft.Colors.RED)
            
        btn_sync.disabled = False
        page.update()
    
    # UI Elements Reference
    dd_source_store = ft.Dropdown(
        label="Loja de Origem",
        width=300,
        options=[ft.dropdown.Option(shop) for shop in db.get_shops()]
    )
    
    input_target_store = ft.TextField(label="Loja de Destino (Novo ou Existente)", width=300)
    
    input_barcode = ft.TextField(
        label="Bipar Produto (Foco Automático)", 
        autofocus=True, 
        width=400,
        on_submit=lambda e: on_barcode_scanned(e)
    )
    
    status_text = ft.Text("")

    # Scrollable container for rows
    # We use a Column inside a ListView or just a Column with scroll
    # ListView is better for scroll_to
    products_list = ft.ListView(
        expand=True,
        spacing=0, # No spacing between rows usually in a table
        auto_scroll=False
    )
    
    # Header Control
    def header_click(idx):
        sort_state["index"] = idx
        sort_state["ascending"] = not sort_state["ascending"]
        refresh_table()

    # Column Widths
    W_CODE = 200
    W_CAT = 400
    W_FLAV = 400
    W_PRICE = 150
    W_HEAD_BTN = 50 # Extra space for action header?

    def show_snack(message, color=ft.Colors.GREEN):
        page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=color)
        page.snack_bar.open = True
        page.update()
        
    def update_product_data(prod, field, value):
        if field == 'preco':
            try:
                prod[field] = float(value)
            except ValueError:
                pass 
        else:
            prod[field] = value

    def mark_edited(e, prod, row_control):
        # Mark as reviewed (Green) on manual edit
        prod['reviewed'] = True
        prod['scanned'] = False # Clear scanned status so it becomes Green
        
        if row_control:
             row_control.bgcolor = ft.Colors.GREEN_900
             row_control.update()

    def mark_as_checked(e, prod, row_control):
        # Guard: If already Green (Reviewed manually), don't change to Blue
        if prod.get('reviewed', False) and not prod.get('scanned', False):
            return

        # Mark as checked/scanned (Blue) on button click
        prod['reviewed'] = True
        prod['scanned'] = True # Force Blue status
        
        if row_control:
             row_control.bgcolor = ft.Colors.BLUE_900
             row_control.update()

    def refresh_table():
        # Handle Sorting
        idx = sort_state["index"]
        asc = sort_state["ascending"]
        
        if idx is not None:
             keys = ['barcode', 'categoria', 'sabor', 'preco']
             if idx < len(keys):
                 key = keys[idx]
                 current_products.sort(key=lambda x: x.get(key, ""), reverse=not asc)

        products_list.controls.clear()
        
        for p in current_products:
            is_reviewed = p.get('reviewed', False)
            is_scanned = p.get('scanned', False)
            
            # Row Color (Background)
            row_color = None
            if is_scanned:
                row_color = ft.Colors.BLUE_900
            elif is_reviewed:
                row_color = ft.Colors.GREEN_900
            
            # Editable Fields
            txt_barcode = ft.TextField(value=p['barcode'], border=ft.InputBorder.UNDERLINE, width=W_CODE)
            txt_category = ft.TextField(value=p['categoria'], border=ft.InputBorder.UNDERLINE, width=W_CAT)
            txt_flavor = ft.TextField(value=p['sabor'], border=ft.InputBorder.UNDERLINE, width=W_FLAV)
            txt_price = ft.TextField(value=f"{p['preco']:.2f}", border=ft.InputBorder.UNDERLINE, width=W_PRICE)
            
            # Action Buttons
            btn_check = ft.IconButton(
                icon=ft.Icons.CHECK,
                icon_color=ft.Colors.BLUE, # Changed to BLUE to match action
                tooltip="Marcar como Verificado (Azul)"
            )

            btn_del = ft.IconButton(
                icon=ft.Icons.DELETE,
                icon_color=ft.Colors.RED,
                tooltip="Remover",
                on_click=lambda e, prod=p: delete_product(prod)
            )

            # Create Row Container
            row_container = ft.Container(
                content=ft.Row(
                    controls=[
                        txt_barcode,
                        txt_category,
                        txt_flavor,
                        txt_price,
                        ft.Container(
                            content=ft.Row([btn_del, btn_check], spacing=0, alignment=ft.MainAxisAlignment.CENTER), 
                            width=100, 
                            alignment=ft.alignment.center
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER
                ),
                bgcolor=row_color,
                key=p['barcode'], 
                padding=5
            )
            
            # Use helper to bind with closure
            def make_check_click(prod, ctrl):
                return lambda e: mark_as_checked(e, prod, ctrl)
            
            btn_check.on_click = make_check_click(p, row_container)

            # Bind Callbacks
            def make_on_change(prod, field_name):
                 return lambda e: update_product_data(prod, field_name, e.control.value)
            
            def make_on_blur(prod, col_ctrl):
                return lambda e: mark_edited(e, prod, col_ctrl)

            txt_barcode.on_change = make_on_change(p, 'barcode')
            txt_barcode.on_blur = make_on_blur(p, row_container)
            
            txt_category.on_change = make_on_change(p, 'categoria')
            txt_category.on_blur = make_on_blur(p, row_container)
            
            txt_flavor.on_change = make_on_change(p, 'sabor')
            txt_flavor.on_blur = make_on_blur(p, row_container)
            
            txt_price.on_change = make_on_change(p, 'preco')
            txt_price.on_blur = make_on_blur(p, row_container)

            products_list.controls.append(row_container)
            
        page.update()

    def load_products(e):
        source = dd_source_store.value
        if not source:
            show_snack("Selecione uma loja de origem!", ft.Colors.RED)
            return
        
        status_text.value = "Carregando..."
        page.update()
        
        try:
            prods = db.get_all_products(shop_name=source)
            current_products.clear()
            current_products.extend(prods)
            # Reset reviewed status
            for p in current_products:
                p['reviewed'] = False
                p['scanned'] = False
                
            refresh_table()
            status_text.value = f"{len(prods)} produtos carregados de {source}."
            
            # Auto-fill target if empty
            if not input_target_store.value:
                input_target_store.value = source
            
            # Lock source store/load, enable add
            dd_source_store.disabled = True
            btn_load.disabled = True
            btn_add.disabled = False
                
        except Exception as ex:
            status_text.value = f"Erro: {ex}"
            print(ex)
            
        page.update()

    def on_barcode_scanned(e):
        barcode = input_barcode.value.strip()
        if not barcode:
            return
        
        found_data = None
        for p in current_products:
            if p['barcode'] == barcode:
                p['reviewed'] = True
                p['scanned'] = True # Mark as scanned
                found_data = p
                break
        
        if found_data:
            # Find the control in the ListView
            found_control = None
            found_index = -1
            
            for i, ctrl in enumerate(products_list.controls):
                if ctrl.key == barcode:
                    found_control = ctrl
                    found_index = i
                    break
            
            if found_control:
                # Update color
                found_control.bgcolor = ft.Colors.BLUE_900
                found_control.update()
                
                # Scroll to it by calculated offset (since key/index had issues)
                # Estimated row height set to 57 (between 55 undershoot and 60 overshoot)
                row_height = 57 
                scroll_offset = found_index * row_height
                
                try:
                    products_list.scroll_to(offset=scroll_offset, duration=0)
                except Exception as ex:
                    print(f"Scroll error: {ex}")
                    
                show_snack(f"Produto {barcode} verificado!")
            else:
                # Fallback
                refresh_table()
                # Find index again
                for i, p in enumerate(current_products):
                    if p['barcode'] == barcode:
                         row_height = 57
                         scroll_offset = i * row_height
                         try:
                             # We need to find the control to color it
                             products_list.controls[i].bgcolor = ft.Colors.BLUE_900
                             products_list.update()
                             products_list.scroll_to(offset=scroll_offset, duration=0)
                         except: pass
                         break
                
                show_snack(f"Produto {barcode} verificado!")
                
        else:
            show_snack(f"Produto {barcode} não encontrado na lista!", ft.Colors.RED)
            
        input_barcode.value = ""
        input_barcode.focus()

    def delete_product(prod):
        if prod in current_products:
            deleted_products.append(prod)
            current_products.remove(prod)
            refresh_table()

    def delete_all_products(e):
        deleted_products.extend(current_products)
        current_products.clear()
        refresh_table()

    def sync_to_dynamodb(e):
        target = input_target_store.value.strip()
        source = dd_source_store.value
        
        if not target:
            show_snack("Defina a loja de destino!", ft.Colors.RED)
            return

        # Check existing shops
        existing_shops = db.get_shops()
        is_new_store = target not in existing_shops
        
        # VALIDATION: Target must be Source OR New. cannot be a different existing store.
        if (target != source) and (not is_new_store):
             show_snack(f"ERRO: Loja destino '{target}' já existe e é diferente da origem.", ft.Colors.RED)
             print(f"Sync Blocked: Target '{target}' exists and != Source '{source}'")
             return

        items_to_add = []
        if is_new_store:
            # New Store: Upload EVERYTHING
            items_to_add = list(current_products)
            show_snack(f"Loja nova detected. Preparando migração completa ({len(items_to_add)} produtos)...", ft.Colors.BLUE)
        else:
            # Existing Store (Must be Source): Sync only changes
            items_to_add = [p for p in current_products if p.get('reviewed', False)]

        # Check if there is anything to do
        if not items_to_add and not deleted_products:
            show_snack("Nada para sincronizar (apenas itens Verdes/Azuis ou Deletados são processados)!", ft.Colors.RED)
            return
        
        total_add = len(items_to_add)
        total_del = len(deleted_products)
        
        btn_sync.disabled = True
        status_text.value = f"Sincronizando: {total_add} envios, {total_del} remoções..."
        page.update()
        
        try:
            # Process Deletions
            for i, p in enumerate(deleted_products):
                status_text.value = f"Removendo {i+1}/{total_del}: {p['barcode']}..."
                page.update()
                db.delete_product(p['barcode'], target)
            
            # Process Additions/Updates
            for i, p in enumerate(items_to_add):
                status_text.value = f"Enviando {i+1}/{total_add}: {p['barcode']}..."
                page.update()
                db.add_product(p, target)
                
            show_snack(f"Sincronização Fim: {total_add} enviados, {total_del} removidos em '{target}'.")
            
            # Clear deletion tracking after successful sync
            deleted_products.clear()
            status_text.value = "Pronto."
            
            # If it was a new store, we might want to reload the dropdown source list, 
            # but db.get_shops() is called dynamically so it should be fine if we add logic to add shop later.
            
        except Exception as ex:
            print(ex)
            show_snack(f"Erro durante sincronização: {ex}", ft.Colors.RED)
            
        btn_sync.disabled = False
        page.update()

    # Layout
    
    btn_load = ft.ElevatedButton("Carregar Produtos", on_click=load_products)
    btn_add = ft.ElevatedButton("Adicionar Produto", icon=ft.Icons.ADD, on_click=add_new_product, bgcolor=ft.Colors.GREEN, color=ft.Colors.WHITE, disabled=True)
    btn_sync = ft.ElevatedButton("Enviar para DynamoDB", on_click=sync_to_dynamodb, bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE)
    
    header = ft.Row(
        controls=[
            dd_source_store,
            btn_load,
            btn_add,
            ft.VerticalDivider(width=20),
            input_target_store,
            btn_sync
        ],
        alignment=ft.MainAxisAlignment.START,
    )
    
    search_area = ft.Row(
        controls=[input_barcode],
        alignment=ft.MainAxisAlignment.CENTER
    )
    
    # Header Row (Defined late to access callbacks)
    header_row = ft.Row(
        controls=[
            ft.Container(ft.TextButton("Código", on_click=lambda e: header_click(0)), width=W_CODE),
            ft.Container(ft.TextButton("Categoria", on_click=lambda e: header_click(1)), width=W_CAT),
            ft.Container(ft.TextButton("Sabor", on_click=lambda e: header_click(2)), width=W_FLAV),
            ft.Container(ft.TextButton("Preço", on_click=lambda e: header_click(3)), width=W_PRICE),
            ft.Container(
                ft.IconButton(
                    icon=ft.Icons.DELETE_SWEEP, 
                    icon_color=ft.Colors.RED, 
                    tooltip="Limpar Tudo (Locamente)",
                    on_click=delete_all_products
                ), 
                width=100,
                alignment=ft.alignment.center
            ),
        ],
        alignment=ft.MainAxisAlignment.CENTER # Center the header
    )
    
    page.add(
        ft.Text("Gerenciador de Lojas & Produtos", size=24, weight=ft.FontWeight.BOLD),
        header,
        ft.Divider(),
        search_area,
        status_text,
        header_row, # Add Header Row
        products_list # Add ListView
    )

if __name__ == "__main__":
    ft.app(target=main)
