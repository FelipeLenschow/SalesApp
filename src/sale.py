import uuid

class Sale:
    def __init__(self, product_db, shop, payment_method=""):
        self.product_db = product_db
        self.shop = shop
        self.payment_method = payment_method
        self.current_sale = {}
        self.final_price = 0.0
        self.id = str(uuid.uuid4())

    def calculate_total(self):
        total_price = 0.0

        # Calcula o preço total (sem promoções)
        for product in self.current_sale.values():
            quantity = product['quantidade']
            price = product['preco']
            total_price += price * quantity

        self.final_price = total_price
        return self.final_price

    def add_product(self, product):
        product_id = product[('Metadata', 'Product ID')]
        if product_id not in self.current_sale or (type(product_id) == str and product_id.startswith('Manual')):
            self.current_sale[product_id] = {
                'categoria': product[('Todas', 'Categoria')],
                'sabor': product[('Todas', 'Sabor')],
                'preco': product[(self.shop, 'Preco')],
                'quantidade': 1,
                'product_id': product_id
            }
        else:
            self.current_sale[product_id]['quantidade'] += 1

    def remove_product(self, product_id):
        if product_id in self.current_sale:
            del self.current_sale[product_id]

    def update_quantity(self, product_id, quantity):
        if product_id in self.current_sale:
            self.current_sale[product_id]['quantidade'] = max(quantity, 0)
            if self.current_sale[product_id]['quantidade'] == 0:
                self.remove_product(product_id)

    def update_price(self, product_id, new_price):
        if product_id in self.current_sale:
            self.current_sale[product_id]['preco'] = new_price
