import flet as ft
from src.gui_flet import ProductApp

def main(page: ft.Page):
    app = ProductApp(page)

if __name__ == "__main__":
    ft.app(target=main)