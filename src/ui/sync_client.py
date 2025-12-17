
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
            return {"message": "Sem conexão AWS (Credenciais ausentes?)", "success": False}

        results = {"uploaded": 0, "downloaded": 0, "deleted_local": 0, "message": "", "success": False}
        
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
            results["success"] = False
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
        
        results["uploaded_sales"] = count_up

        # 3. Product Sync (Bidirectional Smart Sync)
        try:
            # Fetch all from both sources
            aws_products = self.cloud.get_all_products(shop_name)
            local_products = self.db.get_all_products_local()
            
            # Index by barcode for O(1) access
            aws_map = {p['barcode']: p for p in aws_products}
            local_map = {p['barcode']: p for p in local_products}
            
            # A) PRIORITY: Upload Local Modifications
            # Products marked as 'modified' or new (not in AWS but passed modified check)
            products_to_upload = []
            
            for p_local in local_products:
                barcode = p_local['barcode']
                status = p_local.get('sync_status', 'synced')
                
                # If modified explicitly OR (not in AWS and not explicitly synced - new)
                # Actually, if not in AWS and 'synced', it implies deletion from cloud.
                # So we ONLY upload if 'modified'.
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
            
            # RE-EVALUATE Local State?
            # Ideally we rely on memory maps but since we just synced some, we assume they are now equal to what we sent.
            # But let's check for Downloads/Deletions now.
            
            # B) Download Updates & Deletions (Cloud Authority)
            products_to_download = []
            products_to_delete = [] # Local deletions (because they are missing in Cloud)
            
            for p_aws in aws_products:
                barcode = p_aws['barcode']
                
                if barcode not in local_map:
                    # New in Cloud -> Download
                    products_to_download.append(p_aws)
                else:
                    # Exists in Local. Check status.
                    p_local = local_map[barcode]
                    status = p_local.get('sync_status', 'synced')
                    
                    if status == 'synced':
                        # If local is synced (not modified pending upload), Cloud is authority.
                        # Compare content.
                        is_different = False
                        if p_local['categoria'] != p_aws['categoria']: is_different = True
                        if p_local['sabor'] != p_aws['sabor']: is_different = True
                        try:
                            if abs(float(p_local['preco']) - float(p_aws['preco'])) > 0.001: is_different = True
                        except: is_different = True
                        
                        if is_different:
                            products_to_download.append(p_aws)
                    
                    # If status == 'modified', we skip downloading. We just tried to upload it.
                    # If upload failed, we keep local version (conflict -> local wins/retry next time).
            
            # Check for Local Deletions (In Local (Synced) but NOT in AWS)
            for barcode, p_local in local_map.items():
                if barcode not in aws_map:
                    status = p_local.get('sync_status', 'synced')
                    if status == 'synced':
                        # Valid candidate for deletion (it was synced before, now gone from cloud)
                        products_to_delete.append(p_local)
                    # If 'modified', it's a new local creation not yet uploaded (or upload failed above). Keep it.

            # Execute Deletions
            count_del = 0
            for p in products_to_delete:
                self.db.delete_product(p['barcode'])
                count_del += 1
            
            # Execute Downloads
            count_down = 0
            for p in products_to_download:
                product_info = {
                    'barcode': p['barcode'],
                    'categoria': p['categoria'],
                    'sabor': p['sabor'],
                    'preco': p['preco']
                }
                # Add with 'synced' status because it comes from cloud
                self.db.add_product(product_info, shop_name, sync_status='synced')
                count_down += 1
            
            results["downloaded"] = count_down
            results["deleted_local"] = count_del
            
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

