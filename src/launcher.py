import flet as ft
import os
import sys
import subprocess
import json
import urllib.request
import threading
import time
from datetime import datetime

# Add parent directory to sys.path to allow importing src.aws_db if running from src/
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Import Databases
try:
    from src.aws_db import Database as AWSDatabase
except ImportError:
    try:
        from aws_db import Database as AWSDatabase
    except ImportError:
        print("Error: Could not import aws_db")
        AWSDatabase = None

try:
    from src.db_sqlite import Database as LocalDatabase
except ImportError:
    try:
        from db_sqlite import Database as LocalDatabase
    except ImportError:
        print("Error: Could not import db_sqlite")
        LocalDatabase = None

# Configuration
REPO_OWNER = "FelipeLenschow"
REPO_NAME = "SalesApp"
VERSIONS_DIR = "versions"
# We no longer use launcher_config.json, but database.db via LocalDatabase

class VersionManager:
    def __init__(self, base_path):
        self.base_path = base_path
        self.versions_path = os.path.join(base_path, VERSIONS_DIR)
        
        if not os.path.exists(self.versions_path):
            os.makedirs(self.versions_path)

    def get_local_versions(self):
        """Returns a list of versions sorted by newest first."""
        versions = []
        if not os.path.exists(self.versions_path):
            return []
            
        for f in os.listdir(self.versions_path):
            if f.startswith("SalesApp_") and f.endswith(".exe"):
                # Extract version tag: SalesApp_v1.0.0.exe -> v1.0.0
                tag = f.replace("SalesApp_", "").replace(".exe", "")
                full_path = os.path.join(self.versions_path, f)
                versions.append({"tag": tag, "path": full_path, "filename": f})
        
        # Sort versions
        versions.sort(key=lambda x: x['tag'], reverse=True)
        return versions

    def get_version_path(self, tag):
        filename = f"SalesApp_{tag}.exe"
        return os.path.join(self.versions_path, filename)

    def fetch_latest_release(self):
        """Fetches latest release info from GitHub."""
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
        try:
            with urllib.request.urlopen(url) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    return data
        except Exception as e:
            print(f"Error fetching release: {e}")
            return None
        return None

    def fetch_release_by_tag(self, tag):
        """Fetches specific release info from GitHub."""
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{tag}"
        try:
            with urllib.request.urlopen(url) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    return data
        except Exception as e:
            print(f"Error fetching release tag {tag}: {e}")
            return None
        return None

    def download_version(self, asset_url, tag, progress_callback=None):
        """Downloads a specific version asset."""
        target_path = self.get_version_path(tag)
        
        if os.path.exists(target_path):
            return target_path  # Already exists

        try:
            # Download with progress
            def report(block_num, block_size, total_size):
                if progress_callback:
                    downloaded = block_num * block_size
                    percent = min(1.0, downloaded / total_size) if total_size > 0 else 0
                    progress_callback(percent)

            urllib.request.urlretrieve(asset_url, target_path, reporthook=report)
            return target_path
        except Exception as e:
            print(f"Download failed: {e}")
            if os.path.exists(target_path):
                os.remove(target_path) # Cleanup partial
            raise e

    def launch_version(self, version_path, db_path):
        """Launches the selected executable."""
        if not os.path.exists(version_path):
            raise FileNotFoundError(f"Executable not found: {version_path}")
            
        print(f"Launching {version_path}")
        subprocess.Popen([version_path, "--db", db_path], cwd=os.path.dirname(version_path))
        # sys.exit(0) # We'll exit in the caller after saving state

class LauncherApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.manager = VersionManager(os.getcwd())
        
        # Init DBs
        self.aws_db = AWSDatabase() if AWSDatabase else None
        
        # Local DB Path
        self.local_db_path = os.path.join(os.getcwd(), VERSIONS_DIR, 'database.db')
        
        if LocalDatabase:
            self.local_db = LocalDatabase(self.local_db_path)
        else:
            self.local_db = None

        self.page.title = "SalesApp Launcher"
        self.page.window.width = 500
        self.page.window.height = 700
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#1a1a2e"
        self.page.window.center()
        
        # UI Elements
        self.status_text = ft.Text("Inicializando...", color="white70")
        self.progress_bar = ft.ProgressBar(width=400, color="amber", bgcolor="#2a2a40", value=0, visible=False)
        self.shop_dropdown = ft.Dropdown(
            label="Selecione a Loja",
            width=400,
            on_change=self.on_shop_change,
            options=[]
        )
        self.launch_btn = ft.ElevatedButton("Entrar", on_click=self.on_launch_click, width=200, disabled=True)
        self.version_list = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        self.dlg_modal = ft.AlertDialog(modal=True, title=ft.Text("Aviso"))
        
        # State
        self.available_shops = [] 
        self.db_ready = threading.Event()
        
        self.build_ui()
        self.post_init()

    def build_ui(self):
        self.page.add(
            ft.Container(
                content=ft.Column([
                    ft.Text("SalesApp Launcher", size=30, weight="bold", color="white"),
                    ft.Divider(color="white24"),
                    self.shop_dropdown,
                    ft.Divider(color="transparent", height=10),
                    self.launch_btn,
                    ft.Divider(color="white24", height=30),
                    self.status_text,
                    self.progress_bar,
                    ft.Divider(color="transparent", height=20),
                    ft.Text("Versões Locais", size=16, weight="bold", color="blue"),
                    self.version_list
                ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
                expand=True
            )
        )

    def post_init(self):
        # Update local version list
        self.update_version_list()
        
        # Start startup sequence (Shops -> DB)
        threading.Thread(target=self.startup_sequence, daemon=True).start()

    def startup_sequence(self):
        self.load_shops()
        
        # Try to auto launch
        self.attempt_auto_launch()
        
        self.populate_database()

    def attempt_auto_launch(self):
        # Only auto launch if we have a saved shop
        if not self.local_db:
             return

        last_shop = self.local_db.get_selected_shop()
        if not last_shop:
            return

        # Scenario 1: Online & Shop Found
        shop_info = next((s for s in self.available_shops if s['name'] == last_shop), None)
        
        if shop_info:
            target_version = shop_info.get('version')
            if target_version:
                 path = self.manager.get_version_path(target_version)
                 if os.path.exists(path):
                     self.status_text.value = f"Iniciando automaticamente ({target_version})..."
                     self.page.update()
                     time.sleep(0.5) # Brief pause for user feedback
                     
                     # Wait for DB sync if it's already running? 
                     # Actually populate_database starts AFTER this returns in startup_sequence.
                     # But we want to ensure DB is ready.
                     # If we auto-launch, we should trigger DB check/download synchronously?
                     # OR wait for the thread? 
                     # Let's reuse do_final_launch which waits for db_ready.
                     # But db_ready isn't set yet because populate_database hasn't run.
                     
                     # Fix: We need to make sure populate_database runs/finishes before launching.
                     # Since we are in startup_sequence (thread), we can just run populate_database() now
                     # and then launch.
                     self.populate_database()
                     self.do_final_launch(last_shop, target_version, path)
                     return

        # Scenario 2: Offline (Empty shop list or AWS failed)
        if not self.available_shops:
             # Check if we have any local version
             last_version = self.local_db.get_last_version()
             if last_version:
                 path = self.manager.get_version_path(last_version)
                 if os.path.exists(path):
                     self.status_text.value = f"Modo Offline: Iniciando ({last_version})..."
                     self.page.update()
                     time.sleep(0.5)
                     
                     # Ensure DB ready (offline mode)
                     self.populate_database()
                     self.do_final_launch(last_shop, last_version, path)
                     return

    def load_shops(self):
        self.status_text.value = "Carregando lojas..."
        self.page.update()
        
        try:
            if self.aws_db:
                self.available_shops = self.aws_db.get_shops_with_versions()
            else:
                self.available_shops = []
        except Exception as e:
            print(f"Error loading shops: {e}")
            self.available_shops = []

        # Populate Dropdown
        options = []
        for shop in self.available_shops:
            options.append(ft.dropdown.Option(shop['name']))
        
        self.shop_dropdown.options = options
        
        # Restore Selection
        if self.local_db:
            last_shop = self.local_db.get_selected_shop()
            if last_shop and any(s['name'] == last_shop for s in self.available_shops):
                self.shop_dropdown.value = last_shop
                self.launch_btn.disabled = False
        
        self.status_text.value = "Pronto."
        self.page.update()

    def on_shop_change(self, e):
        self.launch_btn.disabled = False
        self.page.update()

    def update_version_list(self):
        self.version_list.controls.clear()
        versions = self.manager.get_local_versions()
        
        if not versions:
            self.version_list.controls.append(ft.Text("Nenhuma versão instalada.", color="red"))
        else:
            for i, v in enumerate(versions):
                # Card for version
                card = ft.Card(
                    content=ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.EXTENSION, color="blue"),
                            ft.Column([
                                ft.Text(v['tag'], size=16, weight="bold"),
                                ft.Text(v['filename'], size=12, color="white54")
                            ], expand=True),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=10
                    ),
                    color="#16213e"
                )
                self.version_list.controls.append(card)
        self.page.update()

    def on_launch_click(self, e):
        selected_shop_name = self.shop_dropdown.value
        shop_info = next((s for s in self.available_shops if s['name'] == selected_shop_name), None)
        
        if not shop_info:
            self.status_text.value = "Erro: Loja inválida."
            self.page.update()
            return
            
        target_version = shop_info.get('version')
        
        if not target_version:
             self.check_latest_and_launch(selected_shop_name)
             return

        self.status_text.value = f"Verificando versão necessária ({target_version})..."
        self.page.update()
        
        self.ensure_and_launch(selected_shop_name, target_version)

    def check_latest_and_launch(self, shop_name):
        self.status_text.value = "Verificando última versão..."
        self.page.update()
        threading.Thread(target=self._async_check_latest, args=(shop_name,), daemon=True).start()

    def _async_check_latest(self, shop_name):
         release = self.manager.fetch_latest_release()
         if release:
             tag = release.get("tag_name")
             self.ensure_and_launch_sync(shop_name, tag)
         else:
             self.status_text.value = "Falha ao verificar versão."
             self.page.update()

    def ensure_and_launch(self, shop_name, version_tag):
        threading.Thread(target=self._async_ensure_launch, args=(shop_name, version_tag), daemon=True).start()

    def _async_ensure_launch(self, shop_name, version_tag):
        self.ensure_and_launch_sync(shop_name, version_tag)

    def ensure_and_launch_sync(self, shop_name, version_tag):
        # Check Local
        local_path = self.manager.get_version_path(version_tag)
        if os.path.exists(local_path):
            self.status_text.value = "Versão encontrada."
            self.page.update()
            self.do_final_launch(shop_name, version_tag, local_path)
            return

        # Download
        self.status_text.value = f"Baixando versão {version_tag}..."
        self.progress_bar.visible = True
        self.page.update()
        
        try:
            release = self.manager.fetch_release_by_tag(version_tag)
            
            if release:
                assets = release.get("assets", [])
                exe_asset = next((a for a in assets if a["name"].endswith(".exe") or "SalesApp" in a["name"]), None)
                
                if exe_asset:
                    def on_progress(p):
                        self.progress_bar.value = p
                        self.page.update()
                        
                    self.manager.download_version(exe_asset["browser_download_url"], version_tag, on_progress)
                    
                    self.status_text.value = "Download concluído."
                    self.progress_bar.visible = False
                    self.page.update()
                    self.do_final_launch(shop_name, version_tag, local_path)
                    return
            
            self.status_text.value = f"Falha ao baixar {version_tag}."
            self.progress_bar.visible = False
            self.page.update()
            self.offer_fallback(shop_name, version_tag)

        except Exception as e:
            print(e)
            self.status_text.value = f"Erro: {e}"
            self.progress_bar.visible = False
            self.page.update()
            self.offer_fallback(shop_name, version_tag)

    def offer_fallback(self, shop_name, target_version):
        last_version = self.local_db.get_last_version() if self.local_db else None
        
        def launch_last(e):
             path = self.manager.get_version_path(last_version)
             self.page.close(self.dlg_modal)
             self.do_final_launch(shop_name, last_version, path)
             
        actions = []
        if last_version:
             p = self.manager.get_version_path(last_version)
             if os.path.exists(p):
                 actions.append(ft.TextButton(f"Abrir anterior ({last_version})", on_click=launch_last))
        
        actions.append(ft.TextButton("Cancelar", on_click=lambda e: self.page.close(self.dlg_modal)))

        self.show_alert("Erro de Versão", 
                        f"A versão exigida ({target_version}) não está disponível.\n",
                        actions)

    def populate_database(self):
         self.status_text.value = "Verificando banco de dados..."
         self.page.update()
         
         if not self.local_db:
             self.db_ready.set()
             return

         # Check count
         try:
             with self.local_db.get_connection() as conn:
                 count = conn.execute("SELECT count(*) FROM products").fetchone()[0]
                 if count > 0:
                     self.db_ready.set()
                     self.status_text.value = "Pronto."
                     self.page.update()
                     return # DB ready
         except Exception as e:
             print(f"DB Check error: {e}")
         
         if not self.aws_db:
             self.status_text.value = "Aviso: AWS DB offline. Cache vazio."
             self.page.update()
             self.db_ready.set()
             return

         self.status_text.value = "Baixando banco de dados (Primeira execução)..."
         self.progress_bar.visible = True
         self.progress_bar.value = None # Indeterminate
         self.page.update()

         try:
             def on_progress(count):
                 self.status_text.value = f"Baixando produtos... ({count})"
                 self.page.update()

             products = self.aws_db.get_all_products_grouped(progress_callback=on_progress)
             
             self.status_text.value = "Salvando no cache local..."
             self.page.update()
             
             self.local_db.replace_all_products(products)
             self.local_db.set_last_sync_timestamp(datetime.now().isoformat())
             
             self.status_text.value = "Banco de dados atualizado."
         except Exception as e:
             print(f"DB Download Error: {e}")
             self.status_text.value = f"Erro ao baixar produtos: {e}"
         finally:
             self.progress_bar.visible = False
             self.db_ready.set()
             self.page.update()

    def do_final_launch(self, shop_name, version_tag, path):
        # Save state
        try:
            if self.local_db:
                self.local_db.set_selected_shop(shop_name)
                self.local_db.set_last_version(version_tag)
        except Exception as e:
            print(f"Error saving state: {e}")
        
        # Wait for DB
        if not self.db_ready.is_set():
             self.status_text.value = "Aguardando download do banco..."
             self.page.update()
             self.db_ready.wait()

        self.status_text.value = f"Iniciando {shop_name}..."
        self.page.update()
        
        self.manager.launch_version(path, self.local_db_path)
        
        self.page.window.close()

    def show_alert(self, title, message, actions=[]):
        self.dlg_modal.title = ft.Text(title)
        self.dlg_modal.content = ft.Text(message)
        self.dlg_modal.actions = actions
        self.page.open(self.dlg_modal)
        self.page.update()

def main(page: ft.Page):
    LauncherApp(page)

if __name__ == "__main__":
    ft.app(target=main)
