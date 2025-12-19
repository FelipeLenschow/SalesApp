import flet as ft
import math
import ast
import json


class SalesHistoryDialog:
    def __init__(self, page, app):
        self.page = page
        self.app = app
        self.db = app.product_db
        self.dialog = ft.AlertDialog(
            title=ft.Text("Histórico de Vendas"),
            content=ft.Container(
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.ALWAYS,
                ),
            ),
        )
        self.load_data()

    def safe_parse_products(self, products_json):
        try:
            # Handle empty or None
            if not products_json:
                return {}
            # It should be a JSON string from the new DB
            if isinstance(products_json, str):
                return json.loads(products_json)
            # Fallback if it's already dict
            if isinstance(products_json, dict):
                return products_json
            return {}
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            return {}

    def format_products(self, produtos_dict):
        if not produtos_dict:
            return ["Nenhum produto registrado"]

        formatted_lines = []
        for product_id, details in produtos_dict.items():
            preco = details.get('preco', 0)
            if isinstance(preco, (int, float)):
                preco = f"R${preco:.2f}"
            else:
                preco = "R$0.00"

            line = (
                f"- {details.get('categoria', 'N/A')} ({details.get('sabor', 'N/A')}): "
                f"{details.get('quantidade', 0)} unidade(s) a {preco}"
            )
            formatted_lines.append(line)
        return formatted_lines

    def load_data(self):
        try:
            # Load from AWS DB
            sales_history = self.db.get_sales_history(shop_name=self.app.shop)
            
            # Helper to safely display values
            def safe_str(val):
                return str(val) if val is not None and val != 'None' and val != 'nan' else ""

            # Create header row
            header = ft.Row(
                controls=[
                    ft.Text("Data", width=150, weight=ft.FontWeight.BOLD),
                    ft.Text("Horário", width=100, weight=ft.FontWeight.BOLD),
                    ft.Text("Preço Final", width=150, weight=ft.FontWeight.BOLD),
                    ft.Text("Método Pagamento", width=200, weight=ft.FontWeight.BOLD),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
            self.dialog.content.content.controls.append(header)
            
            if not sales_history:
                 self.dialog.content.content.controls.append(
                    ft.Text("Nenhum histórico de vendas encontrado.", color=ft.Colors.GREY)
                )
                 return

            for row in sales_history:
                preco_final = row['Preco Final']
                if isinstance(preco_final, (int, float)):
                    preco_final = f"R${preco_final:.2f}"
                else:
                    preco_final = "R$0.00"

                produtos = self.safe_parse_products(row['Produtos'])

                ROW_STYLE = ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=5),
                    overlay_color=ft.Colors.TRANSPARENT,
                    surface_tint_color=ft.Colors.TRANSPARENT,
                    padding=10,
                    animation_duration=300,
                )

                row_content = ft.ListTile(
                    title=ft.Row(
                        controls=[
                            ft.Text(safe_str(row['Data']), width=150),
                            ft.Text(safe_str(row['Horario']), width=100),
                            ft.Text(preco_final, width=150),
                            ft.Text(safe_str(row['Metodo de pagamento']), width=200),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, color=ft.Colors.BLUE_GREY_400),
                    on_click=lambda e, p=produtos: self.show_product_details(p),
                    hover_color=ft.Colors.BLUE_GREY_800,
                    dense=True,
                )
                self.dialog.content.content.controls.append(row_content)

        except Exception as e:
            self.dialog.content.content.controls.append(
                ft.Text(f"Erro ao carregar histórico: {e}", color=ft.Colors.RED)
            )

    def show_product_details(self, produtos):
        formatted_lines = self.format_products(produtos)
        product_texts = [ft.Text(line) for line in formatted_lines]

        product_list = ft.ListView(
            expand=True,
            spacing=10,
            padding=20,
            controls=product_texts
        )

        self.bs = ft.BottomSheet(  # Store as instance variable
            ft.Container(
                ft.Column([
                    ft.Text("Detalhes dos Produtos", weight=ft.FontWeight.BOLD, size=18),
                    product_list,
                ]),
                padding=20,
            ),
            open=True,
            on_dismiss=lambda e: self.close_product_details()
        )
        self.page.overlay.append(self.bs)
        self.page.update()

    def close_product_details(self):
        self.bs.open = False
        self.page.overlay.remove(self.bs)
        self.page.update()

    def show(self):
        self.page.open(self.dialog)
        self.page.update()