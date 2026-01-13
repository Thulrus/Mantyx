# Example Mantyx Application

This is a simple example application that demonstrates how to create apps for Mantyx.

## Structure

- `main.py` - The entrypoint for the application
- `requirements.txt` - Python dependencies

## Running Locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Deploying to Mantyx

1. Zip this directory: `zip -r example-app.zip .`
2. Upload via Mantyx web interface
3. Install dependencies
4. Enable and start the app
