
import sqlite3
import json
from datetime import datetime
import pandas as pd
import numpy as np

import os

class Database:
    def __init__(self, db_path='database_full.db'):
        # Resolve path relative to this file to allow running from any CWD
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.join(base_dir, db_path)
        self.init_db()
        self.shops = self.get_shops()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        create_tables_sql = """
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT NOT NULL,
            category TEXT,
            flavor TEXT,
            UNIQUE(barcode, flavor, category)
        );

        CREATE TABLE IF NOT EXISTS product_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            shop_id INTEGER,
            price REAL,
            UNIQUE(product_id, shop_id),
            FOREIGN KEY(product_id) REFERENCES products(id),
            FOREIGN KEY(shop_id) REFERENCES shops(id)
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            final_price REAL,
            payment_method TEXT,
            products_json TEXT
        );

        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
        try:
            with self.get_connection() as conn:
                conn.executescript(create_tables_sql)
        except sqlite3.Error as e:
            print(f"Error initializing database: {e}")

    def set_config(self, key, value):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        except sqlite3.Error as e:
            print(f"Error setting config: {e}")

    def get_config(self, key):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            print(f"Error getting config: {e}")
            return None

    def reset_config(self, key):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM config WHERE key = ?", (key,))
        except sqlite3.Error as e:
            print(f"Error resetting config: {e}")

    def get_shops(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM shops ORDER BY name")
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Error fetching shops: {e}")
            return []

    def ensure_shop_exists(self, shop_name):
        if shop_name not in self.shops:
            try:
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT OR IGNORE INTO shops (name) VALUES (?)", (shop_name,))
                self.shops = self.get_shops() # Refresh
            except sqlite3.Error as e:
                print(f"Error adding shop: {e}")

    def add_product(self, product_info, shop_name):
        self.ensure_shop_exists(shop_name)
        
        barcode = product_info['barcode']
        category = product_info['categoria']
        flavor = product_info['sabor']
        price = product_info['preco']
        price = product_info['preco']

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Get or Insert Product (Global Attributes)
                cursor.execute("""
                    INSERT OR IGNORE INTO products (barcode, category, flavor)
                    VALUES (?, ?, ?)
                """, (barcode, category, flavor))
                
                # Retrieve product_id (needed because INSERT OR IGNORE might not return rowid if ignored)
                cursor.execute("SELECT id FROM products WHERE barcode = ? AND category = ? AND flavor = ?", (barcode, category, flavor))
                product_id = cursor.fetchone()[0]

                # Get Shop ID
                cursor.execute("SELECT id FROM shops WHERE name = ?", (shop_name,))
                shop_id = cursor.fetchone()[0]

                # Insert or Update Price
                cursor.execute("""
                    INSERT INTO product_prices (product_id, shop_id, price)
                    VALUES (?, ?, ?)
                    ON CONFLICT(product_id, shop_id) DO UPDATE SET
                    price=excluded.price
                """, (product_id, shop_id, price))
                
        except sqlite3.Error as e:
            print(f"Error adding product: {e}")
            raise e

    def get_products_dataframe(self):
        """Returns a DataFrame similar to the one used previously, for compatibility."""
        try:
            with self.get_connection() as conn:
                
                # Fetch all data needed to reconstruct the DataFrame
                query = """
                SELECT 
                    p.barcode, p.category, p.flavor, 
                    s.name as shop_name, 
                    pp.price
                FROM products p
                JOIN product_prices pp ON p.id = pp.product_id
                JOIN shops s ON pp.id = s.shop_id
                """
                # This complex reconstruction might be better handled by just fetching
                # specific queries for the UI, but to maintain 'df' structure for now:
                # Actually, implementing full DataFrame reconstruction is complex and inefficient.
                # Let's support the specific methods the UI needs instead.
                pass
        except sqlite3.Error:
            pass
        return pd.DataFrame() # Return empty for now, we will refactor usage.

    def get_products_by_barcode_and_shop(self, barcode, shop_name):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                SELECT p.barcode, p.category, p.flavor, pp.price, p.id
                FROM products p
                JOIN product_prices pp ON p.id = pp.product_id
                JOIN shops s ON pp.shop_id = s.id
                WHERE p.barcode = ? AND s.name = ?
                """
                cursor.execute(query, (barcode, shop_name))
                rows = cursor.fetchall()
                
                # Convert to DataFrame for compatibility
                data = []
                for row in rows:
                    data.append({
                        ('Todas', 'Codigo de Barras'): row[0],
                        ('Todas', 'Categoria'): row[1],
                        ('Todas', 'Sabor'): row[2],
                        (shop_name, 'Preco'): row[3],
                        ('Metadata', 'Excel Row'): row[4] # Use Product ID as ID
                    })
                return pd.DataFrame(data)
        except sqlite3.Error as e:
            print(f"Error fetching products: {e}")
            return pd.DataFrame()

    def get_product_info(self, product_id, shop_name):
        """Fetch product details by ID for the GUI update loop."""
        try:
            # Check typing, often pandas passes numpy types
            try:
                product_id = int(product_id)
            except:
                pass
            
            # print(f"DEBUG: get_product_info id={product_id} type={type(product_id)} shop={shop_name}")
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                SELECT p.barcode, p.category, p.flavor, pp.price
                FROM products p
                JOIN product_prices pp ON p.id = pp.product_id
                JOIN shops s ON pp.shop_id = s.id
                WHERE p.id = ? AND s.name = ?
                """
                cursor.execute(query, (product_id, shop_name))
                row = cursor.fetchone()
                if row:
                     return {
                        ('Todas', 'Codigo de Barras'): row[0],
                        ('Todas', 'Categoria'): row[1],
                        ('Todas', 'Sabor'): row[2],
                        (shop_name, 'Preco'): row[3],
                        ('Metadata', 'Excel Row'): product_id
                    }
                else:
                    print(f"DEBUG: Product not found in DB for id={product_id} shop={shop_name}")
        except sqlite3.Error as e:
            print(f"Error in get_product_info: {e}")
            pass
        return None

    def search_products(self, search_term, shop_name):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Simple wildcard search
                term = f"%{search_term}%"
                query = """
                SELECT p.barcode, p.category, p.flavor, pp.price, p.id
                FROM products p
                JOIN product_prices pp ON p.id = pp.product_id
                JOIN shops s ON pp.shop_id = s.id
                WHERE s.name = ? AND (
                    p.barcode LIKE ? OR 
                    p.category LIKE ? OR 
                    p.flavor LIKE ? OR
                    CAST(pp.price AS TEXT) LIKE ?
                )
                """
                cursor.execute(query, (shop_name, term, term, term, term))
                rows = cursor.fetchall()
                
                data = []
                for row in rows:
                    data.append({
                        ('Todas', 'Codigo de Barras'): row[0],
                        ('Todas', 'Categoria'): row[1],
                        ('Todas', 'Sabor'): row[2],
                        (shop_name, 'Preco'): row[3],
                         ('Metadata', 'Excel Row'): row[4]
                    })
                return pd.DataFrame(data)
        except sqlite3.Error as e:
            print(f"Error searching products: {e}")
            return pd.DataFrame()

    def record_sale(self, final_price, payment_method, products_dict):
        try:
            # Helper to convert numpy types to python native types
            def convert_numpy(obj):
                if isinstance(obj, dict):
                    return {str(k): convert_numpy(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_numpy(i) for i in obj]
                elif isinstance(obj, (np.int_, np.intc, np.intp, np.int8,
                    np.int16, np.int32, np.int64, np.uint8,
                    np.uint16, np.uint32, np.uint64)):
                    return int(obj)
                elif isinstance(obj, (np.float16, np.float32, np.float64)):
                    return float(obj)
                elif isinstance(obj, (np.ndarray,)): 
                    return convert_numpy(obj.tolist())
                return obj

            clean_products = convert_numpy(products_dict)
            products_json = json.dumps(clean_products)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sales (final_price, payment_method, products_json)
                    VALUES (?, ?, ?)
                """, (final_price, payment_method, products_json))
        except sqlite3.Error as e:
            print(f"Error recording sale: {e}")
            raise e

    def get_sales_history(self):
        try:
            with self.get_connection() as conn:
                # Use pandas to read sql is easier for compatibility
                query = "SELECT timestamp, final_price, payment_method, products_json FROM sales ORDER BY timestamp DESC"
                df = pd.read_sql_query(query, conn)
                
                # Transform to match expected format
                df['Data'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d')
                df['Horario'] = pd.to_datetime(df['timestamp']).dt.strftime('%H:%M:%S')
                df.rename(columns={
                    'final_price': 'Preco Final', 
                    'payment_method': 'Metodo de pagamento',
                    'products_json': 'Produtos'
                }, inplace=True)
                
                # Parse JSON products back to dict/string representation if needed, 
                # but the current history viewer expects string or dict structure.
                # The previous implementation stored string representation of dict.
                # json.dumps creates a string, so it should be compatible if we parse it back
                # OR we keep it as string if the viewer evals it.
                # history.py uses safe_eval_produtos which uses ast.literal_eval.
                # JSON string is compatible with ast.literal_eval for basic types.
                
                return df
        except Exception as e:
            print(f"Error fetching history: {e}")
            return pd.DataFrame()

    # Property for compatibility
    @property
    def df(self):
        # Allow accessing shops directly via retrieving all prices?
        # This is strictly related to how 'select_shop_window' works.
        # It needs 'shops'.
        return self # partial mock

