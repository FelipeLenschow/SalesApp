
import boto3
from botocore.exceptions import ClientError
import json
import os
import decimal
import time
import uuid
from datetime import datetime

# Helper class to convert Python objects to DynamoDB format
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)

class Database:
    def __init__(self, region_name='us-east-1'):
        # 1. Try to load embedded credentials (priority for built exe)
        try:
            import src.embedded_credentials as embedded
            os.environ['AWS_ACCESS_KEY_ID'] = embedded.AWS_ACCESS_KEY_ID
            os.environ['AWS_SECRET_ACCESS_KEY'] = embedded.AWS_SECRET_ACCESS_KEY
            if hasattr(embedded, 'AWS_DEFAULT_REGION'):
                 region_name = embedded.AWS_DEFAULT_REGION
        except ImportError:
            # 2. Check for local credentials file in project root (dev mode)
            local_creds = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.aws', 'credentials')
            if os.path.exists(local_creds):
                os.environ['AWS_SHARED_CREDENTIALS_FILE'] = local_creds

        # Initialize DynamoDB resource
        self.dynamodb = boto3.resource('dynamodb', region_name=region_name)
        
        # Table References
        self.public_shops_table = self.dynamodb.Table('SalesApp_PublicShops')
        self.products_table = self.dynamodb.Table('SalesApp_Products_V3') # V3 Schema
        self.sales_table = self.dynamodb.Table('SalesApp_Sales')
        
        self.init_tables()
        self.shops = []

    def init_tables(self):
        """Check if tables exist, create them if not."""
        try:
            # PUBLIC SHOPS TABLE
            try:
                self.public_shops_table.load()
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print("Creating SalesApp_PublicShops table...")
                    self.public_shops_table = self.dynamodb.create_table(
                        TableName='SalesApp_PublicShops',
                        KeySchema=[{'AttributeName': 'name', 'KeyType': 'HASH'}],
                        AttributeDefinitions=[{'AttributeName': 'name', 'AttributeType': 'S'}],
                        BillingMode='PAY_PER_REQUEST'
                    )
                    self.public_shops_table.wait_until_exists()
            
            # PRODUCTS TABLE (V3)
            # Strategy: PK = product_id (UUID), GSI = BarcodeIndex (barcode)
            try:
                self.products_table.load()
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print("Creating SalesApp_Products_V3 table...")
                    self.products_table = self.dynamodb.create_table(
                        TableName='SalesApp_Products_V3',
                        KeySchema=[
                            {'AttributeName': 'product_id', 'KeyType': 'HASH'},    # Partition Key
                        ],
                        AttributeDefinitions=[
                            {'AttributeName': 'product_id', 'AttributeType': 'S'},
                            {'AttributeName': 'barcode', 'AttributeType': 'S'}
                        ],
                        GlobalSecondaryIndexes=[
                            {
                                'IndexName': 'BarcodeIndex',
                                'KeySchema': [
                                    {'AttributeName': 'barcode', 'KeyType': 'HASH'},
                                ],
                                'Projection': {
                                    'ProjectionType': 'ALL'
                                }
                            }
                        ],
                        BillingMode='PAY_PER_REQUEST'
                    )
                    self.products_table.wait_until_exists()

            # SALES TABLE
            try:
                self.sales_table.load()
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print("Creating SalesApp_Sales table...")
                    self.sales_table = self.dynamodb.create_table(
                        TableName='SalesApp_Sales',
                        KeySchema=[
                            {'AttributeName': 'shop_name', 'KeyType': 'HASH'},
                            {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
                        ],
                        AttributeDefinitions=[
                            {'AttributeName': 'shop_name', 'AttributeType': 'S'},
                            {'AttributeName': 'timestamp', 'AttributeType': 'S'}
                        ],
                        BillingMode='PAY_PER_REQUEST'
                    )
                    self.sales_table.wait_until_exists()
                    
        except ClientError as e:
            print(f"Error initializing DynamoDB tables: {e}")

    # --- Shop Management ---

    def get_shops(self):
        try:
            response = self.public_shops_table.scan()
            items = response.get('Items', [])
            result = [item['name'] for item in items]
            self.shops = result
            return result
        except ClientError as e:
            print(f"Error fetching shops: {e}")
            return []

    def add_shop(self, shop_name):
        try:
            self.public_shops_table.put_item(Item={'name': shop_name})
            return True
        except ClientError as e:
            print(f"Error adding shop: {e}")
            raise e

    def delete_shop(self, shop_name):
        try:
            self.public_shops_table.delete_item(Key={'name': shop_name})
            return True
        except ClientError as e:
            print(f"Error deleting shop: {e}")
            raise e


    # --- Product Management ---

    def _get_price_attr_name(self, shop_name):
        # Sanitize shop name for attribute name safe usage if needed, 
        # but DynamoDB supports most chars. We prefix to avoid collisions.
        # Replacing spaces with underscores is a good convention for "columns".
        return f"price_{shop_name.replace(' ', '_')}"

    def add_product(self, product_info, shop_name):
        """
        Upserts a product.
        If 'product_id' is missing, generates a new one (UUID).
        Updates metadata and the specific shop's price column.
        """
        product_id = product_info.get('product_id')
        barcode = product_info['barcode']
        category = product_info.get('categoria', '')
        flavor = product_info.get('sabor', '')
        brand = product_info.get('marca', '')
        
        # If no product_id, this is technically a NEW product entity.
        if not product_id:
            product_id = str(uuid.uuid4())

        # Price
        try:
            raw_price = product_info.get('preco', 0)
            price = decimal.Decimal(str(raw_price))
        except:
            price = decimal.Decimal('0')

        price_attr = self._get_price_attr_name(shop_name)

        try:
            # UpdateItem allows us to create or update attributes
            # Add last_updated timestamp
            timestamp = datetime.now().isoformat()
            
            self.products_table.update_item(
                Key={'product_id': product_id},
                UpdateExpression="SET barcode=:code, category=:cat, flavor=:flav, brand=:brand, #p=:price, last_updated=:ts",
                ExpressionAttributeNames={
                    '#p': price_attr
                },
                ExpressionAttributeValues={
                    ':code': barcode,
                    ':cat': category,
                    ':flav': flavor,
                    ':brand': brand,
                    ':price': price,
                    ':ts': timestamp
                }
            )
            return product_id
            
        except ClientError as e:
            print(f"Error adding product: {e}")
            raise e

    def delete_product(self, product_id, shop_name):
        """
        Removes the price column for this shop.
        Does NOT delete the product item itself.
        Updates timestamp to trigger sync.
        """
        price_attr = self._get_price_attr_name(shop_name)
        timestamp = datetime.now().isoformat()
        try:
            self.products_table.update_item(
                Key={'product_id': product_id},
                UpdateExpression="REMOVE #p SET last_updated=:ts",
                ExpressionAttributeNames={'#p': price_attr},
                ExpressionAttributeValues={':ts': timestamp}
            )
        except ClientError as e:
            print(f"Error deleting product (price removal): {e}")
            raise e

    def delete_product_completely(self, product_id):
        """
        Deletes the entire product record from the table.
        """
        try:
            self.products_table.delete_item(Key={'product_id': product_id})
        except ClientError as e:
            print(f"Error completely deleting product: {e}")
            raise e

    def get_all_products(self, shop_name=None, progress_callback=None):
        return self.get_products_delta(shop_name=shop_name, last_sync_ts=None, progress_callback=progress_callback)

    def get_products_delta(self, shop_name=None, last_sync_ts=None, progress_callback=None):
        """
        Fetches products. 
        If last_sync_ts provided, returns only items modified after that time.
        """
        try:
            items = []
            kwargs = {}
            price_attr = ""
            
            filter_exp = None
            
            if shop_name:
                price_attr = self._get_price_attr_name(shop_name)
                # FilterExpression: attribute_exists(price_Shop_A)
                filter_exp = boto3.dynamodb.conditions.Attr(price_attr).exists()
            
            if last_sync_ts:
                # Add timestamp filter
                ts_filter = boto3.dynamodb.conditions.Attr('last_updated').gt(last_sync_ts)
                if filter_exp:
                    filter_exp = filter_exp & ts_filter
                else:
                    filter_exp = ts_filter
            
            if filter_exp:
                kwargs['FilterExpression'] = filter_exp
            
            while True:
                response = self.products_table.scan(**kwargs)
                chunk = response.get('Items', [])
                items.extend(chunk)
                
                if progress_callback:
                    progress_callback(len(items))
                
                last_key = response.get('LastEvaluatedKey')
                if not last_key:
                    break
                kwargs['ExclusiveStartKey'] = last_key
                
            # Flatten results
            results = []
            for item in items:
                # If filtered by shop, we return that one price
                if shop_name:
                    p_val = item.get(price_attr, 0.0)
                    results.append({
                        'product_id': item['product_id'],
                        'barcode': item['barcode'],
                        'categoria': item.get('category', ''),
                        'sabor': item.get('flavor', ''),
                        'marca': item.get('brand', ''),
                        'preco': float(p_val),
                        'shop_name': shop_name,
                        'last_updated': item.get('last_updated', '')
                    })
                else:
                    # If all, return all found prices?
                    # Find all attributes starting with price_
                    keys = [k for k in item.keys() if k.startswith("price_")]
                    
                    if not keys:
                         # Product exists but has no prices yet (Unlisted)
                         results.append({
                            'product_id': item['product_id'],
                            'barcode': item['barcode'],
                            'categoria': item.get('category', ''),
                            'sabor': item.get('flavor', ''),
                            'marca': item.get('brand', ''),
                            'preco': 0.0,
                            'shop_name': '',
                            'last_updated': item.get('last_updated', '')
                        })
                    
                    for k in keys:
                        s_name_raw = k.replace("price_", "")
                        s_name = s_name_raw.replace("_", " ") 
                        p_val = item[k]
                        results.append({
                            'product_id': item['product_id'],
                            'barcode': item['barcode'],
                            'categoria': item.get('category', ''),
                            'sabor': item.get('flavor', ''),
                            'marca': item.get('brand', ''),
                            'preco': float(p_val),
                            'shop_name': s_name,
                            'last_updated': item.get('last_updated', '')
                        })

            return results
        except ClientError as e:
            print(f"Error fetching products delta: {e}")
            return []

    def get_all_product_ids(self):
        """
        Fast scan to get all IDs and Barcodes for deletion detection.
        """
        try:
            items = []
            kwargs = {
                'ProjectionExpression': "product_id, barcode"
            }
            
            while True:
                response = self.products_table.scan(**kwargs)
                items.extend(response.get('Items', []))
                
                last_key = response.get('LastEvaluatedKey')
                if not last_key:
                    break
                kwargs['ExclusiveStartKey'] = last_key
                
            return items
        except ClientError as e:
            print(f"Error fetching product IDs: {e}")
            return []

    def get_all_products_grouped(self, progress_callback=None):
        """
        Fetches all products and aggregates prices for ALL shops into a 'prices' dict.
        Returns list of dicts:
        {
            'product_id': ...,
            'barcode': ...,
            ...
            'prices': { 'Shop A': 10.0, 'Shop B': 12.0 }
        }
        """
        try:
            items = []
            kwargs = {}
            
            while True:
                response = self.products_table.scan(**kwargs)
                chunk = response.get('Items', [])
                items.extend(chunk)
                
                if progress_callback:
                    progress_callback(len(items))
                
                last_key = response.get('LastEvaluatedKey')
                if not last_key:
                    break
                kwargs['ExclusiveStartKey'] = last_key
                
            results = []
            for item in items:
                # Base product info
                product = {
                    'product_id': item['product_id'],
                    'barcode': item['barcode'],
                    'categoria': item.get('category', ''),
                    'sabor': item.get('flavor', ''),
                    'marca': item.get('brand', ''),
                    'prices': {}
                }
                
                # Extract prices
                # Keys like "price_Shop_Name"
                for k, v in item.items():
                    if k.startswith("price_"):
                        shop_raw = k.replace("price_", "")
                        # Simple heuristic to restore spaces (matches logic in get_all_products)
                        # We hope shop names don't have intended underscores if we rely on this.
                        # Ideally we'd have a separate Shop table or map, but this works for the current schema.
                        shop_name = shop_raw.replace("_", " ") 
                        try:
                            product['prices'][shop_name] = float(v)
                        except:
                            product['prices'][shop_name] = 0.0
                            
                results.append(product)

            return results
        except ClientError as e:
            print(f"Error fetching grouped products: {e}")
            return []


    def get_product_info(self, product_id, shop_name):
        """
        Fetches by product_id directly.
        """
        try:
            resp = self.products_table.get_item(Key={'product_id': product_id})
            item = resp.get('Item')
            if not item:
                return None
            
            price_attr = self._get_price_attr_name(shop_name)
            if price_attr not in item:
                return None
                
            return {
                'product_id': item['product_id'],
                'barcode': item['barcode'],
                'categoria': item.get('category', ''),
                'sabor': item.get('flavor', ''),
                'marca': item.get('brand', ''),
                'preco': float(item[price_attr]),
                'shop_name': shop_name
            }
        except ClientError as e:
            print(f"Error getting product info: {e}")
            return None

    def search_products(self, term, shop_name):
        """
        Naive search.
        """
        all_prods = self.get_all_products(shop_name=shop_name)
        term = term.lower()
        results = []
        for p in all_prods:
            if (term in p['barcode'].lower() or 
                term in p['categoria'].lower() or 
                term in p['sabor'].lower() or 
                term in p['marca'].lower()):
                results.append(p)
        return results

    def get_products_by_barcode_and_shop(self, barcode, shop_name):
        """
        Uses GSI to find products with this barcode.
        Filters for those that have price for shop_name.
        """
        try:
            response = self.products_table.query(
                IndexName='BarcodeIndex',
                KeyConditionExpression=boto3.dynamodb.conditions.Key('barcode').eq(barcode)
            )
            items = response.get('Items', [])
            
            price_attr = self._get_price_attr_name(shop_name)
            results = []
            
            for item in items:
                if price_attr in item:
                    results.append({
                        'product_id': item['product_id'],
                        'barcode': item['barcode'],
                        'categoria': item.get('category', ''),
                        'sabor': item.get('flavor', ''),
                        'marca': item.get('brand', ''),
                        'preco': float(item[price_attr]),
                        'shop_name': shop_name
                    })
            return results
            
        except ClientError as e:
            print(f"Error querying by barcode: {e}")
            return []

    def get_template_by_barcode(self, barcode):
        """
        Searches globally for a barcode to use as a template.
        Returns basic info (ID, brand, etc) without price.
        Used to prevent creating duplicate product IDs for the same barcode.
        """
        try:
            response = self.products_table.query(
                IndexName='BarcodeIndex',
                KeyConditionExpression=boto3.dynamodb.conditions.Key('barcode').eq(barcode),
                Limit=1
            )
            items = response.get('Items', [])
            if items:
                item = items[0]
                return {
                    'product_id': item['product_id'],
                    'barcode': item['barcode'],
                    'categoria': item.get('category', ''),
                    'sabor': item.get('flavor', ''),
                    'marca': item.get('brand', ''),
                    'preco': 0.0, # Default for new shop
                    'reviewed': True,
                    'scanned': True
                }
            return None
        except Exception as e:
            print(f"Error fetching template: {e}")
            return None

    # --- Sales Management ---

    def record_sale(self, shop_name, sale_data):
        try:
            self.sales_table.put_item(
                Item={
                    'shop_name': shop_name,
                    'timestamp': str(sale_data['timestamp']), # Convert to string for Range Key
                    'final_price': decimal.Decimal(str(sale_data['final_price'])),
                    'payment_method': sale_data['payment_method'],
                    'products_json': sale_data['products_json']
                },
            )
            return True
        except ClientError as e:
             print(f"Error recording sale: {e}")
             raise e

    def get_sales_history(self, shop_name=None, limit=50):
        """
        Fetches recent sales. 
        If shop_name is provided, querying by PK (shop_name) would be ideal. 
        However, currently table PK is shop_name, SK is timestamp.
        """
        try:
            # We need to know which shop to query for.
            # If no shop provided, maybe scan (expensive)? 
            # Ideally the App should pass the current shop.
            
            items = []
            if shop_name:
                response = self.sales_table.query(
                    KeyConditionExpression=boto3.dynamodb.conditions.Key('shop_name').eq(shop_name),
                    ScanIndexForward=False, # Newest first
                    Limit=limit
                )
                items = response.get('Items', [])
            else:
                # Fallback to scan if no shop (or if we want all shops?)
                # For this app, we probably only want the current shop's history if logged in.
                response = self.sales_table.scan(Limit=limit)
                items = response.get('Items', [])
            
            # Map to format expected by UI if possible or just return clean dicts
            results = []
            for item in items:
                # Convert back to simple types
                results.append({
                    'Data': time.strftime('%Y-%m-%d', time.localtime(float(item['timestamp']))),
                    'Horario': time.strftime('%H:%M:%S', time.localtime(float(item['timestamp']))),
                    'Preco Final': float(item.get('final_price', 0)),
                    'Metodo de pagamento': item.get('payment_method', ''),
                    'Produtos': item.get('products_json', '{}'),
                    'Shop': item.get('shop_name', '')
                })
            return results
        except Exception as e:
            print(f"Error fetching filtered sales history: {e}")
            return []
