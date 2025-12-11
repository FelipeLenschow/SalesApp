import tkinter as tk
import requests
import qrcode
from PIL import Image, ImageTk  # Ensure both Image and ImageTk are imported
import threading
import time

import src.config as config

class Payment:
    def __init__(self, app, shop):
        self.shop = shop
        self.app = app

    def create_payment_intent_card(self, amount, internal_id):

        url = "https://api.mercadopago.com/point/integration-api/devices/" + config.device + "/payment-intents"
        headers = {
            "Authorization": "Bearer " + config.id_token,
            "Content-Type": "application/json"
        }
        payload = {
            "amount": amount * 100,
            "description": "Lolla sorveteria",
            "additional_info": {
                "external_reference": internal_id,
                "print_on_terminal": True
            }
        }
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def create_payment_intent_debit(self, amount, internal_id):

        url = "https://api.mercadopago.com/point/integration-api/devices/" + config.device + "/payment-intents"
        headers = {
            "Authorization": "Bearer " + config.id_token,
            "Content-Type": "application/json"
        }
        payload = {
            "amount": amount * 100,
            "description": "Lolla sorveteria",
            "payment": {
                "type": "debit_card"
            },
            "additional_info": {
                "external_reference": internal_id,
                "print_on_terminal": True
            }
        }
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def create_payment_intent_credit(self, amount, internal_id):

        url = "https://api.mercadopago.com/point/integration-api/devices/" + config.device + "/payment-intents"
        headers = {
            "Authorization": "Bearer " + config.id_token,
            "Content-Type": "application/json"
        }
        payload = {
            "amount": amount * 100,
            "description": "Lolla sorveteria",
            "payment": {
                "installments": 1,
                "installments_cost": "seller",
                "type": "credit_card"
            },
            "additional_info": {
                "external_reference": internal_id,
                "print_on_terminal": True
            }
        }
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def create_payment_intent_pix(self, amount, internal_id):
        url = "https://api.mercadopago.com/instore/orders/qr/seller/collectors/" + config.user_id + "/pos/" + config.pos_name + "/qrs"
        headers = {
            "Authorization": "Bearer " + config.id_token,
            "Content-Type": "application/json"
        }
        payload = {
            "external_reference": internal_id,
            "title": "Product order",
            "description": "Purchase description.",
            "total_amount": amount,
            "items": [
                {
                    "title": "Lolla Sorveteria",
                    "unit_price": amount,
                    "quantity": 1,
                    "unit_measure": "unit",
                    "total_amount": amount
                }
            ]
        }
        try:
            response = requests.put(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def confirm_payment_card(self, payment_intent_id):

        url = f"https://api.mercadopago.com/point/integration-api/payment-intents/{payment_intent_id}"
        headers = {
            "Authorization": "Bearer " + config.id_token,
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def confirm_payment_pix(self):

        url = "https://api.mercadopago.com/instore/qr/seller/collectors/" + config.user_id + "/pos/" + config.pos_name + "/orders"
        headers = {
            "Authorization": "Bearer " + config.id_token,
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def delete_pix(self):

        url = "https://api.mercadopago.com/instore/qr/seller/collectors/" + config.user_id + "/pos/" + config.pos_name + "/orders"
        headers = {
            "Authorization": "Bearer " + config.id_token,
            "Content-Type": "application/json"
        }

        try:
            response = requests.delete(url, headers=headers)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"error {str(e)}")

    def wait_for_payment_to_finish_card(self, payment_intent_id, internal_id, poll_interval=1):

        while True:
            response = self.confirm_payment_card(payment_intent_id)
            if "state" in response:
                state = response["state"]
                self.app.update_status(state)

                print(f"Payment state: {state}")
                # if state in ["OPEN", "ON_TERMINAL", "PROCESSING"]:  # Adjust as per terminal state
                if state == "FINISHED":
                    payment_id = response.get("id")
                    print(f"Payment approved with ID: {payment_id}")
                    self.app.finalize_sale(internal_id)
                    return payment_id

                if state == "CANCELED" or state == "ABANDONED":
                    payment_id = response.get("id")
                    print(state)
                    print(f"Payment canceled/abandoned with ID: {payment_id}")
                    return payment_id
            else:
                print(f"Error checking payment state: {response.get('error', 'Unknown error')}")
            time.sleep(poll_interval)

    def wait_for_payment_to_finish_pix(self, internal_id, qr_window, poll_interval=1):

        while True:
            response = self.confirm_payment_pix()
            # print("response::")
            # print(response)
            if "external_reference" in response:
                external_reference_ = response["external_reference"]
                if internal_id != external_reference_:
                    print(f"{external_reference_} != {internal_id}")
                    return external_reference_
                else:
                    time.sleep(poll_interval)
            else:
                print(f"Payment finished with external_reference {internal_id}")
                qr_window.destroy()  # Close the QR code window
                self.app.finalize_sale(internal_id)
                return

    def display_qr_code(self, qr_data, internal_id):
        # Generate the QR code
        self.app.update_status("Gerando QR")

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=int(10 * self.app.scale_factor),  # Adjust box size
            border=4
        )
        qr.add_data(qr_data)
        qr.make()

        win_width = int(1000 * self.app.scale_factor)
        win_height = int(1000 * self.app.scale_factor)
        qr_width = int(900 * self.app.scale_factor)
        qr_height = int(900 * self.app.scale_factor)

        # Create an image of the QR code
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((qr_width, qr_height), Image.Resampling.LANCZOS)  # Updated resizing method
        qr_photo = ImageTk.PhotoImage(img)

        # Create a new Tkinter window for the QR code
        qr_window = tk.Toplevel(self.app.root)
        qr_window.title("Scan QR Code")
        qr_window.configure(bg="#8b0000")
        qr_window.attributes("-topmost", True)

        # Set the window size and make it modal
        qr_window.geometry(f"{win_width}x{win_height}")
        qr_window.resizable(False, False)
        qr_window.grab_set()  # Make the window modal

        # Add the QR code image to the window
        qr_label = tk.Label(qr_window, image=qr_photo, bg="#8b0000")
        qr_label.image = qr_photo  # Keep a reference to avoid garbage collection
        qr_label.pack(expand=True)

        self.app.update_status("Aguardando pagamento")

        # Wait for payment in a separate thread to prevent UI freezing
        threading.Thread(
            target=self.wait_for_payment_to_finish_pix,
            args=(internal_id, qr_window),
            daemon=True
        ).start()

    def update_status_thread(self, pay_amount, internal_id):
        # Update the status first before waiting
        self.app.update_status("Obtendo QR")
        self.delete_pix()
        response = self.create_payment_intent_pix(amount=pay_amount, internal_id=id)

        if "in_store_order_id" in response:
            # After waiting, update status again
            qr = response["qr_data"]
            self.display_qr_code(qr, internal_id)
        else:
            print("Failed to create payment intent.")
            self.app.update_status("Falha")

    def payment(self, pay_amount, payment_type, internal_id):
        self.app.update_status("Iniciando pagamento")


        if payment_type == "":
            response = self.create_payment_intent_card(amount=pay_amount, internal_id=internal_id)
            print(response)

            if "id" in response:
                payment_intent_id = response["id"]

                threading.Thread(
                    target=self.wait_for_payment_to_finish_card,
                    args=(payment_intent_id, internal_id,),
                    daemon=True
                ).start()
            else:
                print("Failed to create payment intent.")
                self.app.update_status("Falha")

        if payment_type == "Débito":
            response = self.create_payment_intent_debit(amount=pay_amount, internal_id=internal_id)
            print(response)

            if "id" in response:
                payment_intent_id = response["id"]

                threading.Thread(
                    target=self.wait_for_payment_to_finish_card,
                    args=(payment_intent_id, internal_id,),
                    daemon=True
                ).start()
            else:
                print("Failed to create payment intent.")
                self.app.update_status("Falha")

        elif payment_type == "Crédito":
            response = self.create_payment_intent_credit(amount=pay_amount, internal_id=internal_id)
            print(response)

            if "id" in response:
                payment_intent_id = response["id"]
                threading.Thread(
                    target=self.wait_for_payment_to_finish_card,
                    args=(payment_intent_id, internal_id,),
                    daemon=True
                ).start()
            else:
                print("Failed to create payment intent.")
                self.app.update_status("Falha")

        elif payment_type == "Pix":
            # Run the sleep and update status in a separate thread
            threading.Thread(target=self.update_status_thread, args=(pay_amount, id,), daemon=True).start()