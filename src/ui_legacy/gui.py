import tkinter as tk
from tkinter import ttk, messagebox
import ctypes
import platform
import threading
import time
import unicodedata
import uuid

import src.db_sqlite as db
import src.sale as sale
from src.serial_scanner import SerialScanner
from src.sync_core import SyncClient

# Constants for UI scaling
BASE_WIDTH = 1920
BASE_HEIGHT = 1080
Version = "2.2.1-Tkinter"

def is_numlock_on():
    if platform.system() != 'Windows':
        return True
    hllDll = ctypes.WinDLL ("User32.dll")
    VK_NUMLOCK = 0x90
    return hllDll.GetKeyState(VK_NUMLOCK) & 1


def set_numlock(state=True):
    if platform.system() != 'Windows':
        return
    hllDll = ctypes.WinDLL ("User32.dll")
    VK_NUMLOCK = 0x90
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002

    current_state = is_numlock_on()
    if current_state != state:
        hllDll.keybd_event(VK_NUMLOCK, 0x45, KEYEVENTF_EXTENDEDKEY | 0, 0)
        hllDll.keybd_event(VK_NUMLOCK, 0x45, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


class POSApplication:
    def __init__(self, root):
        self.root = root
        self.root.withdraw()
        self.barcode_entry = None
        self.sale_frame = None
        self.stored_sale_frame = None
        self.final_price_label = None
        self.status_label = None
        self.filtered_products = [] 
        self.status_label = None
        self.filtered_products = [] 
        self.category_quantities = {}
        
        # Scanner & Sync Init
        self.serial_scanner = None
        self.scanner_lock = threading.Lock()
        self.scanner_initializing = False

        # Change Calculator Vars
        self.received_var = tk.StringVar()
        self.change_label = None

        set_numlock(True)
        self.root.bind_all("<Num_Lock>", lambda event: (set_numlock(state=True), "break")[1])
        
        # Init Scanner in bg
        threading.Thread(target=self.init_serial_scanner, daemon=True).start()

        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.scale_factor = min(self.screen_width / BASE_WIDTH, self.screen_height / BASE_HEIGHT)

        self.product_db = db.Database()
        self.selected_shop_var = tk.StringVar()
        self.sale = None
        self.stored_sales = []
        self.product_widgets = {}
        
        self.manual_add_count = 0
        self.manual_add_list = []

        # Auto-select default shop
        shops = self.product_db.get_shops()
        
        # Priority: DB Config (from Launcher) -> First in list -> Default
        selected = self.product_db.get_selected_shop()
        if selected and selected in shops:
             default_shop = selected
        else:
             default_shop = shops[0] if shops else "Sorveteria"
             
        self.selected_shop_var.set(default_shop)
        
        self.sale = sale.Sale(self.product_db, default_shop, payment_method="")
        self.build_main_window()


    def build_main_window(self):
        self.root.deiconify()
        self.root.title("Sorveteria Lolla")
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg="#1a1a2e")

        # Fonts
        title_font = ("Arial", int(35 * self.scale_factor), "bold")
        shop_font = ("Arial", int(32 * self.scale_factor))
        entry_font = ("Arial", int(16 * self.scale_factor))
        label_font = ("Arial", int(16 * self.scale_factor))
        button_font = ("Arial", int(14 * self.scale_factor))
        final_price_font = ("Arial", int(50 * self.scale_factor), "bold")

        # Header Text Frame (Top Left)
        header_frame = tk.Frame(self.root, bg="#1a1a2e")
        header_frame.grid(row=0, column=0, columnspan=2, sticky="nw", padx=int(20 * self.scale_factor), pady=int(20 * self.scale_factor))

        # Title Label
        title_label = ttk.Label(header_frame, text="Sorveteria Lolla", font=title_font, background="#1a1a2e",
                                foreground="#ffffff")
        title_label.pack(anchor="w")

        # Selected Shop Label
        selected_shop_label = ttk.Label(
            header_frame, text=f"{self.selected_shop_var.get()}", background="#1a1a2e",
            foreground="#ffffff", font=shop_font
        )
        selected_shop_label.pack(anchor="w")

        # Version Tag
        version_label = tk.Label(
            header_frame, text=f"v{Version}", font=("Arial", int(12 * self.scale_factor)),
            bg="#1a1a2e", fg="#555555"
        )
        version_label.pack(anchor="w")

        # Configure grid
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=0)
        self.root.grid_columnconfigure(2, weight=1)
        self.root.grid_rowconfigure(2, weight=0)
        self.root.grid_rowconfigure(3, weight=1) # Spacer area

        # Control Frame (Minimize/Close)
        control_frame = tk.Frame(self.root, bg="#1a1a2e")
        control_frame.grid(row=0, column=2, sticky="ne", padx=int(10 * self.scale_factor), pady=int(10 * self.scale_factor))

        close_button = tk.Button(
            control_frame, text="✖", command=self.close_application, bg="#1a1a2e", fg="red",
            font=("Arial", int(16 * self.scale_factor)), borderwidth=0, width=3
        )
        close_button.pack(side=tk.RIGHT, padx=(0, 5))

        minimize_button = tk.Button(
            control_frame, text="—", command=self.root.iconify, bg="#1a1a2e", fg="#ffffff",
            font=("Arial", int(16 * self.scale_factor)), borderwidth=0, width=3
        )
        minimize_button.pack(side=tk.RIGHT)

        # Barcode Entry
        self.barcode_entry = ttk.Combobox(self.root, state="normal", font=entry_font, width=45)
        self.barcode_entry.grid(
            row=0, column=0, columnspan=3, padx=int(0 * self.scale_factor),
            pady=int(5 * self.scale_factor), sticky=""
        )
        self.barcode_entry.bind('<Return>', self.handle_barcode)
        self.barcode_entry.bind('<KeyRelease>', self.search_products)

        # Sale Frame
        self.sale_frame = tk.Frame(self.root, bg="#1a1a2e")
        self.sale_frame.grid(
            row=2, column=0, padx=int(10 * self.scale_factor),
            pady=int(10 * self.scale_factor), sticky="nw"
        )

        #Stored Sale Frame
        self.stored_sale_frame = tk.Frame(self.root, bg="#1a1a2e")
        self.stored_sale_frame.grid(
            row=2, column=0, padx=int(30 * self.scale_factor),
            pady=int(700 * self.scale_factor), sticky="nw"
        )

        # Final Price Label
        self.final_price_label = tk.Label(
            self.root, text="R$0.00", font=final_price_font, bg="#1a1a2e",
            fg="#ffffff"
        )
        self.final_price_label.grid(
            row=1, column=2, columnspan=3, pady=int(25 * self.scale_factor),
            padx=int(50 * self.scale_factor), sticky="ne"
        )

        # Right Panel Frame for Buttons and Calculator
        self.right_panel_frame = tk.Frame(self.root, bg="#1a1a2e")
        self.right_panel_frame.grid(
            row=2, column=2, padx=int(50 * self.scale_factor),
            pady=int(10 * self.scale_factor), sticky="ne"
        )

        # Money Change Calculator (Now at the top of right panel)
        calc_frame = tk.Frame(self.right_panel_frame, bg="#1a1a2e")
        calc_frame.pack(pady=(0, 20), fill=tk.X)

        tk.Label(calc_frame, text="Calculadora de Troco", font=("Arial", int(14 * self.scale_factor)), bg="#1a1a2e", fg="#aaaaaa").pack(pady=(0,5), anchor="w")
        
        tk.Label(calc_frame, text="Recebido:", font=("Arial", int(12 * self.scale_factor)), bg="#1a1a2e", fg="white").pack(anchor="w")
        entry_received = tk.Entry(calc_frame, textvariable=self.received_var, font=("Arial", int(14 * self.scale_factor)))
        entry_received.pack(fill="x")
        
        tk.Label(calc_frame, text="Troco:", font=("Arial", int(12 * self.scale_factor)), bg="#1a1a2e", fg="white").pack(anchor="w", pady=(5,0))
        self.change_label = tk.Label(calc_frame, text="R$ 0.00", font=("Arial", int(20 * self.scale_factor), "bold"), bg="#1a1a2e", fg="#00ff00")
        self.change_label.pack(anchor="w")
        
        self.received_var.trace("w", self.calculate_change)

        # Finalize Sale Button
        finalize_sale_button = tk.Button(
            self.right_panel_frame, text="Finalizar compra", font=button_font,
            command=lambda: self.finalize_sale(self.sale.id), height=2,
            bg="#00aa00", fg="white"
        )
        finalize_sale_button.pack(pady=(0, 20), fill=tk.X)

        # FAB Container (Bottom Right)
        self.fab_frame = tk.Frame(self.root, bg="#1a1a2e")
        # Use place for absolute positioning to ensure visibility and alignment at bottom-right
        # Same vertical level as stored_sale_frame roughly
        self.fab_frame.place(relx=1.0, rely=1.0, anchor="se", x=-20, y=-20)

        # Scanner FAB (Functional)
        self.scanner_fab = tk.Button(
            self.fab_frame, text="USB", # Icon fallback
            command=self.reconnect_scanner,
            font=("Arial", 12, "bold"), width=4, height=2,
            bg="#0088cc", fg="white", activebackground="#006699", activeforeground="white"
        )
        self.scanner_fab.pack(side=tk.LEFT, padx=5)

        # Register FAB (Moved)
        self.register_fab = tk.Button(
            self.fab_frame, text="+", 
            command=self.edit_product,
            font=("Arial", 12, "bold"), width=4, height=2,
            bg="#0088cc", fg="white", activebackground="#006699", activeforeground="white"
        )
        self.register_fab.pack(side=tk.LEFT, padx=5)

        # History FAB (Disabled)
        self.history_fab = tk.Button(
            self.fab_frame, text="Hist", 
            command=None,
            font=("Arial", 12, "bold"), width=4, height=2,
            bg="#555555", fg="#aaaaaa", state=tk.DISABLED
        )
        self.history_fab.pack(side=tk.LEFT, padx=5)

        # Sync FAB
        self.sync_fab = tk.Button(
            self.fab_frame, text="Sync", 
            command=self.run_sync,
            font=("Arial", 12, "bold"), width=4, height=2,
            bg="#0088cc", fg="white", activebackground="#006699", activeforeground="white"
        )
        self.sync_fab.pack(side=tk.LEFT, padx=5)

        self.update_sale_display()
        self.root.grid_rowconfigure(4, weight=1)


    def strip_accents(self, text):
        if not text: return ""
        text = unicodedata.normalize('NFD', text) \
            .encode('ascii', 'ignore') \
            .decode("utf-8")
        return str(text)

    def search_products(self, event=None, force_search=False):
        if event and event.keysym in ['Return', 'Up', 'Down', 'Left', 'Right']:
            return

        search_term = self.barcode_entry.get()

        if not search_term.isdigit() or force_search:
            if search_term:
                search_term = self.strip_accents(search_term.lower())
                shop = self.selected_shop_var.get()

                if ',' in search_term:
                    search_term = search_term.replace(',', '.')

                self.filtered_products = self.product_db.search_products(search_term, shop)

                self.barcode_entry['values'] = [
                    f"{p['barcode']} - {p['categoria']} ({p['sabor']}) - R${p['preco']:.2f}".replace('.', ',')
                    for p in self.filtered_products
                ]

                if self.barcode_entry['values']:
                    self.barcode_entry.event_generate("<<ComboboxSelected>>")

                self.barcode_entry.bind("<<ComboboxSelected>>", self.handle_product_selection)

    def handle_product_selection(self, event):
        selected_index = self.barcode_entry.current()
        if selected_index != -1 and 0 <= selected_index < len(self.filtered_products):
            selected_product = self.filtered_products[selected_index]
            self.sale.add_product(selected_product)
            self.update_sale_display()
            self.barcode_entry.delete(0, 'end')
            self.barcode_entry['values'] = []

    def confirm_read_error(self, barcode):
        def compare(event=None):
            entered_barcode = barcode_input.get()
            if entered_barcode:
                if entered_barcode == barcode:
                    self.edit_product(barcode=entered_barcode)
                else:
                    self.barcode_entry.set(entered_barcode)
                    self.handle_barcode()
                barcode_error_window.destroy()

        barcode_error_window = tk.Toplevel(self.root)
        barcode_error_window.title("Possível erro de leitura")
        barcode_error_window.configure(bg="#8b0000")
        barcode_error_window.attributes("-topmost", True)

        win_width = int(400 * self.scale_factor)
        win_height = int(200 * self.scale_factor)
        barcode_error_window.geometry(f"{win_width}x{win_height}")
        barcode_error_window.resizable(False, False)
        barcode_error_window.grab_set()

        barcode_error_window.update_idletasks()
        x = (barcode_error_window.winfo_screenwidth() // 2) - (win_width // 2)
        y = (barcode_error_window.winfo_screenheight() // 2) - (win_height // 2)
        barcode_error_window.geometry(f"+{x}+{y}")

        title_font = ("Arial", int(20 * self.scale_factor), "bold")
        input_font = ("Arial", int(14 * self.scale_factor))

        tk.Label(
            barcode_error_window, text="Escaneie novamente",
            bg="#8b0000", fg="#ffffff", font=title_font
        ).pack(pady=int(10 * self.scale_factor))

        barcode_input = ttk.Entry(
            barcode_error_window, font=input_font, width=20
        )
        barcode_input.pack(
            padx=int(20 * self.scale_factor),
            pady=int(10 * self.scale_factor)
        )
        barcode_input.bind("<Return>", compare)
        barcode_input.focus_set()

    def handle_barcode(self, event=None):
        input_barcode = self.barcode_entry.get().strip()
        if not input_barcode:
            return
        
        current_shop = self.selected_shop_var.get()

        if ',' in input_barcode or '.' in input_barcode:
            try:
                value = float(input_barcode.replace(",", "."))
                self.manual_add_count += 1
                product_id = f'Manual_{self.manual_add_count}'
                product = {
                    'product_id': product_id,
                    'barcode': product_id,
                    'categoria': 'Nao cadastrado',
                    'sabor': '',
                    'preco': value
                }
                self.manual_add_list.append(product)
                self.sale.add_product(product)
                self.update_sale_display(focus_on_=product)
                self.barcode_entry.delete(0, 'end')
                return
            except ValueError:
                pass

        if not input_barcode.isdigit():
             self.barcode_entry.event_generate('<Down>')
             return

        matching_products = self.product_db.get_products_by_barcode_and_shop(input_barcode, current_shop)

        if not matching_products:
            self.confirm_read_error(barcode=input_barcode)
        else:
            if len(matching_products) == 1:
                product = matching_products[0]
                self.sale.add_product(product)
                self.update_sale_display(focus_on_=product)
            else:
                self.search_products(force_search=True)
                self.barcode_entry.event_generate('<Down>')
                return

        self.barcode_entry.delete(0, 'end')

    def calculate_change(self, *args):
        try:
            val_str = self.received_var.get().replace(',', '.')
            if not val_str:
                self.change_label.config(text="R$ 0.00", fg="#00ff00")
                return
            received = float(val_str)
            total = self.sale.final_price
            change = received - total
            if change < 0:
                self.change_label.config(text=f"Falta R${abs(change):.2f}", fg="#ff5555")
            else:
                self.change_label.config(text=f"R${change:.2f}", fg="#00ff00")
        except ValueError:
            self.change_label.config(text="---", fg="white")

    def create_or_update_product_widget(self, product_id, details):
        if product_id not in self.product_widgets:
            row = len(self.product_widgets)

            text_widget = tk.Text(
                self.sale_frame, height=1, width=35, bg="#1a1a2e", fg="#ffffff",
                font=("Arial", 18), bd=0, highlightthickness=0
            )
            text_widget.grid(row=row, column=0, padx=50, pady=2, sticky="w")
            
            display_text = details['categoria']
            if details['sabor']:
                display_text += f" - {details['sabor']}"
            
            text_widget.insert(tk.END, display_text)
            text_widget.config(state=tk.DISABLED)

            price_label = tk.Label(
                self.sale_frame, text="", bg="#1a1a2e",
                fg="#ffffff", font=("Arial", 18)
            )
            price_label.grid(row=row, column=2, padx=5, pady=2)

            quantity_var = tk.StringVar(value=str(details['quantidade']))
            quantity_entry = ttk.Entry(
                self.sale_frame, textvariable=quantity_var, width=5, font=("Arial", 18)
            )
            quantity_entry.grid(row=row, column=1, padx=5, pady=2)
            quantity_entry.bind("<KeyRelease>", lambda event: self.update_quantity_dynamic(product_id, quantity_var))
            quantity_entry.bind("<FocusIn>", self.select_all_text)

            delete_button = tk.Button(
                self.sale_frame, text="✖",
                command=lambda b=product_id: self.delete_product(b),
                bg="#ff5555", fg="#ffffff", font=("Arial", int(14 * self.scale_factor), "bold"),
                borderwidth=0, width=3
            )
            delete_button.grid(row=row, column=3, padx=5, pady=2)

            self.product_widgets[product_id] = {
                'text_widget': text_widget,
                'price_label': price_label,
                'quantity_var': quantity_var,
                'quantity_entry': quantity_entry,
                'delete_button': delete_button
            }
            
            if not str(product_id).startswith('Manual'):
                edit_button = tk.Button(
                    self.sale_frame, text="✎",
                    command=lambda b=product_id: self.edit_product(product_id=b),
                    bg="#444466", fg="#ffffff", font=("Arial", int(14 * self.scale_factor)),
                    borderwidth=0, width=3
                )
                edit_button.grid(row=row, column=4, padx=5, pady=2)
                self.product_widgets[product_id]['edit_button'] = edit_button

        else:
            widgets = self.product_widgets[product_id]
            widgets['text_widget'].config(state=tk.NORMAL)
            widgets['text_widget'].delete("1.0", tk.END)
            display_text = details['categoria']
            if details['sabor']:
                display_text += f" - {details['sabor']}"
            widgets['text_widget'].insert(tk.END, display_text)
            widgets['text_widget'].config(state=tk.DISABLED)
            widgets['quantity_var'].set(str(details['quantidade']))

        widgets = self.product_widgets[product_id]
        price = details['preco']
        widgets['price_label'].config(text=f"R${price:.2f}", fg="#ffffff")


    def update_sale_display(self, focus_on_=None):
        final_price = self.sale.calculate_total()
        self.final_price_label.config(text=f"R${final_price:.2f}")

        # Recalculate change if valid
        self.calculate_change()

        for product_id in list(self.sale.current_sale.keys()):
            sale_item = self.sale.current_sale[product_id]
            product_info = self.product_db.get_product_info(product_id, self.sale.shop)

            if not product_info:
                 for m in self.manual_add_list:
                     if m['product_id'] == product_id:
                         product_info = m
                         break
            if not product_info:
                product_info = sale_item
            
            details = {
                'categoria': product_info.get('categoria', ''),
                'sabor': product_info.get('sabor', ''),
                'preco': sale_item['preco'], 
                'quantidade': sale_item['quantidade'],
                'product_id': product_id
            }
            
            self.create_or_update_product_widget(product_id, details)

        self.root.bind("<Return>", lambda event: (self.barcode_entry.focus(), "break")[1])
        self.root.bind("<F12>", lambda event: (self.F12_press_handle(), "break")[1])
        self.root.bind("<End>", lambda event: (self.F12_press_handle(), "break")[1])
        self.root.bind("<F10>", lambda event: (self.new_sale(), "break")[1])
        self.root.bind("<F11>", lambda event: (self.finalize_sale(internal_id=self.sale.id), "break")[1])

        self.create_or_update_sale_widgets(self.sale.id)

    def F12_press_handle(self):
        self.barcode_entry.focus()
        self.barcode_entry.delete(0, 'end')

    def select_all_text(self, event):
        event.widget.select_range(0, 'end')
        event.widget.icursor('end')
        return 'break'

    def update_quantity_dynamic(self, product_id, quantity_var):
        try:
            val = quantity_var.get().replace(',', '.')
            if not val: return
            new_quantity = float(val)
            
            if new_quantity <= 0:
                self.delete_product(product_id)
            elif product_id in self.sale.current_sale:
                self.sale.current_sale[product_id]['quantidade'] = new_quantity
            
            self.update_sale_display()
        except ValueError:
            pass

    def delete_product(self, product_id):
        self.sale.remove_product(product_id)
        if product_id in self.product_widgets:
            for widget in self.product_widgets[product_id].values():
                 if hasattr(widget, 'grid_forget'):
                     widget.grid_forget()
                     widget.destroy()
            del self.product_widgets[product_id]
        
        for idx, (pid, widgets) in enumerate(self.product_widgets.items()):
            widgets['text_widget'].grid(row=idx, column=0, padx=50, pady=2, sticky="w")
            widgets['quantity_entry'].grid(row=idx, column=1, padx=5, pady=2)
            widgets['price_label'].grid(row=idx, column=2, padx=5, pady=2)
            widgets['delete_button'].grid(row=idx, column=3, padx=5, pady=2)
            if 'edit_button' in widgets:
                 widgets['edit_button'].grid(row=idx, column=4, padx=5, pady=2)

    def edit_product(self, product_id=None, barcode=None):
        current_shop = self.selected_shop_var.get()
        current_barcode = ""
        current_sabor = ""
        current_categoria = ""
        current_preco = ""
        
        if product_id:
             p = self.product_db.get_product_info(product_id, current_shop)
             if p:
                 current_barcode = p['barcode']
                 current_sabor = p['sabor']
                 current_categoria = p['categoria']
                 current_preco = str(p['preco'])
        elif barcode:
             current_barcode = barcode

        def save_changes():
            try:
                new_barcode = barcode_entry.get().strip().upper() 
                new_sabor = sabor_entry.get().strip().capitalize()
                new_categoria = categoria_entry.get().strip().capitalize()
                new_preco = preco_entry.get().strip().replace(',', '.')
                
                if not all([new_barcode, new_categoria, new_preco]):
                     messagebox.showerror("Erro", "Campos obrigatorios: Barcode, Categoria, Preco")
                     return
                
                price_val = float(new_preco)
                
                info = {
                    'product_id': product_id, 
                    'barcode': new_barcode,
                    'sabor': new_sabor,
                    'categoria': new_categoria,
                    'preco': price_val
                }
                
                new_id = self.product_db.add_product(info, current_shop)
                
                if product_id and product_id in self.sale.current_sale:
                     self.sale.current_sale[product_id]['preco'] = price_val
                     self.sale.current_sale[product_id]['categoria'] = new_categoria
                     self.sale.current_sale[product_id]['sabor'] = new_sabor
                     
                self.update_sale_display()
                edit_window.destroy()
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao salvar: {e}")

        edit_window = tk.Toplevel(self.root)
        edit_window.title("Editar Produto")
        edit_window.configure(bg="#8b0000")
        edit_window.attributes("-topmost", True)
        
        input_frame = tk.Frame(edit_window, bg="#8b0000")
        input_frame.pack(pady=10, padx=10)
        
        tk.Label(input_frame, text="Barcode:", bg="#8b0000", fg="white").grid(row=0, column=0)
        barcode_entry = tk.Entry(input_frame)
        barcode_entry.grid(row=0, column=1)
        barcode_entry.insert(0, current_barcode)
        
        tk.Label(input_frame, text="Sabor:", bg="#8b0000", fg="white").grid(row=1, column=0)
        sabor_entry = tk.Entry(input_frame) 
        sabor_entry.grid(row=1, column=1)
        sabor_entry.insert(0, current_sabor)

        tk.Label(input_frame, text="Categoria:", bg="#8b0000", fg="white").grid(row=2, column=0)
        categoria_entry = tk.Entry(input_frame)
        categoria_entry.grid(row=2, column=1)
        categoria_entry.insert(0, current_categoria)

        tk.Label(input_frame, text="Preco:", bg="#8b0000", fg="white").grid(row=3, column=0)
        preco_entry = tk.Entry(input_frame)
        preco_entry.grid(row=3, column=1)
        preco_entry.insert(0, current_preco)
        
        tk.Button(edit_window, text="Salvar", command=save_changes).pack(pady=10)


    def finalize_sale(self, internal_id):
        sale_obj = next((s for s in self.stored_sales if s.id == internal_id), None)
        if not sale_obj and self.sale.id == internal_id:
            sale_obj = self.sale
            
        if not sale_obj or not sale_obj.current_sale:
            messagebox.showerror("Erro", "Venda vazia")
            return
            
        final_price = sale_obj.calculate_total()
        
        def record():
            self.product_db.record_sale(final_price, "Legacy (N/A)", sale_obj.current_sale)
        
        threading.Thread(target=record).start()
        
        self.delete_stored_sale(internal_id)

    def new_sale(self, sale_=None):
        if sale_ is None:
             self.sale = sale.Sale(self.product_db, self.selected_shop_var.get())
        else:
             self.sale = sale_
        
        for widget in self.sale_frame.winfo_children():
            widget.grid_forget()
            widget.destroy()
        self.product_widgets.clear()
        
        self.barcode_entry.delete(0, 'end')
        self.received_var.set("") # Clear calculator
        self.update_sale_display()

    def create_or_update_sale_widgets(self, id):
        if id not in [s.id for s in self.stored_sales]:
             self.stored_sales.append(self.sale)
         
        for widget in self.stored_sale_frame.winfo_children():
            widget.destroy()

        # "Nova Venda" (+) Button at the START (Left)
        new_sale_btn = tk.Button(
            self.stored_sale_frame, text="+", 
            command=lambda: self.new_sale(None), # Force new empty sale
            bg="#444444", fg="white", font=("Arial", 20, "bold"), width=3
        )
        new_sale_btn.grid(row=0, column=0, padx=15)
            
        for i, s in enumerate(self.stored_sales):
             container = tk.Frame(self.stored_sale_frame, bg="#1a1a2e")
             container.grid(row=0, column=i+1, padx=5) # Shift by 1
             
             # Sale Price (Open/Edit)
             btn = tk.Button(
                 container, text=f"R${s.final_price:.2f}",
                 font=("Arial", 16), command=lambda sid=s.id: self.open_sale(sid),
                 bg="#4444aa", fg="white", width=8
             )
             btn.pack(side=tk.LEFT)
             
             # Checkmark (Finalize)
             chk_btn = tk.Button(
                 container, text="✔", command=lambda sid=s.id: self.finalize_sale(sid),
                 bg="#00aa00", fg="white", font=("Arial", 14), width=3
             )
             chk_btn.pack(side=tk.LEFT, padx=1)
             
             # X (Close/Delete)
             del_btn = tk.Button(
                 container, text="X", command=lambda sid=s.id: self.delete_stored_sale(sid),
                 bg="#aa4444", fg="white", font=("Arial", 14), width=3
             )
             del_btn.pack(side=tk.LEFT, padx=1)


    def delete_stored_sale(self, id):
        if not messagebox.askyesno("Confirmar remoção", "Tem certeza que deseja apagar esta venda em aberto?"):
            return

        to_rem = next((s for s in self.stored_sales if s.id == id), None)
        if to_rem:
             self.stored_sales.remove(to_rem)
        
        # If we deleted the active sale, switch to another or clear
        if self.sale.id == id:
             if self.stored_sales:
                 self.open_sale(self.stored_sales[0].id)
             else:
                 self.new_sale()
        else:
            self.create_or_update_sale_widgets(self.sale.id) # Refresh list

    def open_sale(self, id):
        s = next((x for x in self.stored_sales if x.id == id), None)
        if s:
            self.new_sale(s)

    def close_application(self):
        if self.serial_scanner:
             self.serial_scanner.stop()
        self.root.quit()
        self.root.destroy()
        
    def init_serial_scanner(self):
        # Prevent double init
        if not self.scanner_lock.acquire(blocking=False):
            return

        try:
            if self.scanner_initializing: return
            self.scanner_initializing = True
            time.sleep(2.0) # Wait for UI

            # 1. Get Config
            port = self.product_db.get_config('scanner_port')
            
            if not port:
                port = SerialScanner.find_scanner_port()
            
            # Ensure any previous scanner is stopped
            if self.serial_scanner: 
                 try: self.serial_scanner.stop()
                 except: pass

            if port:
                try:
                    self.serial_scanner = SerialScanner(port=port)
                    self.serial_scanner.set_callback(self.on_barcode_scanned)
                    self.serial_scanner.set_error_callback(self.on_scanner_error)
                    started = self.serial_scanner.start()
                    
                    if started:
                        self.update_scanner_status(True, port)
                    else:
                        self.update_scanner_status(False)
                except Exception as e:
                     print(f"Error starting scanner: {e}")
                     self.update_scanner_status(False)
            else:
                 self.update_scanner_status(False)
                 
        except Exception as e:
             print(f"CRITICAL ERROR in init_serial_scanner: {e}")
        finally:
            self.scanner_initializing = False
            self.scanner_lock.release()

    def update_scanner_status(self, connected, port=""):
         def _update():
             if hasattr(self, 'scanner_fab'):
                 if connected:
                     self.scanner_fab.config(bg="#00aa00", activebackground="#00aa00") # Green
                 else:
                     self.scanner_fab.config(bg="#aa0000", activebackground="#aa0000") # Red
         self.root.after(0, _update)

    def on_barcode_scanned(self, barcode):
        # Thread-safe callback
        self.root.after(0, lambda: self.handle_barcode_event(barcode))
        
    def handle_barcode_event(self, barcode):
        # Only inject if we are focused on main window or barcode entry?
        # Actually scanner acts as keyboard usually, but serial scanner is separate.
        # So we manually inject into handle_barcode logic.
        if barcode:
             self.barcode_entry.set(barcode)
             self.handle_barcode()

    def on_scanner_error(self, msg):
        print(f"Scanner Error: {msg}")
        self.update_scanner_status(False)
        
    def reconnect_scanner(self):
        print("Reconnecting scanner...")
        if self.serial_scanner:
            self.serial_scanner.stop()
        
        # Set to grey/loading
        if hasattr(self, 'scanner_fab'):
             self.scanner_fab.config(bg="#888888")
             
        threading.Thread(target=self.init_serial_scanner, daemon=True).start()

    def run_sync(self):
        print("Running manual sync...")
        self.sync_fab.config(bg="#aaaa00", text="...") # Yellowish
        self.show_toast("Sincronizando...", bg="#aaaa00")
        
        def _sync_thread():
             try:
                 client = SyncClient(self.product_db)
                 shop_name = self.selected_shop_var.get()
                 result = client.sync(shop_name=shop_name)
                 
                 msg = f"Sincronização concluída!\nMsg: {result.get('message')}"
                 is_success = result.get('success', True)
                 
                 def _finish():
                     if is_success:
                         self.sync_fab.config(bg="#00aa00", text="Sync")
                         self.show_toast(msg, bg="#00aa00")
                         # messagebox.showinfo("Sucesso", msg) # Removed
                     else:
                         self.sync_fab.config(bg="#aa0000", text="Erro")
                         self.show_toast(msg, bg="#aa0000")
                         # messagebox.showerror("Erro", msg) # Removed
                         
                 self.root.after(0, _finish)
                 
             except Exception as e:
                 def _fail():
                     self.sync_fab.config(bg="#aa0000", text="Erro")
                     self.show_toast(f"Erro Crítico: {str(e)}", bg="#aa0000")
                 self.root.after(0, _fail)

        threading.Thread(target=_sync_thread, daemon=True).start()

    def show_toast(self, message, duration=4000, bg="#333333", fg="white"):
        """
        Displays a non-blocking toast message at the bottom of the screen.
        """
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True) # Remove window decorations
        toast.attributes("-topmost", True)
        toast.config(bg=bg)
        
        lbl = tk.Label(toast, text=message, bg=bg, fg=fg, font=("Arial", 12), padx=20, pady=10)
        lbl.pack()
        
        # Center horizontally at the bottom
        toast.update_idletasks()
        width = toast.winfo_width()
        height = toast.winfo_height()
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        x = (screen_width // 2) - (width // 2)
        y = screen_height - height - 80 # Just above the taskbar/bottom edge
        
        toast.geometry(f"+{x}+{y}")
        
        # Fade out/destroy effect
        def close_toast():
            try:
                toast.destroy()
            except: pass
            
        self.root.after(duration, close_toast)
