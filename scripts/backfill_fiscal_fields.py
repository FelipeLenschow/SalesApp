
import boto3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def backfill_columns():
    try:
        try:
            import src.embedded_credentials as embedded
        except ImportError:
             sys.path.append(os.path.join(os.getcwd(), 'src'))
             import embedded_credentials as embedded

        os.environ['AWS_ACCESS_KEY_ID'] = embedded.AWS_ACCESS_KEY_ID
        os.environ['AWS_SECRET_ACCESS_KEY'] = embedded.AWS_SECRET_ACCESS_KEY
        if hasattr(embedded, 'AWS_DEFAULT_REGION'):
             region = embedded.AWS_DEFAULT_REGION
        else:
             region = 'us-east-1'
    except ImportError:
        local_creds = os.path.join(os.getcwd(), '.aws', 'credentials')
        if os.path.exists(local_creds):
            os.environ['AWS_SHARED_CREDENTIALS_FILE'] = local_creds
            region = 'us-east-1'
        else:
            print("No credentials.")
            return

    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table('SalesApp_Products')
    
    print("Scanning SalesApp_Products...")
    
    scan_kwargs = {}
    done = False
    start_key = None
    count = 0
    updated = 0
    
    while not done:
        if start_key:
            scan_kwargs['ExclusiveStartKey'] = start_key
        response = table.scan(**scan_kwargs)
        start_key = response.get('LastEvaluatedKey')
        if not start_key:
            done = True
            
        items = response.get('Items', [])
        
        with table.batch_writer() as batch:
            for item in items:
                count += 1
                needs_update = False
                
                if 'ncm' not in item:
                    item['ncm'] = ""
                    needs_update = True
                
                if 'cest' not in item:
                    item['cest'] = ""
                    needs_update = True
                    
                if 'cfop' not in item:
                    item['cfop'] = "5102" # Default
                    needs_update = True
                    
                if 'tax_rule' not in item:
                    item['tax_rule'] = ""
                    needs_update = True
                
                if needs_update:
                    batch.put_item(Item=item)
                    updated += 1
                    
        print(f"Scanned {count}, Updated {updated}...")
        
    print(f"Backfill Complete. Updated {updated} items.")

if __name__ == "__main__":
    backfill_columns()
