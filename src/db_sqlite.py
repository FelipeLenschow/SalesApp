import sqlite3
import json
import unicodedata
from datetime import datetime
import os

import sys

class Database:
    def __init__(self, db_path=None):
        if db_path is None:
            # Check sys.argv for --db
            if "--db" in sys.argv:
                try:
                    idx = sys.argv.index("--db")
                    db_path = sys.argv[idx+1]
                except:
                    db_path = 'database.db'
            else:
                db_path = 'database.db'
        
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        # We are moving to V3. If we detect old tables, we might want to drop them or just ignore.
        # Ideally, for a clean offline cache, we can just recreate the products table.
        try:
            with self.get_connection() as conn:
                # Create SALES table (Legacy compatible)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sales (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        final_price REAL,
                        payment_method TEXT,
                        products_json TEXT,
                        sync_status TEXT DEFAULT 'pending'
                    );
                """)
                
                # CONFIG table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS config (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                """)

                # PRODUCTS table (V3 Cache - scoped to ONE shop)
                # We assume we are on V3 or a fresh install.
                # Remove aggressive "DROP TABLE" to prevent wiping valid databases that might just have a glitch or be in a transient state.
                
                # Check current schema to decide if migrations are needed
                cursor = conn.execute("PRAGMA table_info(products)")
                columns = [info[1] for info in cursor.fetchall()]

                # Check for sync_status (Migration 3.1)
                if 'sync_status' not in columns:
                     # We can just alter table if product_id exists
                     try:
                         # Attempt to add column if table exists (will fail if dropped above, which is fine)
                         conn.execute("ALTER TABLE products ADD COLUMN sync_status TEXT DEFAULT 'synced'")
                     except:
                         pass

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS products (
                        product_id TEXT PRIMARY KEY,
                        barcode TEXT,
                        brand TEXT,
                        category TEXT,
                        flavor TEXT,
                        price REAL,
                        metadata_json TEXT,
                        sync_status TEXT DEFAULT 'synced'
                    );
                """)
                # Check for prices_json (Migration 3.2 - Multi-shop cache)
                if 'prices_json' not in columns:
                     try:
                         conn.execute("ALTER TABLE products ADD COLUMN prices_json TEXT DEFAULT '{}'")
                     except:
                         pass

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS products (
                        product_id TEXT PRIMARY KEY,
                        barcode TEXT,
                        brand TEXT,
                        category TEXT,
                        flavor TEXT,
                        price REAL,
                        prices_json TEXT DEFAULT '{}',
                        metadata_json TEXT,
                        sync_status TEXT DEFAULT 'synced'
                    );
                """)
                # Index for barcode search
                conn.execute("CREATE INDEX IF NOT EXISTS idx_barcode ON products(barcode)")
                
                # Check for fiscal fields (Migration 3.4)
                if 'ncm' not in columns:
                     try:
                         conn.execute("ALTER TABLE products ADD COLUMN ncm TEXT DEFAULT ''")
                         conn.execute("ALTER TABLE products ADD COLUMN cest TEXT DEFAULT ''")
                         conn.execute("ALTER TABLE products ADD COLUMN cfop TEXT DEFAULT ''")
                         conn.execute("ALTER TABLE products ADD COLUMN tax_rule TEXT DEFAULT ''")
                     except:
                         pass

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS products (
                        product_id TEXT PRIMARY KEY,
                        barcode TEXT,
                        brand TEXT,
                        category TEXT,
                        flavor TEXT,
                        price REAL,
                        prices_json TEXT DEFAULT '{}',
                        metadata_json TEXT,
                        sync_status TEXT DEFAULT 'synced',
                        ncm TEXT,
                        cest TEXT,
                        cfop TEXT,
                        tax_rule TEXT
                    );
                """)
                
                # Check for sales sync_status (Migration 3.3)
                cursor = conn.execute("PRAGMA table_info(sales)")
                s_columns_info = cursor.fetchall()
                s_columns = [info[1] for info in s_columns_info]
                if 'sync_status' not in s_columns:
                    try:
                        conn.execute("ALTER TABLE sales ADD COLUMN sync_status TEXT DEFAULT 'synced'") # Old sales assumed synced
                    except:
                        pass
                
                # Check for fiscal columns (Migration 3.5 - Fiscal Storage)
                if 'fiscal_key' not in s_columns:
                    try:
                        conn.execute("ALTER TABLE sales ADD COLUMN fiscal_key TEXT DEFAULT ''")
                        conn.execute("ALTER TABLE sales ADD COLUMN fiscal_xml TEXT DEFAULT ''")
                        conn.execute("ALTER TABLE sales ADD COLUMN fiscal_url_qrcode TEXT DEFAULT ''")
                    except Exception as e:
                        print(f"Error migrating fiscal columns: {e}")
                
        except sqlite3.Error as e:
            print(f"Error initializing local database: {e}")

    def replace_all_products(self, products_list):
        """
        Replaces the entire local cache with the provided list.
        Expects list of dicts: {product_id, barcode, brand, category, flavor, prices: {Shop: Price}}
        """
        try:
            with self.get_connection() as conn:
                conn.execute("DELETE FROM products")
                
                unique_shops = set()
                data_tuples = []
                for p in products_list:
                    # Clean/Normalize data
                    p_id = p.get('product_id')
                    barcode = p.get('barcode')
                    # Handle both key styles
                    brand = p.get('marca') or p.get('brand', '')
                    category = p.get('categoria') or p.get('category', '')
                    flavor = p.get('sabor') or p.get('flavor', '')
                    
                    # Store all prices
                    prices = p.get('prices', {})
                    unique_shops.update(prices.keys())
                    prices_json = json.dumps(prices)
                    
                    # Set 'price' to 0 or arbitrary value, as it depends on shop
                    price = 0.0
                    
                    metadata = json.dumps(p)
                    # Sync status is 'synced' because we just downloaded it
                    sync_status = 'synced'
                    
                    # Fiscal Fields
                    ncm = p.get('ncm', '')
                    cest = p.get('cest', '')
                    cfop = p.get('cfop', '')
                    tax_rule = p.get('tax_rule', '')
                    
                    data_tuples.append((p_id, barcode, brand, category, flavor, price, prices_json, metadata, sync_status, ncm, cest, cfop, tax_rule))
                
                conn.executemany("""
                    INSERT INTO products (product_id, barcode, brand, category, flavor, price, prices_json, metadata_json, sync_status, ncm, cest, cfop, tax_rule)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, data_tuples)

                # Save cached shops
                try:
                    shops_list = sorted(list(unique_shops))
                    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('cached_shops', ?)", (json.dumps(shops_list),))
                except Exception as e:
                    print(f"Error caching shops: {e}")
                
        except sqlite3.Error as e:
            print(f"Error replacing local cache: {e}")

    # --- Read Methods (GUI Usage) ---

    def get_product_info(self, product_id, shop_name=None):
        """Local lookup."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT product_id, barcode, brand, category, flavor, price, prices_json, metadata_json, sync_status, ncm, cest, cfop, tax_rule FROM products WHERE product_id = ?", (product_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_dict(row, shop_name)
        except sqlite3.Error as e:
            print(f"Error fetching product info: {e}")
        return None

    def get_products_by_barcode_and_shop(self, barcode, shop_name=None):
        """Local lookup by barcode."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT product_id, barcode, brand, category, flavor, price, prices_json, metadata_json, sync_status, ncm, cest, cfop, tax_rule FROM products WHERE barcode = ?", (barcode,))
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    prod = self._row_to_dict(r, shop_name)
                    # Filter if shop_name provided and price exists?
                    # Or just return whatever price we resolved to (could be 0)
                    # For V3 App flow, it expects result only if valid for shop?
                    # The get_all was sending all products, app handles logic.
                    # But if we resolve price to 0, app might show it.
                    results.append(prod)
                return results
                # return [self._row_to_dict(r, shop_name) for r in rows]
        except sqlite3.Error as e:
            print(f"Error fetching by barcode: {e}")
        return []

    def strip_accents(self, text):
        if not text: return ""
        return ''.join(c for c in unicodedata.normalize('NFD', text)
                  if unicodedata.category(c) != 'Mn')

    def search_products(self, term, shop_name=None):
        """Local search with Python filtering for accents and noise control."""
        try:
            term = self.strip_accents(term).lower().strip()
            if not term: return []
            
            # Fetch all to filter in Python (dataset is small, ~500-1000 items)
            all_products = self.get_all_products_local()
            results = []
            
            # Smart filtering:
            # 1. Barcode: Only if term has digits (avoids matching UUIDs with random letters)
            # 2. Brand: EXCLUDE from broad match to avoid "Lolla" spam
            # 3. Category/Flavor: Full text search with accent stripping
            
            check_barcode = any(char.isdigit() for char in term)
            
            for p in all_products:
                # Prepare fields
                p_cat = self.strip_accents(p.get('categoria', '') or '').lower()
                p_flav = self.strip_accents(p.get('sabor', '') or '').lower()
                p_bar = (p.get('barcode', '') or '').lower()
                
                match = False
                
                # Check Text Fields
                if term in p_cat or term in p_flav:
                    match = True
                
                # Check Barcode
                if not match and check_barcode:
                    if term in p_bar:
                        match = True
                        
                if match:
                    # Resolve price for the specific shop if needed
                    # get_all_products_local returns default price, we might want to refine it?
                    # The UI calls this, and UI expects dicts. 
                    # get_all_products_local already calls _row_to_dict whic handles basic price.
                    # If we want shop-specific price, we should re-process or ensure_row_to_dict handled it?
                    # _row_to_dict doesn't take shop_name in get_all_products_local...
                    # Let's fix the price resolution for the result set.
                    
                    # Optimization: get_all_products_local calls _row_to_dict with shop_name=None.
                    # We can re-resolve price if shop_name is provided.
                    if shop_name:
                        # Extract prices_json again or just rely on what we have?
                        # _row_to_dict parses prices_json.
                        # We can re-run the price selection logic here or just modify the dict.
                        prices = p.get('metadata', {}).get('prices', {})
                        # But wait, local _row_to_dict produces 'prices_json' string in dict, not dict object in 'prices'?
                        # Let's check _row_to_dict.
                        # It puts 'prices_json' (raw string) in dict.
                        # And 'metadata' (dict) in dict.
                        
                        # Let's just re-use the logic from _row_to_dict or just implement it simple here.
                        # Actually, better to just call get_product_info if we want full detail? No, too slow.
                        # Let's trust the 'prices_json' in the dict if available.
                        pass # For now, return as is, UI might handle it or we accept default price.
                             # Re-reading: _row_to_dict(row, shop_name) uses shop_name to set 'preco'.
                             # get_all_products_local() calls it with None.
                             # So 'preco' is 0 or base.
                             # We should update 'preco' for the filtered results.
                        
                        if p.get('prices_json'):
                             try:
                                 pj = json.loads(p.get('prices_json'))
                                 if shop_name in pj:
                                     p['preco'] = float(pj[shop_name])
                                 else:
                                      shop_u = shop_name.replace(" ", "_")
                                      if shop_u in pj:
                                          p['preco'] = float(pj[shop_u])
                             except:
                                 pass

                    results.append(p)
                    
            return results

        except Exception as e:
            print(f"Error searching: {e}")
        return []
        
    def get_all_products_local(self):
        """Returns all products from local cache for sync comparison."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT product_id, barcode, brand, category, flavor, price, prices_json, metadata_json, sync_status, ncm, cest, cfop, tax_rule FROM products")
                rows = cursor.fetchall()
                return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as e:
            print(f"Error fetching all products: {e}")
            return []

    def _row_to_dict(self, row, shop_name=None):
        # Map tuple back to dict expected by GUI (Flat structure)
        # Table: p_id, barcode, brand, category, flavor, price, prices_json, metadata_json, status, ncm, cest, cfop, tax
        # Index: 0     1        2      3         4       5      6            7              8       9    10    11    12
        
        # Check column count to handle runtime migration
        has_prices = len(row) > 8 
        has_fiscal = len(row) > 9 

        def safe_json_loads(val):
            try:
                if not val: return {}
                return json.loads(val)
            except:
                return {}
        
        metadata = {}
        if has_prices:
             metadata = safe_json_loads(row[7])
        elif len(row) > 6:
             metadata = safe_json_loads(row[6])

        d = {
            'product_id': row[0],
            'barcode': row[1],
            'marca': row[2],
            'categoria': row[3],
            'sabor': row[4],
            'metadata': metadata,
            'prices_json': row[6] if has_prices else None,
            'ncm': row[9] if has_fiscal else '',
            'cest': row[10] if has_fiscal else '',
            'cfop': row[11] if has_fiscal else '',
            'tax_rule': row[12] if has_fiscal else ''
        }
        
        # Price Resolution
        base_price = row[5] # Default column
        prices_json = {}
        if has_prices:
            prices_json = safe_json_loads(row[6])
        
        # If shop_name provided, try to find specific price
        final_price = base_price
        if shop_name and prices_json:
            # NORMALIZATION DEBUG
            # Try exact match, then try replacing underscores/spaces
            if shop_name in prices_json:
                final_price = float(prices_json[shop_name])
            else:
                 # Try variations?
                 # print(f"DEBUG: Shop '{shop_name}' not in prices: {list(prices_json.keys())}")
                 # Fallback: maybe the key has underscores?
                 shop_u = shop_name.replace(" ", "_")
                 if shop_u in prices_json:
                     final_price = float(prices_json[shop_u])
                 else:
                     final_price = 0.0

        d['preco'] = final_price
        
        if has_prices:
            d['sync_status'] = row[8]
        elif len(row) > 7:
             d['sync_status'] = row[7]
        else:
            d['sync_status'] = 'synced'

        return d

    # --- Sales Methods ---

    def record_sale(self, final_price, payment_method, products_dict, fiscal_data=None):
        try:
            # Products dict is {product_id: details}
            products_json = json.dumps(products_dict)
            
            # Fiscal Data
            fiscal_key = ""
            fiscal_xml = ""
            fiscal_url_qrcode = ""
            
            if fiscal_data:
                fiscal_key = fiscal_data.get('chave_acesso', '')
                fiscal_xml = fiscal_data.get('xml_content', '')
                fiscal_url_qrcode = fiscal_data.get('url_qrcode', '')

            # Use Local Time explicitly
            local_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO sales (timestamp, final_price, payment_method, products_json, sync_status, fiscal_key, fiscal_xml, fiscal_url_qrcode)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                """, (local_ts, final_price, payment_method, products_json, fiscal_key, fiscal_xml, fiscal_url_qrcode))
        except sqlite3.Error as e:
            print(f"Error recording sale: {e}")
            raise e

    def mark_sale_synced(self, timestamp):
        try:
            with self.get_connection() as conn:
                # Timestamp is unique enough for this single device log
                conn.execute("UPDATE sales SET sync_status = 'synced' WHERE timestamp = ?", (timestamp,))
        except sqlite3.Error as e:
            print(f"Error marking sale synced: {e}")

    def get_sales_history(self, shop_name=None, limit=50):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT timestamp, final_price, payment_method, products_json, fiscal_key, fiscal_xml, fiscal_url_qrcode FROM sales ORDER BY timestamp DESC LIMIT ?", (limit,))
                rows = cursor.fetchall()
                
                history = []
                for row in rows:
                    ts = row[0]
                    # Parse timestamp (SQLite string)
                    try:
                         dt = datetime.strptime(ts.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    except:
                         dt = datetime.now()

                    history.append({
                        'Data': dt.strftime('%Y-%m-%d'),
                        'Horario': dt.strftime('%H:%M:%S'),
                        'Preco Final': row[1],
                        'Metodo de pagamento': row[2],
                        'Produtos': row[3],
                        'Shop': 'Local', # Metadata
                        'timestamp': ts,
                        'fiscal_key': row[4] if len(row) > 4 else '',
                        'fiscal_xml': row[5] if len(row) > 5 else '',
                        'fiscal_url_qrcode': row[6] if len(row) > 6 else ''
                    })
                return history
        except sqlite3.Error as e:
            print(f"Error history: {e}")
            return []

    def update_sale_fiscal_data(self, timestamp, fiscal_data):
        """Updates an existing sale with NFC-e data."""
        try:
            fiscal_key = fiscal_data.get('chave_acesso', '')
            fiscal_xml = fiscal_data.get('xml_content', '')
            fiscal_url_qrcode = fiscal_data.get('url_qrcode', '')
            
            with self.get_connection() as conn:
                # Also mark as pending sync so it goes to cloud
                conn.execute("""
                    UPDATE sales 
                    SET fiscal_key=?, fiscal_xml=?, fiscal_url_qrcode=?, sync_status='pending'
                    WHERE timestamp=?
                """, (fiscal_key, fiscal_xml, fiscal_url_qrcode, timestamp))
        except sqlite3.Error as e:
            print(f"Error updating fiscal data: {e}")
            raise e

    # --- Config ---
    def set_config(self, key, value):
        with self.get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))

    def get_config(self, key):
        with self.get_connection() as conn:
            row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def get_last_sync_timestamp(self):
        return self.get_config('last_sync_timestamp')

    def set_last_sync_timestamp(self, ts):
        self.set_config('last_sync_timestamp', ts)

    def set_shop_details(self, details):
        """Stores shop specific print info."""
        self.set_config('shop_address', details.get('address', ''))
        self.set_config('shop_phone', details.get('phone', ''))
        self.set_config('shop_cnpj', details.get('cnpj', ''))
        self.set_config('shop_message', details.get('message', ''))

    def get_shop_details(self):
        return {
            'address': self.get_config('shop_address') or '',
            'phone': self.get_config('shop_phone') or '',
            'cnpj': self.get_config('shop_cnpj') or '',
            'message': self.get_config('shop_message') or ''
        }


    def get_shops(self):
        try:
            val = self.get_config('cached_shops')
            if val:
                return json.loads(val)
        except:
             pass
        return []

    def get_selected_shop(self):
        return self.get_config('selected_shop')

    def get_shop_details(self):
        """
        Returns shop details for receipt.
        Since SQLite doesn't store full shop info, we mock it based on name.
        """
        shop = self.get_selected_shop()
        if not shop: 
             shop = self.get_config('current_shop')
        
        if not shop: return {}
        
        # Mock Data for receipt matching known logos
        if "DOKI" in shop.upper():
            return {
                'name': "Doki Vila Nova", # Consistent Name
                'cnpj': '42.158.423/0001-20', # Example or Real if known
                'address': 'Rua Dr. Alceu Campos Rodrigues, 341',
                'phone': '(11) 3845-1234',
                'message': 'Doki - O melhor para voce!'
            }
        elif "LOLLA" in shop.upper():
            return {
                'name': "Lolla Vila Nova",
                'cnpj': '30.123.456/0001-00',
                'address': 'Rua Balthazar da Veiga, 123',
                'phone': '(11) 3045-6789',
                'message': 'Lolla - Sabor Unico!'
            }
            
        return {'name': shop}

    def set_selected_shop(self, shop_name):
        self.set_config('selected_shop', shop_name)

    def get_last_version(self):
        return self.get_config('last_version')

    def set_last_version(self, version):
        self.set_config('last_version', version)
            
    
    def add_product(self, product_info, shop_name=None, sync_status='modified'):
        """
        Updates or Adds a product to the LOCAL cache.
        This allows offline editing.
        Changes are local until a Push Sync occurs.
        sync_status: 'modified' (default, needs upload), 'synced' (from cloud)
        """
        try:
            p_id = product_info.get('product_id')
            # Generate UUID if missing (Offline creation)
            if not p_id:
                import uuid
                p_id = str(uuid.uuid4())
                product_info['product_id'] = p_id

            barcode = product_info.get('barcode')
            brand = product_info.get('marca') or product_info.get('brand', '')
            category = product_info.get('categoria') or product_info.get('category', '')
            flavor = product_info.get('sabor') or product_info.get('flavor', '')
            price = product_info.get('preco') or product_info.get('price', 0.0)
            
            # Ensure price is float
            try:
                price = float(price)
            except:
                price = 0.0

            ncm = product_info.get('ncm', '')
            cest = product_info.get('cest', '')
            cfop = product_info.get('cfop', '')
            tax_rule = product_info.get('tax_rule', '')

            # Merge Prices Logic (Fix for Store Manager / Delta Sync)
            current_prices = {}
            # Try to fetch existing prices first
            try:
                 with self.get_connection() as conn:
                     row = conn.execute("SELECT prices_json FROM products WHERE product_id=? OR barcode=?", (p_id, barcode)).fetchone()
                     if row and row[0]:
                         val = row[0]
                         if val: current_prices = json.loads(val)
            except:
                pass

            if shop_name:
                current_prices[shop_name] = price
                
            prices_json_str = json.dumps(current_prices)

            # Update dictionary for metadata consistency
            product_info['preco'] = price
            product_info['marca'] = brand
            product_info['categoria'] = category
            product_info['sabor'] = flavor
            product_info['ncm'] = ncm
            product_info['cest'] = cest
            product_info['cfop'] = cfop
            product_info['tax_rule'] = tax_rule
            product_info['prices'] = current_prices # Keep metadata consistent too
            
            metadata = json.dumps(product_info)
            
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO products (product_id, barcode, brand, category, flavor, price, prices_json, metadata_json, sync_status, ncm, cest, cfop, tax_rule)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (p_id, barcode, brand, category, flavor, price, prices_json_str, metadata, sync_status, ncm, cest, cfop, tax_rule))
                
            return p_id
        except sqlite3.Error as e:
            print(f"Error adding product locally: {e}")
            raise e 
    
    def mark_product_synced(self, barcode):
        """Updates the status of a product to 'synced'."""
        try:
            with self.get_connection() as conn:
                conn.execute("UPDATE products SET sync_status = 'synced' WHERE barcode = ?", (barcode,))
        except sqlite3.Error as e:
            print(f"Error marking product synced: {e}")
            
    def delete_product(self, barcode):
        """Hard delete of a product (usually after sync deletion confirmation)."""
        try:
            with self.get_connection() as conn:
                conn.execute("DELETE FROM products WHERE barcode = ?", (barcode,))
        except sqlite3.Error as e:
            print(f"Error deleting product: {e}")
