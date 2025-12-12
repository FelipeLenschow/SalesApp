
import requests
import json
import sqlite3
import src.db_sqlite as db
from datetime import datetime
import flet as ft
import threading
import time

class SyncClient:
    def __init__(self, server_url, db_instance: db.Database):
        self.server_url = server_url
        self.db = db_instance

    def get_shops(self):
        try:
            response = requests.get(f"{self.server_url}/shops", timeout=5)
            response.raise_for_status()
            return response.json().get("shops", [])
        except Exception as e:
            print(f"Error fetching shops: {e}")
            return []

    def create_shop(self, new_name, new_password, source_name=None, source_password=None):
        payload = {
            "new_name": new_name,
            "new_password": new_password,
            "source_name": source_name,
            "source_password": source_password
        }
        response = requests.post(f"{self.server_url}/create_shop", json=payload, timeout=10)
        response.raise_for_status()
        return response.json()

    def sync(self, password=None, shop_name=None):
        """
        1. Get unsynced sales (For now we assume all sales that are NOT in specific range? 
        2. Send to server.
        3. Receive products.
        4. Update local DB.
        """
        results = {"uploaded": 0, "downloaded": 0, "message": ""}
        
        # 1. Get Sales
        sales_data = []
        try:
            # We don't have a 'synced' column yet.
            # We can treat all local sales as candidates.
            df_sales = self.db.get_sales_history() 
            # df_sales has: Data, Horario, Preco Final, Metodo de pagamento, Produtos
            # We need to convert back to raw format for the API
            
            # Ideally database.get_sales_history() would return raw objects too.
            # Let's read raw table for accuracy.
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT timestamp, final_price, payment_method, products_json FROM sales")
                rows = cursor.fetchall()
                for row in rows:
                    sales_data.append({
                        "timestamp": row[0],
                        "final_price": row[1],
                        "payment_method": row[2],
                        "products_json": row[3]
                    })
        except Exception as e:
            results["message"] = f"Error reading local sales: {e}"
            return results

        # 2. Send to Server
        
        # Get current shop name to filter products (if not passed explicitly)
        if not shop_name:
            shop_name = self.db.get_config('current_shop')
        
        # Use provided password or fallback to stored one
        if not password:
            password = self.db.get_config('shop_password')
        
        payload = {
            "sales": sales_data,
            "shop_name": shop_name,
            "password": password
        }
        
        # NOTE: Exceptions here will propagate to the caller (GUI or auto-sync thread)
        # This is intentional so that initial sync can fail on invalid password.
        response = requests.post(f"{self.server_url}/sync", json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results["uploaded"] = data.get("imported_sales", 0)
        products_update = data.get("products_update", [])

        # 3. Update Local DB
        count = 0
        try:
            # We iterate received products and use db.add_product
            # db.add_product handles INSERT OR IGNORE / UPDATE logic
            for p in products_update:
                product_info = {
                    'barcode': p['barcode'],
                    'categoria': p['categoria'],
                    'sabor': p['sabor'],
                    'preco': p['preco']
                }
                shop_name_p = p.get('shop_name', shop_name) # use p['shop_name'] if available
                self.db.add_product(product_info, shop_name_p)
                count += 1
            
            
            # 4. Update Config
            shop_config = data.get("shop_config", {})
            if shop_config:
                for key, value in shop_config.items():
                    if value is not None:
                        self.db.set_config(key, value)
            
            results["downloaded"] = count
            results["message"] = "Sync completed successfully"
            
        except Exception as e:
            results["message"] = f"Error updating local products: {e}"

        return results


class SyncManager:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.stop_sync_thread = False
        self.sync_fab = None # Will be linked from MainWindow or created here? 
                             # Ideally MainWindow creates FAB and registers it here, or we create it.
                             # For now, we assume App passes it or we find it.

    def start_auto_sync(self):
        while not self.stop_sync_thread:
            try:
                # Wait 30 minutes (1800 seconds)
                # Check smaller intervals to allow faster exit
                for _ in range(1800):
                    if self.stop_sync_thread: break
                    time.sleep(1)
                
                if self.stop_sync_thread: break

                saved_ip = self.app.product_db.get_config('server_ip')
                if saved_ip:
                   print("Auto-sync triggering...")
                   self.run_sync(saved_ip, silent=True)
            except Exception as e:
                print(f"Auto-sync loop error: {e}")
                time.sleep(60) # Wait a bit on error

    def update_fab_status(self, color, tooltip):
        # We need a reference to the FAB
        # Since logic was in ProductApp, it accessed self.sync_fab
        # We can ask app for it
        try:
             if hasattr(self.app, 'sync_fab'):
                self.app.sync_fab.bgcolor = color
                self.app.sync_fab.tooltip = tooltip
                self.app.sync_fab.update()
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
                client = SyncClient(server_url, self.app.product_db)
                result = client.sync()
                print(f"Sync result: {result}")
                
                # Save successful IP
                self.app.product_db.set_config('server_ip', server_url)
                
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
                
                self.update_fab_status(ft.Colors.GREEN, f"Sincronizado: {result.get('message', 'OK')}")

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

    def open_sync_dialog(self, e):
        print("Open Sync Dialog clicked")
        # Pre-fill IP from config
        saved_ip = self.app.product_db.get_config('server_ip') or "http://localhost:8000"
        
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
            self.app.product_db.reset_config('current_shop')
            self.app.show_error("Loja resetada! Reinicie o programa para selecionar novamente.")
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
