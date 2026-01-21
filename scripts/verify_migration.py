
import boto3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def verify():
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
    
    t1 = dynamodb.Table('SalesApp_Products_V3')
    t2 = dynamodb.Table('SalesApp_Products')
    
    # Simple count (scan)
    print("Counting V3...")
    c1 = t1.scan(Select='COUNT')['Count']
    print(f"V3 Has: {c1}")
    
    print("Counting SalesApp_Products...")
    try:
        c2 = t2.scan(Select='COUNT')['Count']
        print(f"New Has: {c2}")
        
        if c1 == c2:
            print("SUCCESS: Counts match.")
        else:
            print("WARNING: Counts mismatch.")
            
    except Exception as e:
        print(f"Error reading new table: {e}")

if __name__ == "__main__":
    verify()
