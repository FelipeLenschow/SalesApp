# C:\Users\Felipe\AppData\Local\Programs\Python\Python312-32\python.exe "c:\Users\Felipe\Desktop\Sales\Build\build.py"
import os
import subprocess
import shutil
import configparser
import sys

def main():
    # Build dir is where this script resides e.g. Root/Build
    build_dir = os.path.dirname(os.path.abspath(__file__))
    # Project Root is one level up
    project_root = os.path.dirname(build_dir)
    
    print(f"Project root: {project_root}")

    # Determine architecture
    import struct
    bits = struct.calcsize("P") * 8
    arch_suffix = "_x64" if bits == 64 else "_x86"
    print(f"Detected {bits}-bit Python environment. Build will be suffixed with '{arch_suffix}'.")

    # 1. Read AWS Credentials
    aws_creds_path = os.path.join(project_root, '.aws', 'credentials')
    
    if not os.path.exists(aws_creds_path):
        print(f"Error: AWS credentials file not found at {aws_creds_path}")
        return

    config = configparser.ConfigParser()
    config.read(aws_creds_path)
    
    if 'default' not in config:
        print("Error: 'default' profile not found in credentials file.")
        return

    aws_access_key = config['default'].get('aws_access_key_id')
    aws_secret_key = config['default'].get('aws_secret_access_key')
    
    if not aws_access_key or not aws_secret_key:
        print("Error: Incomplete credentials in default profile.")
        return

    # 2. Generate embedded credentials module
    src_dir = os.path.join(project_root, 'src')
    embedded_file = os.path.join(src_dir, 'embedded_credentials.py')
    
    print("Generating temporary embedded credentials...")
    with open(embedded_file, 'w') as f:
        f.write(f'AWS_ACCESS_KEY_ID = "{aws_access_key}"\n')
        f.write(f'AWS_SECRET_ACCESS_KEY = "{aws_secret_key}"\n')
        f.write('AWS_DEFAULT_REGION = "us-east-1"\n')

    try:
        # 3. Build Executables using PyInstaller
        print("Starting PyInstaller build...")
        
        # Build Launcher
        build_launcher(project_root, arch_suffix)
        
        # Build Main App
        # build_app(project_root, arch_suffix)

    except Exception as e:
        print(f"Build failed with exception: {e}")
        
    finally:
        # 4. Cleanup
        if os.path.exists(embedded_file):
            print("Cleaning up embedded credentials...")
            os.remove(embedded_file)
            print("Cleanup done.")

def build_app(project_root, arch_suffix):
    print("Building SalesApp with PyInstaller...")
    main_script = os.path.join(project_root, 'main.py')
    
    # Check if pyinstaller is installed
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except:
        print("Error: PyInstaller not found. Cannot build SalesApp.")
        return

    # Check for existing spec file to preserve custom settings if any
    # But usually for a fresh migration we might want to start clean or use standard args
    # We'll use command line args for simplicity and consistency
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name", "SalesApp",
        "--distpath", os.path.join(project_root, 'dist', f'app{arch_suffix}'), # Output to dist/app_x64 or app_x86
        "--workpath", os.path.join(project_root, 'build', 'temp_app'),
        "--specpath", os.path.join(project_root, 'build'),
        "--clean",
        # Hidden imports often needed for Flet/Boto3
        "--hidden-import", "flet",
        "--hidden-import", "flet.controls",
        "--hidden-import", "flet.page",
        "--hidden-import", "flet.types",
        "--hidden-import", "flet_web",
        "--hidden-import", "boto3", 
        "--hidden-import", "PIL", # Pillow
        "--hidden-import", "qrcode",
        "--collect-all", "flet_web",
        main_script
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("SalesApp build complete.")
    except subprocess.CalledProcessError as e:
        print(f"SalesApp build failed: {e}")

def build_launcher(project_root, arch_suffix):
    print("Building Launcher with PyInstaller...")
    launcher_script = os.path.join(project_root, 'launcher.py')
    
    # Check if pyinstaller is installed
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except:
        print("Error: PyInstaller not found. Cannot build Launcher.")
        return

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name", "Launcher",
        "--distpath", os.path.join(project_root, 'dist', f'launcher{arch_suffix}'),
        "--workpath", os.path.join(project_root, 'build', 'temp_launcher'),
        "--specpath", os.path.join(project_root, 'build'),
        "--clean",
        launcher_script,
        "--hidden-import", "src.embedded_credentials",
        "--hidden-import", "src.db_sqlite",
        "--hidden-import", "src.aws_db",
        "--hidden-import", "certifi"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("Launcher build complete.")
    except subprocess.CalledProcessError as e:
        print(f"Launcher build failed: {e}")

if __name__ == "__main__":
    main()
    # Assume main() finds project root independently, but we can't pass it easily unless we modify main or move logic.
    # Refactoring main to call build_launcher would be cleaner.
    
    # Re-reading main() logic:
    # main() calculates project_root.
    # I should insert the call inside main() or pass it.

