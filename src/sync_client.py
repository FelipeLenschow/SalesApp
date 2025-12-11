
import requests
import json
import sqlite3
import src.db_sqlite as db
from datetime import datetime

class SyncClient:
    def __init__(self, server_url, db_instance: db.Database):
        self.server_url = server_url
        self.db = db_instance

    def get_shops(self):
        try:
            response = requests.get(f"{self.server_url}/shops", timeout=5)
            response.raise_for_status()
            return response.json().get("shops", [])
        except Exception as e:
            print(f"Error fetching shops: {e}")
            return []

    def sync(self):
        """
        1. Get unsynced sales (For now we assume all sales that are NOT in specific range? 
           Or we add a 'synced' flag to sales table? 
           For this 'simple' version, we will just send ALL sales and let Server dedup.)
        2. Send to server.
        3. Receive products.
        4. Update local DB.
        """
        results = {"uploaded": 0, "downloaded": 0, "message": ""}
        
        # 1. Get Sales
        sales_data = []
        try:
            # We don't have a 'synced' column yet.
            # We can treat all local sales as candidates.
            df_sales = self.db.get_sales_history() 
            # df_sales has: Data, Horario, Preco Final, Metodo de pagamento, Produtos
            # We need to convert back to raw format for the API
            
            # Ideally database.get_sales_history() would return raw objects too.
            # Let's read raw table for accuracy.
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
            return results

        # 2. Send to Server
        try:
            # Get current shop name to filter products
            shop_name = self.db.get_config('current_shop')
            
            payload = {
                "sales": sales_data,
                "shop_name": shop_name
            }
            response = requests.post(f"{self.server_url}/sync", json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            results["uploaded"] = data.get("imported_sales", 0)
            products_update = data.get("products_update", [])
            
        except Exception as e:
            results["message"] = f"Connection error: {e}"
            return results

        # 3. Update Local DB
        count = 0
        try:
            # We iterate received products and use db.add_product
            # db.add_product handles INSERT OR IGNORE / UPDATE logic
            for p in products_update:
                product_info = {
                    'barcode': p['barcode'],
                    'categoria': p['categoria'],
                    'sabor': p['sabor'],
                    'preco': p['preco']
                }
                shop_name = p['shop_name']
                self.db.add_product(product_info, shop_name)
                count += 1
            
            results["downloaded"] = count
            results["message"] = "Sync completed successfully"
            
        except Exception as e:
            results["message"] = f"Error updating local products: {e}"

        return results
