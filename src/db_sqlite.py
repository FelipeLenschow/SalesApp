
import sqlite3
import json
from datetime import datetime

class Database:
    def __init__(self, db_path='database.db'):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        create_tables_sql = """
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
            price REAL,
            UNIQUE(product_id),
            FOREIGN KEY(product_id) REFERENCES products(id)
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

    def add_product(self, product_info, shop_name):
        
        barcode = product_info['barcode']
        category = product_info['categoria']
        flavor = product_info['sabor']
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

                # Insert or Update Price
                cursor.execute("""
                    INSERT INTO product_prices (product_id, price)
                    VALUES (?, ?)
                    ON CONFLICT(product_id) DO UPDATE SET
                    price=excluded.price
                """, (product_id, price))
                
        except sqlite3.Error as e:
            print(f"Error adding product: {e}")
            raise e

    def get_products_dataframe(self):
        """Mock method for compatibility - returns empty list."""
        return []

    def get_products_by_barcode_and_shop(self, barcode, shop_name):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                SELECT p.barcode, p.category, p.flavor, pp.price, p.id
                FROM products p
                JOIN product_prices pp ON p.id = pp.product_id
                WHERE p.barcode = ?
                """
                cursor.execute(query, (barcode,))
                rows = cursor.fetchall()
                
                data = []
                for row in rows:
                    data.append({
                        ('Todas', 'Codigo de Barras'): row[0],
                        ('Todas', 'Categoria'): row[1],
                        ('Todas', 'Sabor'): row[2],
                        (shop_name, 'Preco'): row[3],
                        ('Metadata', 'Product ID'): row[4]
                    })
                return data
        except sqlite3.Error as e:
            print(f"Error fetching products: {e}")
            return []

    def get_product_info(self, product_id, shop_name):
        """Fetch product details by ID."""
        try:
            try:
                product_id = int(product_id)
            except:
                pass
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                SELECT p.barcode, p.category, p.flavor, pp.price
                FROM products p
                JOIN product_prices pp ON p.id = pp.product_id
                WHERE p.id = ?
                """
                cursor.execute(query, (product_id,))
                row = cursor.fetchone()
                if row:
                     return {
                        ('Todas', 'Codigo de Barras'): row[0],
                        ('Todas', 'Categoria'): row[1],
                        ('Todas', 'Sabor'): row[2],
                        (shop_name, 'Preco'): row[3],
                        ('Metadata', 'Product ID'): product_id
                    }
                else:
                    # print(f"DEBUG: Product not found in DB for id={product_id} shop={shop_name}")
                    pass
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
                WHERE 
                    p.barcode LIKE ? OR 
                    p.category LIKE ? OR 
                    p.flavor LIKE ? OR
                    CAST(pp.price AS TEXT) LIKE ?
                
                """
                cursor.execute(query, (term, term, term, term))
                rows = cursor.fetchall()
                
                data = []
                for row in rows:
                    data.append({
                        ('Todas', 'Codigo de Barras'): row[0],
                        ('Todas', 'Categoria'): row[1],
                        ('Todas', 'Sabor'): row[2],
                        (shop_name, 'Preco'): row[3],
                         ('Metadata', 'Product ID'): row[4]
                    })
                return data
        except sqlite3.Error as e:
            print(f"Error searching products: {e}")
            return []

    def record_sale(self, final_price, payment_method, products_dict):
        try:
            # Basic type conversion if needed (removed numpy dependency)
            def convert_simple(obj):
                if isinstance(obj, dict):
                    return {str(k): convert_simple(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_simple(i) for i in obj]
                # Assuming no numpy types passed in anymore or standard types cover it
                return obj

            clean_products = convert_simple(products_dict)
            products_json = json.dumps(clean_products)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sales (timestamp, final_price, payment_method, products_json)
                    VALUES (?, ?, ?, ?)
                """, (datetime.now(), final_price, payment_method, products_json))
        except sqlite3.Error as e:
            print(f"Error recording sale: {e}")
            raise e

    def get_sales_history(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT timestamp, final_price, payment_method, products_json FROM sales ORDER BY timestamp DESC"
                cursor.execute(query)
                rows = cursor.fetchall()
                
                history = []
                for row in rows:
                    ts = row[0]
                    # SQLite stores datetime as string generally or we get it as string/obj
                    # If it's a string 'YYYY-MM-DD HH:MM:SS...'
                    try:
                        dt_obj = datetime.strptime(str(ts).split('.')[0], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        try:
                            dt_obj = datetime.strptime(str(ts), '%Y-%m-%d %H:%M:%S')
                        except:
                            # Fallback
                            dt_obj = datetime.now()

                    history.append({
                        'timestamp': ts,
                        'Data': dt_obj.strftime('%Y-%m-%d'),
                        'Horario': dt_obj.strftime('%H:%M:%S'),
                        'Preco Final': row[1],
                        'Metodo de pagamento': row[2],
                        'Produtos': row[3]
                    })
                
                return history
        except Exception as e:
            print(f"Error fetching history: {e}")
            return []

    def get_all_products_local(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                SELECT p.barcode, p.category, p.flavor, pp.price
                FROM products p
                JOIN product_prices pp ON p.id = pp.product_id
                """
                cursor.execute(query)
                rows = cursor.fetchall()
                products = []
                for row in rows:
                    products.append({
                        'barcode': row[0],
                        'categoria': row[1],
                        'sabor': row[2],
                        'preco': row[3]
                    })
                return products
        except sqlite3.Error as e:
            print(f"Error fetching all products: {e}")
            return []

