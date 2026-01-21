
import boto3
import time
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botocore.exceptions import ClientError

def migrate():
    print("Starting Migration: V3 -> SalesApp_Products")
    
    # 1. Setup
    # 1. Setup
    try:
        try:
            import src.embedded_credentials as embedded
        except ImportError:
            try:
                import embedded_credentials as embedded
            except ImportError:
                 # Try adding src to path explicitly if running from root
                 sys.path.append(os.path.join(os.getcwd(), 'src'))
                 import embedded_credentials as embedded

        os.environ['AWS_ACCESS_KEY_ID'] = embedded.AWS_ACCESS_KEY_ID
        os.environ['AWS_SECRET_ACCESS_KEY'] = embedded.AWS_SECRET_ACCESS_KEY
        if hasattr(embedded, 'AWS_DEFAULT_REGION'):
             region = embedded.AWS_DEFAULT_REGION
        else:
             region = 'us-east-1'
        print("Loaded embedded credentials.")
    except ImportError:
        print("No embedded credentials. checking .aws/credentials")
        # Fallback to local .aws/credentials
        local_creds = os.path.join(os.getcwd(), '.aws', 'credentials')
        if os.path.exists(local_creds):
            os.environ['AWS_SHARED_CREDENTIALS_FILE'] = local_creds
            print(f"Using local file: {local_creds}")
            region = 'us-east-1'
        else:
            print("No credentials found!")
            return

    dynamodb = boto3.resource('dynamodb', region_name=region)
    
    table_source_name = 'SalesApp_Products_V3'
    table_target_name = 'SalesApp_Products'
    
    table_source = dynamodb.Table(table_source_name)
    
    # 2. Read Source (V3)
    print(f"Scanning source: {table_source_name}...")
    items = []
    try:
        done = False
        start_key = None
        while not done:
            if start_key:
                resp = table_source.scan(ExclusiveStartKey=start_key)
            else:
                resp = table_source.scan()
            items.extend(resp.get('Items', []))
            start_key = resp.get('LastEvaluatedKey')
            if not start_key:
                done = True
        print(f"Read {len(items)} items from source.")
    except Exception as e:
        print(f"Error reading source: {e}")
        return

    # 3. Delete Target if Exists (SalesApp_Products)
    # WARNING: We are deleting the TARGET, not the source.
    print(f"Checking target: {table_target_name}...")
    try:
        table_target = dynamodb.Table(table_target_name)
        try:
            table_target.load()
            print(f"Target table {table_target_name} exists. DELETING it to recreate clean...")
            table_target.delete()
            table_target.wait_until_not_exists()
            print("Target table deleted.")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print("Target table does not exist.")
            else:
                raise e
    except Exception as e:
        print(f"Error handling target table deletion: {e}")
        return

    # 4. Create Target Table
    print(f"Creating {table_target_name}...")
    try:
        # Schema must match V3: PK=product_id, GSI=BarcodeIndex
        new_table = dynamodb.create_table(
            TableName=table_target_name,
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
        print("Waiting for table creation...")
        new_table.wait_until_exists()
        print("Table created.")
    except Exception as e:
        print(f"Error creating table: {e}")
        return

    # 5. Write Data
    print(f"Writing {len(items)} items to {table_target_name}...")
    table_target = dynamodb.Table(table_target_name)
    
    with table_target.batch_writer() as batch:
        for i, item in enumerate(items):
            batch.put_item(Item=item)
            if i % 100 == 0:
                print(f"  Written {i} items...")
    
    print("Migration Complete!")

if __name__ == "__main__":
    migrate()
