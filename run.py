"""Start the BorrowLoop API:  python run.py   (then open http://127.0.0.1:5000/api/health)"""
import os
import sys

if sys.version_info < (3, 10):
    sys.exit(f"BorrowLoop needs Python 3.10 or newer (you have {sys.version.split()[0]}).")

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  BorrowLoop API running on http://{host}:{port}/api   (database: {app.config['DB_BACKEND']})\n")
    app.run(host=host, port=port, debug=app.config["DEBUG"], use_reloader=False)
