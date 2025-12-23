import flet as ft
from src.ui.gui import ProductApp
from src.updater import Updater

def main(page: ft.Page):
    Updater.update()
    ProductApp(page)

def run():
    ft.app(target=main)

if __name__ == "__main__":
    run()
