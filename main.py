import flet as ft
from src.ui.gui import ProductApp

def main(page: ft.Page):
    app = ProductApp(page)

if __name__ == "__main__":
    ft.app(target=main)