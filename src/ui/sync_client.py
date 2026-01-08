
import flet as ft
import threading
import time
from src.sync_core import SyncClient

class SyncManager:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.stop_event = threading.Event()

    def start_auto_sync(self):
        while not self.stop_event.is_set():
            try:
                # Sleep for 1800 seconds (30 min) or wake up if event is set
                if self.stop_event.wait(timeout=1800):
                    break
                
                # Auto-sync check
                shop_name = getattr(self.app, 'shop', None)
                
                if shop_name:
                   print("Auto-sync triggering...")
                   self.run_sync(silent=True)
            except Exception as e:
                print(f"Auto-sync loop error: {e}")
                # Prevent tight loop on error
                if self.stop_event.wait(timeout=60):
                    break

    def stop(self):
        self.stop_event.set()

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
                     
                     # Force a page update to ensure the FAB color change is visible even if silent
                     try:
                         self.page.update()
                     except:
                         pass

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
                try:
                     self.page.update()
                except:
                     pass

        threading.Thread(target=sync_process, daemon=True).start()
