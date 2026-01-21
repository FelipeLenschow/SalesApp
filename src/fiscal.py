
import json
import logging
import time
from datetime import datetime

class FiscalManager:
    """
    Manages Fiscal Invoice (NFC-e) generation and emission.
    Currently Mocked/Simulated for structure validation.
    """
    def __init__(self, cert_path=None, cert_password=None, token_csc=None, csc_id=None):
        self.cert_path = cert_path
        self.cert_password = cert_password
        self.token_csc = token_csc
        self.csc_id = csc_id
        # Future: Initialize API Client (e.g. NuvemFiscal, FocusNFe, eNotas) here.

    def validate_product_tax_data(self, product):
        """
        Validates if the product has necessary fiscal fields.
        Returns: (bool, str) -> (IsValid, ErrorMessage)
        """
        # For Mock/Dev purposes, we warn but allow default "00000000" if missing
        if not product.get('ncm'):
            print(f"WARNING: Produto {product.get('barcode')} sem NCM. Usando 00000000.")
            product['ncm'] = '00000000'
        
        if not product.get('cfop'):
             print(f"WARNING: Produto {product.get('barcode')} sem CFOP. Usando 5102.")
             product['cfop'] = '5102'

        return True, ""

    def prepare_sale_data(self, sale_items, total_price, payment_method, shop_details):
        """
        Structures the data for NFC-e emission.
        Follows a generic JSON structure adaptable to major APIs.
        """
        
        # 1. Validate Items
        for item in sale_items:
            is_valid, error = self.validate_product_tax_data(item)
            if not is_valid:
                raise ValueError(error)

        # 2. Map Payment Method to SEFAZ Code
        # 01=Dinheiro, 03=Cartão Crédito, 04=Cartão Débito, 17=PIX
        payment_map = {
            'money': '01',
            'credit': '03',
            'debit': '04',
            'pix': '17'
        }
        pay_code = payment_map.get(payment_method.lower(), '99') # 99=Outros

        # 3. Build Payload
        payload = {
            "timestamp": datetime.now().isoformat(),
            "natureza_operacao": "VENDA AO CONSUMIDOR",
            "tipo": "1", # 1=Saída
            "finalidade": "1", # 1=Normal
            "ambiente": "2", # 2=Homologação (Test)
            "emitente": {
                "cnpj": shop_details.get('cnpj', ''),
                "nome": shop_details.get('name', ''),
                "endereco": shop_details.get('address', ''),
                 # In real usage, State Registration (IE) and Tax Regime (CRT) are critical
                "ie": shop_details.get('ie', 'ISENTO'), 
                "crt": shop_details.get('crt', '1') # 1=Simples Nacional
            },
            "destinatario": None, # NFC-e usually anonymous
            "itens": [],
            "pagamento": {
                "forma": pay_code,
                "valor": total_price
            }
        }

        # 4. Process Items
        for idx, item in enumerate(sale_items):
            # Calculate item total
            # item dict should have: barcode, name (brand+cat+flavor), price, quantity, fiscal fields
            qtd = float(item.get('quantity', 1))
            unit_price = float(item.get('price', 0.0))
            
            # Construct Description
            desc_parts = [item.get('marca', ''), item.get('categoria', ''), item.get('sabor', '')]
            description = " ".join([p for p in desc_parts if p]).strip()
            if not description: description = "Produto Sem Nome"

            payload["itens"].append({
                "numero_item": idx + 1,
                "codigo_produto": item.get('barcode'),
                "descricao": description,
                "ncm": item.get('ncm'),
                "cest": item.get('cest', ''),
                "cfop": item.get('cfop'),
                "unidade": "UN", # Default
                "quantidade": qtd,
                "valor_unitario": unit_price,
                "valor_total": round(qtd * unit_price, 2),
                "regra_imposto": item.get('tax_rule', '') # Logic to expand 'Simples Nacional' to CSOSN codes would go here
            })

        return payload

    def emit_nfce(self, sale_data):
        """
        Mock emission.
        In reality, this would send 'sale_data' to an API.
        """
        print(f"[FiscalManager] Emitting NFC-e for {len(sale_data['itens'])} items...")
        
        # Simulate Network Latency
        time.sleep(1.0) 
        
        # Mock Response
        # Generate a fake Access Key (44 digits)
        # UF(2) + AAMM(4) + CNPJ(14) + MOD(2) + SERIE(3) + NUM(9) + TIPO(1) + CODE(8) + DV(1)
        fake_key = f"352401{sale_data['emitente']['cnpj'].zfill(14)}650010000000011000000001"
        
        return {
            "success": True,
            "message": "Nota Fiscal emitida com sucesso (MOCK)",
            "chave_acesso": fake_key,
            "numero": "1",
            "serie": "1",
            "url_xml": "http://mock.api/nfce/123.xml",
            "url_qrcode": "http://mock.api/nfce/qrcode/123", # This would be printed
            "xml_content": f"<nfeProc><NFe><infNFe Id='NFe{fake_key}'>...</infNFe><Signature>...</Signature></NFe><protNFe>...</protNFe></nfeProc>", # Mock Signed XML
            "data_emissao": datetime.now().isoformat()
        }
