from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uvicorn
import json
import sqlite3
import sys
import os

import db_sqlite as db
import threading

# Define data models
class SaleItem(BaseModel):
    timestamp: str
    final_price: float
    payment_method: str
    products_json: str

class SyncPayload(BaseModel):
    sales: List[SaleItem]
    shop_name: Optional[str] = None
    password: Optional[str] = None

app = FastAPI()
database = db.Database()

@app.get("/")
def read_root():
    return {"status": "online", "shop": "Master Server"}

@app.get("/shops")
def get_shops():
    try:
        with database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM shops")
            shops = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
        return {"shops": shops}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CreateShopPayload(BaseModel):
    new_name: str
    new_password: str
    source_name: Optional[str] = None
    source_password: Optional[str] = None

@app.post("/create_shop")
def create_shop(payload: CreateShopPayload):
    print(f"Request to create shop: {payload.new_name}")
    
    # 1. Check if source credentials are correct (if copying)
    if payload.source_name:
         with database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT password FROM shops WHERE name = ?", (payload.source_name,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Loja de origem não encontrada.")
            
            stored_pass = row[0] if row[0] is not None else ""
            input_pass = payload.source_password if payload.source_password is not None else ""
            
            if stored_pass != input_pass:
                raise HTTPException(status_code=401, detail="Senha da loja de origem incorreta.")

    # 2. Create the new shop
    success = database.create_shop(payload.new_name, payload.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="Uma loja com este nome já existe.")

    # 3. Copy data if requested
    copied_count = 0
    if payload.source_name:
        try:
            copied_count = database.copy_shop_data(payload.source_name, payload.new_name)
            print(f"Copied {copied_count} prices from {payload.source_name} to {payload.new_name}")
        except Exception as e:
            # If copy fails, should we delete the shop? For now, just report error.
            print(f"Error copying data: {e}")
            raise HTTPException(status_code=500, detail=f"Loja criada, mas erro ao copiar dados: {e}")

    return {"status": "success", "message": f"Loja '{payload.new_name}' criada com sucesso!", "copied_items": copied_count}

@app.post("/sync")
def sync_data(payload: SyncPayload):
    print(f"Received sync request from {payload.shop_name} with {len(payload.sales)} sales.")
    
    print(f"Received sync request from {payload.shop_name} with {len(payload.sales)} sales.")
    
    shop_id = None
    
    # 1. Verify Password & Get Shop ID logic (Moved to TOP for security)
    if payload.shop_name:
        # print(f"DEBUG: Validating password for shop='{payload.shop_name}'")
        try:
             with database.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, password, device, id_token, pos_name, user_id FROM shops WHERE name = ?", (payload.shop_name,))
                row = cursor.fetchone()
                shop_config = {}
                if row:
                    shop_id = row[0]
                    stored_password = row[1]
                    
                    # Store config for response
                    shop_config = {
                        "device": row[2],
                        "id_token": row[3],
                        "pos_name": row[4],
                        "user_id": row[5]
                    }
                    
                    # Normalize passwords for comparison (treat None as empty string)
                    db_pass = stored_password if stored_password is not None else ""
                    input_pass = payload.password if payload.password is not None else ""
                    
                    # Verify strictly
                    if db_pass != input_pass:
                        print(f"Unauthorized sync attempt for {payload.shop_name}")
                        raise HTTPException(status_code=401, detail="Senha incorreta.")
                else:
                    print(f"DEBUG: Shop '{payload.shop_name}' not found in DB during validation.")
                    raise HTTPException(status_code=404, detail="Loja não encontrada para validação.")
        except HTTPException:
            raise
        except Exception as e:
             print(f"Error verifying password: {e}")
             raise HTTPException(status_code=500, detail=str(e))
    else:
        # Require shop name for now? Or allow anonymous sync (fails to map shop_id)?
        # For this requirement, we need store id.
        raise HTTPException(status_code=400, detail="Shop name is required.")

    # 2. Insert received sales into Master DB (Now secured)
    count = 0
    try:
        with database.get_connection() as conn:
            cursor = conn.cursor()
            for sale in payload.sales:
                # Avoid duplicates: Check if timestamp + final_price matches (simple dedup)
                cursor.execute("""
                    INSERT INTO sales (shop_id, timestamp, final_price, payment_method, products_json)
                    SELECT ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM sales 
                        WHERE timestamp = ? AND final_price = ? AND shop_id = ?
                    )
                """, (shop_id, sale.timestamp, sale.final_price, sale.payment_method, sale.products_json,
                      sale.timestamp, sale.final_price, shop_id))
                if cursor.rowcount > 0:
                    count += 1
    except Exception as e:
        print(f"Error processing sales: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    print(f"Inserted {count} new sales for Shop ID {shop_id}.")

    # 2. Fetch latest Products to send back
    products = []
    try:
        with database.get_connection() as conn:
            
            cursor = conn.cursor()
            # Get all shops
            cursor.execute("SELECT id, name FROM shops")
            shops = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Filter by shop if provided
            if payload.shop_name:
                print(f"Filtering products for shop: {payload.shop_name}")
                query = """
                    SELECT p.barcode, p.category, p.flavor, pp.price, pp.shop_id
                    FROM products p
                    JOIN product_prices pp ON p.id = pp.product_id
                    JOIN shops s ON pp.shop_id = s.id
                    WHERE s.name = ?
                """
                cursor.execute(query, (payload.shop_name,))
            else:
                # Fallback: Send all (or logic for Master/Global)
                query = """
                    SELECT p.barcode, p.category, p.flavor, pp.price, pp.shop_id
                    FROM products p
                    JOIN product_prices pp ON p.id = pp.product_id
                """
                cursor.execute(query)

            for row in cursor.fetchall():
                shop_name = shops.get(row[4])
                if not shop_name: continue
                
                products.append({
                    'barcode': row[0],
                    'categoria': row[1],
                    'sabor': row[2],
                    'preco': row[3],
                    'shop_name': shop_name
                })
                
    except Exception as e:
        print(f"Error fetching products: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "imported_sales": count, "products_update": products, "shop_config": shop_config}

def start_server(host="0.0.0.0", port=8000):
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    start_server()
