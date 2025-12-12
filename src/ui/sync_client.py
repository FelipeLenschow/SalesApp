
import json
import sqlite3
import src.db_sqlite as db
import src.aws_db as aws_db
from datetime import datetime
import flet as ft
import threading
import time

class SyncClient:
    def __init__(self, db_instance: db.Database, server_url=None):
        # server_url is kept for compatibility but ignored
        self.db = db_instance
        try:
            self.cloud = aws_db.Database()
        except Exception as e:
            print(f"Failed to initialize AWS connection: {e}")
            self.cloud = None

    def get_shops(self):
        if not self.cloud: return []
        try:
            return self.cloud.get_shops()
        except Exception as e:
            print(f"Error fetching shops: {e}")
            return []

    def create_shop(self, new_name, new_password, source_name=None, source_password=None):
        if not self.cloud: 
            return {"status": "error", "message": "No AWS Connection"}
        
        # 1. Validation (if source)
        if source_name:
            source_details = self.cloud.get_shop_details(source_name)
            if not source_details:
                raise Exception("Loja de origem não encontrada.")
            if source_details.get('password') != source_password:
                raise Exception("Senha da loja de origem incorreta.")
        
        # 2. Create
        if not self.cloud.create_shop(new_name, new_password):
            raise Exception("Loja já existe.")
        
        # 3. Copy
        copied = 0
        if source_name:
            copied = self.cloud.copy_shop_data(source_name, new_name)

        return {"status": "success", "message": "Shop created", "copied_items": copied}

    def sync(self, password=None, shop_name=None):
        if not self.cloud:
            return {"message": "Sem conexão AWS (Credenciais ausentes?)"}

        results = {"uploaded": 0, "downloaded": 0, "message": ""}
        
        # 1. Get Sales
        sales_data = []
        try:
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

        # 2. Upload to Cloud
        if not shop_name:
            shop_name = self.db.get_config('current_shop')
        if not password:
            password = self.db.get_config('shop_password')
        
        # Authenticate
        shop_details = self.cloud.get_shop_details(shop_name)
        if not shop_details or shop_details.get('password') != password:
            results["message"] = "Autenticação falhou."
            raise Exception("Senha incorreta ou loja não encontrada.")

        # Upload
        count_up = 0
        for sale in sales_data:
            try:
                self.cloud.record_sale(shop_name, sale)
                count_up += 1
            except Exception as e:
                print(f"Failed to upload sale: {e}")
        
        results["uploaded"] = count_up

        # 3. Download Products
        products_update = self.cloud.get_all_products(shop_name) # Filter by shop
        
        # Update Local DB
        count_down = 0
        try:
            for p in products_update:
                product_info = {
                    'barcode': p['barcode'],
                    'categoria': p['categoria'],
                    'sabor': p['sabor'],
                    'preco': p['preco']
                }
                # Force shop override for local storage consistency if needed
                self.db.add_product(product_info, shop_name)
                count_down += 1
            
            results["downloaded"] = count_down
            results["message"] = "Sync completed successfully"
            
            # Sync Configs?
            # From cloud to local
            if shop_details:
                for key in ['device', 'id_token', 'pos_name', 'user_id']:
                    val = shop_details.get(key)
                    if val: self.db.set_config(key, val)

        except Exception as e:
            results["message"] = f"Error updating local products: {e}"

        return results


class SyncManager:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.stop_sync_thread = False

    def start_auto_sync(self):
        while not self.stop_sync_thread:
            try:
                for _ in range(1800):
                    if self.stop_sync_thread: break
                    time.sleep(1)
                
                if self.stop_sync_thread: break
                
                # Auto-sync check - we don't need server_ip check anymore, just shop
                if self.app.product_db.get_config('current_shop'):
                   print("Auto-sync triggering...")
                   self.run_sync(silent=True)
            except Exception as e:
                print(f"Auto-sync loop error: {e}")
                time.sleep(60)

    def update_fab_status(self, color, tooltip):
        try:
             if hasattr(self.app, 'sync_fab'):
                self.app.sync_fab.bgcolor = color
                self.app.sync_fab.tooltip = tooltip
                self.app.sync_fab.update()
        except:
            pass
    
    def mark_unsynced(self):
        self.update_fab_status(ft.Colors.BLUE, "Sincronizar (Dados pendentes)")

    def run_sync(self, server_url=None, silent=False):
        # server_url ignored
        print(f"Running direct AWS sync")
        
        if not silent:
            self.page.snack_bar = ft.SnackBar(content=ft.Text("Iniciando sincronização (AWS)..."), bgcolor="blue")
            self.page.snack_bar.open = True
            self.page.update()
            
            loading = ft.AlertDialog(
                title=ft.Text("Sincronizando com Nuvem..."),
                content=ft.ProgressRing(),
                modal=True
            )
            self.page.dialog = loading
            loading.open = True
            self.page.update()

        self.update_fab_status(ft.Colors.YELLOW, "Sincronizando...")

        def sync_process():
            try:
                # No URL needed
                client = SyncClient(self.app.product_db)
                result = client.sync()
                print(f"Sync result: {result}")
                
                if not silent:
                    loading.open = False
                    try:
                        self.page.update()
                    except Exception as e:
                        print(f"Error closing loading dialog: {e}")
                
                final_msg = f"Sincronização concluída!\nEnviados: {result.get('uploaded')}\nRecebidos: {result.get('downloaded')}\nMsg: {result.get('message')}"
                if not silent:
                     self.page.snack_bar = ft.SnackBar(ft.Text(final_msg), bgcolor="green")
                     self.page.snack_bar.open = True
                     self.page.update()
                
                if "error" in str(result.get('message')).lower():
                     self.update_fab_status(ft.Colors.RED, f"Erro: {result.get('message')}")
                else:
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
        # Simplified dialog, no IP needed
        
        def start_sync(e):
            if hasattr(self.page, 'close'):
                 self.page.close(dialog)
            else:
                 self.page.close_dialog()
            self.run_sync()

        def reset_shop(e):
            self.app.product_db.reset_config('current_shop')
            self.app.show_error("Loja resetada! Reinicie o programa.")
            if hasattr(self.page, 'close'):
                 self.page.close(dialog)
            else:
                 self.page.close_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text("Sincronização em Nuvem"),
            content=ft.Column([
                ft.Text("Conexão direta com AWS DynamoDB ativa."),
                ft.Divider(),
                ft.TextButton("Trocar/Resetar Loja (Dev)", on_click=reset_shop, style=ft.ButtonStyle(color="red"))
            ], height=100),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.close(dialog) if hasattr(self.page, 'close') else self.page.close_dialog()),
                ft.ElevatedButton("Sincronizar Agora", on_click=start_sync)
            ],
        )

        try:
            self.page.open(dialog)
        except AttributeError:
             self.page.dialog = dialog
             dialog.open = True
        
        self.page.update()
