import os
import subprocess
import sys
import threading
import time

class Updater:
    @staticmethod
    def update():
        """
        Trigger PyApp self-update in the background.
        """
        if not os.environ.get("PYAPP"):
            print("Not running as PyApp, skipping update check.")
            return

        def _update_task():
            try:
                print("Checking for updates...")
                # triggering "self update"
                # The executable (sys.argv[0]) handles the update command
                # We use shell=False and capture output to avoid popping up windows if console is hidden
                process = subprocess.Popen(
                    [sys.argv[0], "self", "update"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                stdout, stderr = process.communicate()
                
                if process.returncode == 0:
                    print(f"Update successful: {stdout}")
                    if "Updated" in stdout or "updated" in stdout:
                        # If update occurred, we might want to notify or restart
                        # PyApp usually updates in place. A restart is often required to load new code.
                        print("Restarting application to apply updates...")
                        # Allow some time for IO
                        time.sleep(2)
                        # Restart
                        os.execv(sys.argv[0], sys.argv)
                else:
                    print(f"Update check finished. No update or error: {stderr}")

            except Exception as e:
                print(f"Update failed: {e}")

        # Run in background to not block UI startup
        thread = threading.Thread(target=_update_task, daemon=True)
        thread.start()
