
import serial
import serial.tools.list_ports
import threading
import time

class SerialScanner:
    def __init__(self, port='COM3', baudrate=9600, timeout=0.1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn = None
        self.running = False
        self.thread = None
        self.callback = None
        self.error_callback = None

    @staticmethod
    def find_scanner_port():
        """
        Attempts to find the Elgin Flash II scanner based on VID:PID or description.
        Returns the port name (e.g., 'COM10') or None.
        """
        # Elgin Flash II (observed: VID:PID=28E9:018A)
        TARGET_VID = 0x28E9
        TARGET_PID = 0x018A
        
        ports = serial.tools.list_ports.comports()
        for port in ports:
            # Check for exact VID:PID match
            if port.vid == TARGET_VID and port.pid == TARGET_PID:
                return port.device
            
            # Fallback: Check strictly for "Dispositivo Serial USB" if needed?
            # Or "Elgin" in description if supported drivers show it.
            if "Elgin" in port.description:
                return port.device

        # Fallback 2: If we only have ONE USB Serial Device, assume it's the scanner
        # (This helps if VID/PID varies across batches)
        usb_serial_ports = [
            p for p in ports 
            if "Serial USB" in p.description or "USB Serial" in p.description
        ]
        if len(usb_serial_ports) == 1:
             return usb_serial_ports[0].device
             
        return None


    def set_callback(self, callback):
        """Callback function that receives the scanned barcode (string)."""
        self.callback = callback

    def set_error_callback(self, callback):
        """Callback for connection errors."""
        self.error_callback = callback

    def start(self):
        if self.running:
            return

        try:
            print(f"DEBUG: Attempting to open serial port {self.port}...", flush=True)
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            print("DEBUG: Serial port opened successfully.")
            self.running = True
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
            print(f"Scanner started on {self.port}")
            return True
        except serial.SerialException as e:
            print(f"Failed to open scanner on {self.port}: {e}")
            if self.error_callback:
                self.error_callback(str(e))
            return False

    def stop(self):
        """
        Signals the read loop to stop. 
        The actual connection closure happens in the _read_loop thread.
        """

        print("Stopping scanner.....")
        self.running = False
        # Optional: cancel pending read if possible (requires cancel_read support)
        if self.serial_conn:
            try:
                self.serial_conn.cancel_read()
            except: pass
        
        # Wait for thread to finish closing connection
        if self.thread and self.thread.is_alive():
            try:
                # Wait up to 1 second for the thread to finish
                self.thread.join(timeout=1.0)
            except: pass

    def _read_loop(self):
        buffer = ""
        try:
            while self.running:
                try:
                    if self.serial_conn and self.serial_conn.is_open:
                        if self.serial_conn.in_waiting > 0:
                            # Read available bytes
                            data = self.serial_conn.read(self.serial_conn.in_waiting)
                            try:
                                # Decode and append to buffer
                                text = data.decode('utf-8', errors='ignore')
                                buffer += text
                                
                                # Check for newline (common suffix for scanners)
                                if '\n' in buffer or '\r' in buffer:
                                    # Split lines
                                    lines = buffer.splitlines()
                                    
                                    # Process all full lines
                                    if buffer.endswith('\n') or buffer.endswith('\r'):
                                        # Full message received
                                        for line in lines:
                                            clean_line = line.strip()
                                            if clean_line and self.callback:
                                                self.callback(clean_line)
                                        buffer = ""
                                    else:
                                        # Process complete lines from the middle
                                        pass
    
                            except Exception as decode_err:
                                print(f"Decode error: {decode_err}")
                        else:
                            time.sleep(0.01) # Sleep to save CPU
                    else:
                        break
                except Exception as e:
                    print(f"Scanner loop error: {e}")
                    if self.error_callback:
                        self.error_callback(str(e))
                    self.running = False
                    break
        finally:
            print("Scanner loop exiting, closing connection...", flush=True)
            if self.serial_conn:
                 try:
                     self.serial_conn.close()
                 except Exception as e:
                     print(f"Error closing serial connection: {e}", flush=True)
                 self.serial_conn = None
            print("Scanner connection closed.", flush=True)
