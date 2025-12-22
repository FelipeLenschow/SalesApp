import flet as ft
from src.ui.gui import ProductApp

def main(page: ft.Page):
    ProductApp(page)

def run():
    ft.app(target=main)

if __name__ == "__main__":
    run()
