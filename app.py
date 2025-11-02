from flask import Flask
from app import create_app

app = create_app()

with app.app_context():
    for rule in app.url_map.iter_rules():
        print(f"Endpoint: {rule.endpoint}, URL: {rule.rule}, Methods: {rule.methods}")

if __name__ == '__main__':
    app.run(debug=True)
