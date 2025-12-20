
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

    def sync(self, shop_name=None, enable_deletion_check=False):
        """
        Main sync logic (Bidirectional).
        1. Upload pending sales (Always)
        2. Upload modified products (Priority)
        3. Download delta products (Changed in Cloud)
        4. Optional: Download IDs to detect cloud deletions (Heavy)
        """
        if not self.cloud:
            return {"message": "Sem conexão AWS (Credenciais ausentes?)", "success": False}

        results = {
            "success": True, 
            "message": "Sync completed", 
            "uploaded_sales": 0,
            "uploaded": 0,
            "downloaded": 0,
            "deleted_local": 0,
            "products_uploaded": 0
        }
        
        # 1. Fetch Local Sales pending sync
        sales_data = []
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT timestamp, final_price, payment_method, products_json, sync_status FROM sales WHERE sync_status IS NOT 'synced'")
                rows = cursor.fetchall()
                
                for row in rows:
                    if not row[3]: continue
                    sales_data.append({
                        'timestamp': row[0],
                        'final_price': row[1],
                        'payment_method': row[2],
                        'products_json': row[3],
                        'sync_status': row[4]
                        })
        except Exception as e:
            results["message"] = f"Error reading local sales: {e}"
            results["success"] = False
            return results

        # 2. Upload Sales (Always)
        if not shop_name:
            shop_name = self.db.get_config('current_shop')
        
        count_up_sales = 0
        for sale in sales_data:
            try:
                self.cloud.record_sale(shop_name, sale)
                self.db.mark_sale_synced(sale['timestamp'])
                count_up_sales += 1
            except Exception as e:
                print(f"Failed to upload sale: {e}")
        
        results["uploaded_sales"] = count_up_sales

        # 3. Product Sync (Bidirectional Smart Sync)
        try:
            # Check Last Sync Timestamp
            last_sync_ts = self.db.get_last_sync_timestamp()
            current_ts = datetime.now().isoformat()
            
            aws_products = []
            cloud_ids_map = {} # For deletion checking
            
            if not last_sync_ts:
                # FULL SYNC
                print("Performing FULL SYNC (Baseline)...")
                aws_products = self.cloud.get_products_delta(shop_name=shop_name, last_sync_ts=None)
                
                # FIX: For Full Sync, we must not rely solely on 'aws_products' (which is filtered by shop)
                # for the deletion map, otherwise we delete cached products from other shops.
                # We need the GLOBAL list of valid IDs to know what to keep.
                print("Fetching Global ID list for deletion check...")
                all_ids = self.cloud.get_all_product_ids()
                cloud_ids_map = {item['barcode']: item['product_id'] for item in all_ids}
            else:
                # DELTA SYNC
                print(f"Performing DELTA SYNC (Since {last_sync_ts})...")
                # 1. Fetch Deltas
                aws_products = self.cloud.get_products_delta(shop_name=shop_name, last_sync_ts=last_sync_ts)
                
                # 2. Fetch ALL IDs for deletion detection (Lightweight) - Only if enabled
                if enable_deletion_check:
                    print("Fetching Cloud IDs for deletion check...")
                    all_ids = self.cloud.get_all_product_ids()
                    cloud_ids_map = {item['barcode']: item['product_id'] for item in all_ids}
                else:
                    cloud_ids_map = {} # Empty means we won't delete anything

            # Local Data
            local_products = self.db.get_all_products_local()
            local_map = {p['barcode']: p for p in local_products}
            
            # A) PRIORITY: Upload Local Modifications
            # Products marked as 'modified' or new (not in AWS but passed modified check)
            products_to_upload = []
            
            for p_local in local_products:
                status = p_local.get('sync_status', 'synced')
                if status == 'modified':
                    products_to_upload.append(p_local)
            
            # Execute Uploads
            count_prod_up = 0
            for p in products_to_upload:
                try:
                    self.cloud.add_product(p, shop_name)
                    # Mark as synced on success
                    self.db.mark_product_synced(p['barcode'])
                    count_prod_up += 1
                except Exception as e:
                    print(f"Failed to upload product {p['barcode']}: {e}")

            results["products_uploaded"] = count_prod_up
            
            # B) Download Updates (From Delta or Full List)
            # If Delta, this list only contains changed items.
            # If Full, it contains everything.
            
            count_down = 0
            
            for p_aws in aws_products:
                barcode = p_aws['barcode']
                
                # If we just uploaded it, ignore download (we are the source)
                # (Unless we want to get the updated timestamp, but local 'synced' is enough)
                
                p_local = local_map.get(barcode)
                should_download = False
                
                if not p_local:
                    should_download = True # New
                else:
                    # Exists. 
                    status = p_local.get('sync_status', 'synced')
                    if status == 'synced':
                         # If synced, trust cloud (delta implies change)
                         should_download = True
                    # If modified, we just tried to upload. If successful, local is synced.
                    # Conflict resolution: if simultaneous edit, cloud (Delta) usually wins in this simple logic,
                    # OR we define "Server Wins". 
                    # Here: if we have local changes remaining (upload failed), we keep local.
                
                if should_download:
                   product_info = {
                        'product_id': p_aws['product_id'],
                        'barcode': p_aws['barcode'],
                        'categoria': p_aws['categoria'],
                        'sabor': p_aws['sabor'],
                        'marca': p_aws['marca'], # Ensure branding is consistant
                        'brand': p_aws['marca'],
                        'preco': p_aws['preco']
                   }
                   self.db.add_product(product_info, shop_name, sync_status='synced')
                   count_down += 1
            
            results["downloaded"] = count_down

            # C) Process Deletions
            # Only if map is populated (implies enabled check or Full Sync)
            # Note: For Full Sync, cloud_ids_map is auto-populated from get_products_delta result?
            # get_products_delta returns everything in Full Sync mode? 
            # If get_products_delta(None) returns ALL items, then cloud_ids_map populated from it is complete.
            # So Full Sync naturally handles deletion without extra call.
            # Delta Sync needs enable_deletion_check to populate it manually.
            
            products_to_delete = []
            if cloud_ids_map: 
                for barcode, p_local in local_map.items():
                    if barcode not in cloud_ids_map:
                        status = p_local.get('sync_status', 'synced')
                        if status == 'synced':
                            products_to_delete.append(p_local)
            
            # Execute Deletions
            count_del = 0
            for p in products_to_delete:
                self.db.delete_product(p['barcode'])
                count_del += 1
                
            results["deleted_local"] = count_del
            
            # SUCCESS: Update Timestamp
            self.db.set_last_sync_timestamp(current_ts)
            
            msg_parts = ["Sync completed"]
            if count_prod_up > 0: msg_parts.append(f"↑ {count_prod_up}")
            if count_down > 0: msg_parts.append(f"↓ {count_down}")
            if count_del > 0: msg_parts.append(f"🗑 {count_del}")
            
            if len(msg_parts) == 1: msg_parts.append("OK")
            
            results["message"] = " | ".join(msg_parts)
            results["success"] = True
            
        except Exception as e:
            results["message"] = f"Error syncing products: {e}"
            results["success"] = False
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
                shop_name = getattr(self.app, 'shop', None)
                result = client.sync(shop_name=shop_name)
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
                
                if not result.get('success', True):
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

