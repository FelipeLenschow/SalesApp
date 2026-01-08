import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys
import subprocess
import json
import urllib.request
import threading
import time
from datetime import datetime
import certifi
import ssl

# Add parent directory to sys.path - REMOVED
# current_dir = os.path.dirname(os.path.abspath(__file__))
# parent_dir = os.path.dirname(current_dir)
# if parent_dir not in sys.path:
#     sys.path.append(parent_dir)

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

class VersionManager:
    def __init__(self, base_path):
        self.base_path = base_path
        self.versions_path = os.path.join(base_path, VERSIONS_DIR)
        print(f"VersionManager path: {self.versions_path}")
        
        if not os.path.exists(self.versions_path):
            os.makedirs(self.versions_path)
            print(f"Created versions directory at {self.versions_path}")

    def get_local_versions(self):
        """Returns a list of versions sorted by newest first."""
        versions = []
        if not os.path.exists(self.versions_path):
            return []
            
        for f in os.listdir(self.versions_path):
            if f.startswith("SalesApp_") and f.endswith(".exe"):
                tag = f.replace("SalesApp_", "").replace(".exe", "")
                full_path = os.path.join(self.versions_path, f)
                versions.append({"tag": tag, "path": full_path, "filename": f})
        
        versions.sort(key=lambda x: x['tag'], reverse=True)
        return versions

    def get_version_path(self, tag):
        filename = f"SalesApp_{tag}.exe"
        return os.path.join(self.versions_path, filename)



    def get_ssl_context(self):
        try:
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            # Fallback for frozen environments where certifi might not locate the pem correctly
            # or if certifi is missing.
            print("DEBUG: Failed to create default SSL context with certifi. Using unverified context.")
            return ssl._create_unverified_context()

    def fetch_latest_release(self):
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
        
        # DNS Debug
        import socket
        try:
            print(f"DEBUG: Resolving api.github.com...")
            addr = socket.gethostbyname("api.github.com")
            print(f"DEBUG: Resolved to {addr}")
        except Exception as e:
            print(f"DEBUG: DNS Resolution Failed: {e}")

        for attempt in range(3):
            try:
                print(f"DEBUG: Requesting {url} (Attempt {attempt+1})")
                context = self.get_ssl_context()
                with urllib.request.urlopen(url, context=context, timeout=10) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        return data
            except Exception as e:
                print(f"Error fetching release (Attempt {attempt+1}): {e}")
                time.sleep(2)
        return None

    def fetch_release_by_tag(self, tag):
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{tag}"
        for attempt in range(3):
            try:
                print(f"DEBUG: Requesting {url} (Attempt {attempt+1})")
                context = self.get_ssl_context()
                with urllib.request.urlopen(url, context=context, timeout=10) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        return data
            except Exception as e:
                print(f"Error fetching release tag {tag} (Attempt {attempt+1}): {e}")
                time.sleep(2)
        return None

    def download_version(self, asset_url, tag, progress_callback=None):
        target_path = self.get_version_path(tag)
        if os.path.exists(target_path):
            return target_path

        try:
            print(f"DEBUG: Downloading {asset_url} to {target_path}")
            context = self.get_ssl_context()
            
            with urllib.request.urlopen(asset_url, context=context) as response:
                total_size = int(response.getheader('Content-Length', 0).strip())
                block_size = 8192
                downloaded = 0
                
                with open(target_path, 'wb') as f:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        downloaded += len(buffer)
                        f.write(buffer)
                        
                        if progress_callback:
                            percent = (downloaded / total_size) * 100 if total_size > 0 else 0
                            progress_callback(percent)
                            
            return target_path
        except Exception as e:
            print(f"Download failed: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            raise e

    def launch_version(self, version_path, db_path):
        if not os.path.exists(version_path):
            raise FileNotFoundError(f"Executable not found: {version_path}")
            
        print(f"Launching {version_path}")
        subprocess.Popen([version_path, "--db", db_path], cwd=os.path.dirname(version_path))

class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SalesApp Launcher")
        self.root.geometry("500x600")
        self.root.configure(bg="#1a1a2e")

        # Determine base path robustly
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        print(f"Base path: {base_path}")
        self.manager = VersionManager(base_path)
        
        # Init DBs
        self.aws_db = AWSDatabase() if AWSDatabase else None
        self.local_db_path = os.path.join(base_path, VERSIONS_DIR, 'database.db')
        self.local_db = LocalDatabase(self.local_db_path) if LocalDatabase else None

        self.available_shops = []
        self.db_ready = threading.Event()

        self.build_ui()
        self.post_init()

    def build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TLabel", background="#1a1a2e", foreground="white")
        style.configure("TButton", background="#0f3460", foreground="white")
        style.configure("TFrame", background="#1a1a2e")

        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        lbl_title = ttk.Label(main_frame, text="SalesApp Launcher", font=("Helvetica", 24, "bold"))
        lbl_title.pack(pady=(0, 20))

        # Shop Selection
        self.shop_var = tk.StringVar()
        self.shop_combo = ttk.Combobox(main_frame, textvariable=self.shop_var, state="readonly", width=40)
        self.shop_combo.pack(pady=10)
        self.shop_combo.bind("<<ComboboxSelected>>", self.on_shop_change)

        # Launch Button
        self.btn_launch = ttk.Button(main_frame, text="Entrar", command=self.on_launch_click, state=tk.DISABLED)
        self.btn_launch.pack(pady=10, ipadx=20, ipady=5)

        # Status & Progress
        self.lbl_status = ttk.Label(main_frame, text="Inicializando...", font=("Helvetica", 10))
        self.lbl_status.pack(pady=(20, 5))

        self.progress = ttk.Progressbar(main_frame, orient=tk.HORIZONTAL, length=400, mode='determinate')
        self.progress.pack(pady=5)

        # Local Versions
        ttk.Label(main_frame, text="Versões Locais", font=("Helvetica", 12, "bold"), foreground="#e94560").pack(pady=(20, 5))
        
        self.list_versions = tk.Listbox(main_frame, height=8, bg="#16213e", fg="white", borderwidth=0, highlightthickness=0)
        self.list_versions.pack(fill=tk.X, pady=5)

    def post_init(self):
        self.update_version_list()
        threading.Thread(target=self.startup_sequence, daemon=True).start()

    def update_ui(self, fn):
        self.root.after(0, fn)

    def set_status(self, text):
        self.update_ui(lambda: self.lbl_status.config(text=text))

    def set_progress(self, val):
        self.update_ui(lambda: self.progress.config(value=val))

    def toggle_progress(self, visible):
        # Tkinter pack_forget/pack to toggle visibility is tricky with ordering.
        # Just creating/destroying or mapping/unmapping is easier for now,
        # or keeping it always visible but empty.
        # Simple fix: always visible, just reset value.
        pass

    def update_version_list(self):
        versions = self.manager.get_local_versions()
        self.list_versions.delete(0, tk.END)
        if not versions:
            self.list_versions.insert(tk.END, "Nenhuma versão instalada.")
        else:
            for v in versions:
                self.list_versions.insert(tk.END, f"{v['tag']} - {v['filename']}")

    def startup_sequence(self):
        print("DEBUG: Starting startup_sequence...")
        self.load_shops()
        print("DEBUG: startup_sequence: load_shops complete.")
        self.attempt_auto_launch()
        print("DEBUG: startup_sequence: attempt_auto_launch complete.")
        self.populate_database()
        print("DEBUG: startup_sequence: populate_database complete.")

    def load_shops(self):
        print("DEBUG: load_shops called.")
        self.set_status("Carregando lojas...")
        try:
            if self.aws_db:
                print("DEBUG: AWS DB available. Getting shops...")
                self.available_shops = self.aws_db.get_shops_with_versions()
                print(f"DEBUG: Found {len(self.available_shops)} shops from AWS.")
            else:
                print("DEBUG: AWS DB not available.")
                self.available_shops = []
        except Exception as e:
            print(f"DEBUG: Error loading shops: {e}")
            self.available_shops = []

        def update_options():
            shop_names = [s['name'] for s in self.available_shops]
            self.shop_combo['values'] = shop_names
            
            if self.local_db:
                last_shop = self.local_db.get_selected_shop()
                print(f"DEBUG: Last selected shop from Local DB: {last_shop}")
                if last_shop and last_shop in shop_names:
                    self.shop_combo.set(last_shop)
                    self.btn_launch.config(state=tk.NORMAL)
            
            self.lbl_status.config(text="Pronto.")

        self.update_ui(update_options)

    def on_shop_change(self, event):
        print(f"DEBUG: Shop selection changed to {self.shop_var.get()}")
        self.btn_launch.config(state=tk.NORMAL)

    def attempt_auto_launch(self):
        print("DEBUG: attempt_auto_launch called.")
        if not self.local_db: 
            print("DEBUG: No local DB, skipping auto-launch.")
            return

        last_shop = self.local_db.get_selected_shop()
        if not last_shop: 
            print("DEBUG: No last shop selected, skipping auto-launch.")
            return

        # Scenario 1: Online
        shop_info = next((s for s in self.available_shops if s['name'] == last_shop), None)
        if shop_info:
            target_version = shop_info.get('version')
            print(f"DEBUG: Auto-launch target version for {last_shop}: {target_version}")
            if target_version:
                path = self.manager.get_version_path(target_version)
                if os.path.exists(path):
                    self.set_status(f"Iniciando automaticamente ({target_version})...")
                    time.sleep(0.5)
                    self.populate_database() # Ensure DB is populated
                    print("DEBUG: Auto-launching now...")
                    self.do_final_launch(last_shop, target_version, path)
                    return
                else:
                    print(f"DEBUG: Target version {target_version} not found locally.")

        # Scenario 2: Offline
        if not self.available_shops:
            print("DEBUG: Offline mode (no available shops). Checking last version.")
            last_version = self.local_db.get_last_version()
            if last_version:
                path = self.manager.get_version_path(last_version)
                if os.path.exists(path):
                    self.set_status(f"Modo Offline: Iniciando ({last_version})...")
                    time.sleep(0.5)
                    self.populate_database()
                    print("DEBUG: Offline Auto-launching now...")
                    self.do_final_launch(last_shop, last_version, path)
                else:
                     print(f"DEBUG: Last version {last_version} not found locally.")

    def populate_database(self):
        print("DEBUG: populate_database called.")
        self.set_status("Verificando banco de dados...")
        if not self.local_db:
            print("DEBUG: No local DB.")
            self.db_ready.set()
            return

        try:
             with self.local_db.get_connection() as conn:
                 count = conn.execute("SELECT count(*) FROM products").fetchone()[0]
                 print(f"DEBUG: Products in DB: {count}")
                 if count > 0:
                     self.db_ready.set()
                     self.set_status("Banco de dados pronto.")
                     return
        except Exception as e:
            print(f"DEBUG: DB Check error: {e}")

        if not self.aws_db:
            self.set_status("Aviso: AWS DB offline. Cache vazio.")
            self.db_ready.set()
            return

        self.set_status("Baixando produtos (Primeira execução)...")
        
        try:
            def on_progress(count):
                self.set_status(f"Baixando produtos... ({count})")

            print("DEBUG: Fetching all products from AWS...")
            products = self.aws_db.get_all_products_grouped(progress_callback=on_progress)
            print(f"DEBUG: Downloaded {len(products)} products.")
            self.set_status("Salvando no cache local...")
            self.local_db.replace_all_products(products)
            self.local_db.set_last_sync_timestamp(datetime.now().isoformat())
            self.set_status("Banco de dados atualizado.")
        except Exception as e:
            print(f"DEBUG: Error downloading products: {e}")
            self.set_status(f"Erro ao baixar produtos: {e}")
        finally:
            self.db_ready.set()

    def on_launch_click(self):
        selected_shop = self.shop_var.get()
        print(f"DEBUG: Launch clicked. Selected shop: {selected_shop}")
        if not selected_shop: return

        shop_info = next((s for s in self.available_shops if s['name'] == selected_shop), None)
        if not shop_info:
            print("DEBUG: Shop info not found in available_shops.")
            self.set_status("Erro: Loja inválida.")
            return

        target_version = shop_info.get('version')
        if not target_version:
            print("DEBUG: No specific version for shop. Checking latest.")
            self.check_latest_and_launch(selected_shop)
            return

        self.set_status(f"Verificando versão ({target_version})...")
        threading.Thread(target=self.ensure_and_launch_sync, args=(selected_shop, target_version), daemon=True).start()

    def check_latest_and_launch(self, shop_name):
        self.set_status("Verificando última versão...")
        def task():
            print("DEBUG: Fetching latest release...")
            release = self.manager.fetch_latest_release()
            if release:
                tag = release.get("tag_name")
                print(f"DEBUG: Latest release tag: {tag}")
                self.ensure_and_launch_sync(shop_name, tag)
            else:
                print("DEBUG: Failed to fetch latest release.")
                self.set_status("Falha ao verificar versão.")
        threading.Thread(target=task, daemon=True).start()

    def offer_fallback(self, shop_name, target_version):
        print(f"DEBUG: Offering fallback for {target_version}")
        last_version = self.local_db.get_last_version() if self.local_db else None
        if not last_version:
            messagebox.showerror("Erro", f"Versão {target_version} não disponível e nenhuma versão anterior encontrada.")
            return

        path = self.manager.get_version_path(last_version)
        if os.path.exists(path):
            if messagebox.askyesno("Aviso", f"Versão {target_version} falhou. Abrir anterior ({last_version})?"):
                self.do_final_launch(shop_name, last_version, path)
        else:
             messagebox.showerror("Erro", f"Versão {target_version} não disponível.")

    def ensure_and_launch_sync(self, shop_name, version_tag):
        print(f"DEBUG: ensure_and_launch_sync called for {shop_name}, version {version_tag}")
        local_path = self.manager.get_version_path(version_tag)
        print(f"DEBUG: Expecting local path: {local_path}")
        
        if os.path.exists(local_path):
            print("DEBUG: Local version found.")
            self.set_status("Versão encontrada.")
            self.do_final_launch(shop_name, version_tag, local_path)
            return

        print(f"DEBUG: Local version NOT found. Initiating download for {version_tag}...")
        self.set_status(f"Baixando versão {version_tag}...")
        try:
            # Try fetching release with the exact tag
            print(f"DEBUG: Fetching release info for tag: {version_tag}")
            release = self.manager.fetch_release_by_tag(version_tag)
            
            if not release and not version_tag.startswith('v'):
                 print(f"DEBUG: Tag {version_tag} not found, trying v{version_tag}...")
                 release = self.manager.fetch_release_by_tag(f"v{version_tag}")
            
            if not release and version_tag.startswith('v'):
                 print(f"DEBUG: Tag {version_tag} not found, trying {version_tag[1:]}...")
                 release = self.manager.fetch_release_by_tag(version_tag[1:])

            if release:
                print("DEBUG: Release found.")
                assets = release.get("assets", [])
                print(f"DEBUG: Found {len(assets)} assets.")
                
                # Intelligent Asset Selection
                # Force 32-bit preference if that's what we want, or just log choice
                import struct
                is_64bit = (struct.calcsize("P") * 8) == 64
                print(f"DEBUG: System is 64-bit? {is_64bit}")
                
                selected_asset = None
                
                # 1. Look for architecture specific match first
                if is_64bit:
                    # Prefer x64/64bit
                    selected_asset = next((a for a in assets if ("x64" in a["name"] or "64bit" in a["name"]) and a["name"].endswith(".exe")), None)
                else:
                    # Prefer x86/32bit
                    selected_asset = next((a for a in assets if ("x86" in a["name"] or "32bit" in a["name"]) and a["name"].endswith(".exe")), None)
                
                if selected_asset:
                     print(f"DEBUG: Selected architecture-specific asset: {selected_asset['name']}")

                # 2. Fallback to generic .exe from SalesApp
                if not selected_asset:
                    selected_asset = next((a for a in assets if "SalesApp" in a["name"] and a["name"].endswith(".exe") and "x64" not in a["name"] and "x86" not in a["name"]), None)
                    if selected_asset: print(f"DEBUG: Selected generic SalesApp asset: {selected_asset['name']}")
                    
                # 3. Last resort: ANY .exe
                if not selected_asset:
                     selected_asset = next((a for a in assets if a["name"].endswith(".exe")), None)
                     if selected_asset: print(f"DEBUG: Fallback to any .exe asset: {selected_asset['name']}")

                if selected_asset:
                    print(f"DEBUG: Starting download of {selected_asset['name']} from {selected_asset['browser_download_url']}")
                    self.manager.download_version(
                        selected_asset["browser_download_url"], 
                        version_tag, 
                        progress_callback=self.set_progress
                    )
                    print("DEBUG: Download complete.")
                    self.set_status("Download concluído.")
                    self.do_final_launch(shop_name, version_tag, local_path)
                    return
                else:
                    print("DEBUG: No suitable executable asset found in release.")
                    self.set_status(f"Nenhum executável encontrado na versão {version_tag}.")
            else:
                 print("DEBUG: Release metadata could not be fetched.")
            
            self.set_status(f"Falha ao baixar {version_tag}.")
            self.offer_fallback(shop_name, version_tag)
        except Exception as e:
            print(f"DEBUG: Error in ensure_and_launch_sync: {e}")
            self.set_status(f"Erro: {e}")
            import traceback
            traceback.print_exc()
            self.offer_fallback(shop_name, version_tag)

    def do_final_launch(self, shop_name, version_tag, path):
        print(f"DEBUG: do_final_launch: shop={shop_name}, ver={version_tag}, path={path}")
        # Save state
        try:
            if self.local_db:
                print(f"DEBUG: Updating selected shop in DB to {shop_name}")
                self.local_db.set_selected_shop(shop_name)
                self.local_db.set_last_version(version_tag)
        except Exception as e:
            print(f"Error saving state: {e}")

        if not self.db_ready.is_set():
            self.set_status("Aguardando download do banco...")
            self.db_ready.wait()

        self.set_status(f"Iniciando {shop_name}...")
        
        try:
            print("DEBUG: Calling launch_version...")
            # We need to run inside main thread or safely? launch_version uses subprocess, fine in thread.
            # But UI updates needed.
            # Wrapper to launch and close
            def launch_wrapper():
                print("DEBUG: launch_wrapper executed.")
                self.manager.launch_version(path, self.local_db_path)
                print("DEBUG: Process launched.")
                
            self.update_ui(launch_wrapper)
            # Give it a moment before destroying? Launcher usually stays open until process starts?
            # launch_version is non-blocking (Popen).
            # Destroy root.
            self.update_ui(self.root.destroy)
        except Exception as e:
            print(f"DEBUG: Final Launch Exception: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = LauncherApp(root)
    root.mainloop()
