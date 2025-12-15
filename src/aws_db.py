
import boto3
from botocore.exceptions import ClientError
import json
import os
import decimal
import time

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
            # print("Using embedded credentials.")
            os.environ['AWS_ACCESS_KEY_ID'] = embedded.AWS_ACCESS_KEY_ID
            os.environ['AWS_SECRET_ACCESS_KEY'] = embedded.AWS_SECRET_ACCESS_KEY
            if hasattr(embedded, 'AWS_DEFAULT_REGION'):
                 region_name = embedded.AWS_DEFAULT_REGION
        except ImportError:
            # 2. Check for local credentials file in project root (dev mode)
            local_creds = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.aws', 'credentials')
            if os.path.exists(local_creds):
                # print(f"Using local credentials file: {local_creds}")
                os.environ['AWS_SHARED_CREDENTIALS_FILE'] = local_creds

        # Initialize DynamoDB resource
        # Ensure AWS credentials are set in environment or ~/.aws/credentials
        self.dynamodb = boto3.resource('dynamodb', region_name=region_name)
        
        # Table References
        self.public_shops_table = self.dynamodb.Table('SalesApp_PublicShops')
        self.products_table = self.dynamodb.Table('SalesApp_Products')
        self.sales_table = self.dynamodb.Table('SalesApp_Sales')
        
        # Initialize Tables if they don't exist (First Run)
        self.init_tables()
        
        # Cache for shops to mimic SQLite's quick lookup if needed, 
        # though DynamoDB is fast enough to query directly usually.
        self.shops = [] # Lazy load

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
                        KeySchema=[{'AttributeName': 'name', 'KeyType': 'HASH'}], # Partition Key
                        AttributeDefinitions=[{'AttributeName': 'name', 'AttributeType': 'S'}],
                        BillingMode='PAY_PER_REQUEST'
                    )
                    self.public_shops_table.wait_until_exists()
            
            # PRODUCTS TABLE
            # Strategy: Partition Key = barcode, Sort Key = shop_name
            # This allows efficient querying of a product across a specific shop or all shops
            try:
                self.products_table.load()
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print("Creating SalesApp_Products table...")
                    self.products_table = self.dynamodb.create_table(
                        TableName='SalesApp_Products',
                        KeySchema=[
                            {'AttributeName': 'barcode', 'KeyType': 'HASH'},    # Partition Key
                            {'AttributeName': 'shop_name', 'KeyType': 'RANGE'}  # Sort Key
                        ],
                        AttributeDefinitions=[
                            {'AttributeName': 'barcode', 'AttributeType': 'S'},
                            {'AttributeName': 'shop_name', 'AttributeType': 'S'}
                        ],
                        BillingMode='PAY_PER_REQUEST'
                    )
                    self.products_table.wait_until_exists()

            # SALES TABLE
            # Strategy: Partition Key = shop_name, Sort Key = timestamp
            try:
                self.sales_table.load()
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print("Creating SalesApp_Sales table...")
                    self.sales_table = self.dynamodb.create_table(
                        TableName='SalesApp_Sales',
                        KeySchema=[
                            {'AttributeName': 'shop_name', 'KeyType': 'HASH'},  # Partition Key
                            {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}   # Sort Key
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
            # Scan Public Shops Table
            response = self.public_shops_table.scan()
            items = response.get('Items', [])
            result = [item['name'] for item in items]
            self.shops = result
            return result
        except ClientError as e:
            print(f"Error fetching shops: {e}")
            return []


    # --- Product Management ---

    def add_product(self, product_info, shop_name):
        # We store price denormalized with the product for that shop (Single Table-ish row)
        barcode = product_info['barcode']
        category = product_info['categoria']
        flavor = product_info['sabor']
        price = product_info['preco'] # Decimal conversion happens automatically by boto3 usually, or we cast.

        try:
            self.products_table.put_item(
                Item={
                    'barcode': barcode,
                    'shop_name': shop_name,
                    'category': category,
                    'flavor': flavor,
                    'price': decimal.Decimal(str(price))
                }
            )
        except ClientError as e:
            print(f"Error adding product: {e}")
            raise e

    def delete_product(self, barcode, shop_name):
        """Deletes a product from the specific shop."""
        try:
            self.products_table.delete_item(
                Key={
                    'barcode': barcode,
                    'shop_name': shop_name
                }
            )
        except ClientError as e:
            print(f"Error deleting product: {e}")
            raise e

    def get_all_products(self, shop_name=None):
        """
        Returns list of product dictionaries.
        If shop_name is provided, filters by that shop.
        """
        try:
            if shop_name:
                # Scan with filter (since we don't have GSI on shop_name yet)
                response = self.products_table.scan(
                    FilterExpression=boto3.dynamodb.conditions.Attr('shop_name').eq(shop_name)
                )
            else:
                response = self.products_table.scan()
                
            items = response.get('Items', [])
            # Format to match what server/main.py expects (list of dicts)
            results = []
            for item in items:
                results.append({
                    'barcode': item['barcode'],
                    'categoria': item.get('category', ''),
                    'sabor': item.get('flavor', ''),
                    'preco': float(item.get('price', 0.0)),
                    'shop_name': item['shop_name']
                })
            return results
        except ClientError as e:
            print(f"Error fetching products: {e}")
            return []

    # --- Sales Management ---

    def record_sale(self, shop_name, sale_data):
        """
        Records a sale.
        sale_data expected: object or dict with timestamp, final_price, payment_method, products_json
        """
        try:
            # Handle both dict and object (pydantic style)
            if isinstance(sale_data, dict):
                timestamp = sale_data.get('timestamp')
                final_price = sale_data.get('final_price')
                payment_method = sale_data.get('payment_method')
                products_json = sale_data.get('products_json')
            else:
                timestamp = sale_data.timestamp
                final_price = sale_data.final_price
                payment_method = sale_data.payment_method
                products_json = getattr(sale_data, 'products_json', '')

            self.sales_table.put_item(
                Item={
                    'shop_name': shop_name,
                    'timestamp': timestamp,
                    'final_price': decimal.Decimal(str(final_price)),
                    'payment_method': payment_method,
                    'products_json': products_json
                },
            )
            return True
        except ClientError as e:
             print(f"Error recording sale: {e}")
             raise e
