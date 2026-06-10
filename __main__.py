"""Entry point for ``python -m PayrollWhatsAppSystem``."""

from gui import PayrollApp


def main() -> None:
    app = PayrollApp()
    app.mainloop()


if __name__ == "__main__":
    main()
