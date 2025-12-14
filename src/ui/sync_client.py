
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

    def sync(self, shop_name=None):
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

        # 2. Upload Sales (Always)
        if not shop_name:
            shop_name = self.db.get_config('current_shop')
        
        count_up = 0
        for sale in sales_data:
            try:
                self.cloud.record_sale(shop_name, sale)
                count_up += 1
            except Exception as e:
                print(f"Failed to upload sale: {e}")
        
        results["uploaded"] = count_up

        # 3. Product Sync (Bidirectional Smart Sync)
        try:
            # Fetch all from both sources
            aws_products = self.cloud.get_all_products(shop_name)
            local_products = self.db.get_all_products_local()
            
            # Index by barcode for O(1) access
            aws_map = {p['barcode']: p for p in aws_products}
            local_map = {p['barcode']: p for p in local_products}
            
            # A) Upload Check: Local -> Cloud
            # We assume Local is the 'editor' source of truth for conflicts in this version.
            products_to_upload = []
            
            for p_local in local_products:
                barcode = p_local['barcode']
                p_aws = aws_map.get(barcode)
                
                if not p_aws:
                    # New in Local
                    products_to_upload.append(p_local)
                else:
                    # Exists in both, check for changes
                    # Normalize types for comparison (AWS uses Decimal, Local uses float/str)
                    is_different = False
                    
                    # Compare specific fields
                    if p_local['categoria'] != p_aws['categoria']: is_different = True
                    if p_local['sabor'] != p_aws['sabor']: is_different = True
                    
                    # Price comparison (handle potential type mismatch)
                    try:
                        price_local = float(p_local['preco'])
                        price_aws = float(p_aws['preco'])
                        if abs(price_local - price_aws) > 0.001: # float epsilon
                            is_different = True
                    except:
                        is_different = True # Assume diff on error
                        
                    if is_different:
                        products_to_upload.append(p_local)

            # B) Execute Uploads
            count_prod_up = 0
            for p in products_to_upload:
                self.cloud.add_product(p, shop_name)
                count_prod_up += 1
            results["products_uploaded"] = count_prod_up

            # C) Download Check: Cloud -> Local
            # We add products that are in Cloud but NOT in Local.
            # (If they were in Local but different, we already prioritized Local -> Cloud above)
            products_to_download = []
            
            for p_aws in aws_products:
                if p_aws['barcode'] not in local_map:
                    products_to_download.append(p_aws)
            
            # Execute Downloads
            count_down = 0
            for p in products_to_download:
                product_info = {
                    'barcode': p['barcode'],
                    'categoria': p['categoria'],
                    'sabor': p['sabor'],
                    'preco': p['preco']
                }
                self.db.add_product(product_info, shop_name)
                count_down += 1
            
            results["downloaded"] = count_down
            
            msg_parts = ["Sync completed"]
            if count_prod_up > 0: msg_parts.append(f"Uploaded {count_prod_up} products")
            if count_down > 0: msg_parts.append(f"Downloaded {count_down} products")
            results["message"] = ". ".join(msg_parts)
            
        except Exception as e:
            results["message"] = f"Error syncing products: {e}"
            print(f"Sync error: {e}")

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

    def run_sync(self, silent=False):
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

