import io
import sys
import os

import ssl
import urllib.request

# This bypasses the certificate verification
ssl._create_default_https_context = ssl._create_unverified_context

# Patch stdout/stderr for uvicorn/flet in frozen noconsole mode
# This prevents crashes when uvicorn tries to write to None
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import flet as ft
import threading
import time

# Force PyInstaller to include these modules to avoid ImportErrors in frozen app
try:
    import flet.controls
    import flet.page
    import flet.types
    import flet_web
except ImportError:
    pass

# Global session management
session_count = 0
session_lock = threading.Lock()
exit_timer = None

def main(page: ft.Page):
    global session_count, exit_timer
    
    with session_lock:
        session_count += 1
        # Cancel any pending exit
        if exit_timer:
            try:
                exit_timer.cancel()
            except: pass
            exit_timer = None
        print(f"New session started. Total sessions: {session_count}")

    # Container for app instance to access in inner functions
    app_instance = None

    # Ensure the app exits when the browser tab is closed
    def on_disconnect(e):
        global session_count, exit_timer
        print("Client disconnected...")
        
        # Verify app instance cleanup
        if app_instance:
             try:
                 app_instance.cleanup()
             except Exception as cleanup_err:
                 print(f"Cleanup error: {cleanup_err}")
        
        with session_lock:
            session_count -= 1
            print(f"Session ended. Remaining sessions: {session_count}")
            
            if session_count <= 0:
                # If running as a native desktop app, exit immediately
                if not page.web:
                    print("Desktop app closed. Exiting immediately.")
                    os._exit(0)

                print("No active sessions. Scheduling exit in 3 seconds...")
                
                def dedicated_exit():
                    time.sleep(3)
                    with session_lock:
                        if session_count <= 0:
                            print("Exiting application.")
                            os._exit(0)
                        else:
                            print("Exit cancelled (new session).")

                # Use a thread for delayed exit so we don't block Flet
                threading.Thread(target=dedicated_exit, daemon=True).start()
    
    page.on_disconnect = on_disconnect
    
    try:
        from src.ui.gui import ProductApp
        app_instance = ProductApp(page)
    except Exception as e:
        print(f"Error in main: {e}")

if __name__ == "__main__":
    import multiprocessing

    # Guard against Flet trying to run pip in a frozen app which causes infinite loops
    if len(sys.argv) > 1 and 'pip' in sys.argv:
        sys.exit(1)
    
    try:
        multiprocessing.freeze_support()
    except Exception as e:
        print(f"freeze_support failed: {e}")

    # Detect Architecture
    is_32bit = sys.maxsize < 2**32
    
    if is_32bit:
    # if True: # dont touch this
        print("32-bit environment detected. Launching Legacy Tkinter UI (Refactored).")
        try:
            import tkinter as tk
            from src.ui_legacy.gui import POSApplication
            
            root = tk.Tk()
            app = POSApplication(root)
            root.mainloop()
            
        except Exception as e:
            # Fallback to simple error msg if Tk fails
            import tkinter.messagebox
            tkinter.messagebox.showerror("Critical Error", f"Failed to launch 32-bit UI: {e}")
    else:
        print("64-bit environment detected. Launching Flet UI.")
        try:
             ft.app(target=main)
        except Exception as e:
             print(f"ft.app failed: {e}")