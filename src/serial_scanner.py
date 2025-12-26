
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
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
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
        self.running = False
        if self.serial_conn:
            try:
                self.serial_conn.close()
            except:
                pass
            self.serial_conn = None

    def _read_loop(self):
        buffer = ""
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
                                # Keep the last part if it was incomplete (not ending in newline)
                                # But splitlines consumes the delimiters.
                                
                                # Better approach for simple scanner:
                                # They usually send CODE + \r\n
                                if buffer.endswith('\n') or buffer.endswith('\r'):
                                    # Full message received
                                    for line in lines:
                                        clean_line = line.strip()
                                        if clean_line and self.callback:
                                            self.callback(clean_line)
                                    buffer = ""
                                else:
                                    # Process complete lines from the middle
                                    # This is a bit tricky with splitlines, let's just use the fact that
                                    # we expect a burst of data.
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
