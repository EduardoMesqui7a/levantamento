# Project EAP Builder

MVP web app in Streamlit for engineering and architecture project takeoff.

## Features

- PDF upload
- Text extraction per page
- Optional OCR fallback
- GPT-powered EAP and materials extraction
- JSON and Excel export

## Setup

1. Install Python 3.12 or newer.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set environment variables:

```bash
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

For local development, you can also create a private file at `.streamlit/secrets.toml` with the same keys.
That file is ignored by Git and will be read automatically by Streamlit.

4. Run the app:

```bash
streamlit run app.py
```

## Streamlit Cloud Deploy

1. Push this repository to GitHub.
2. In Streamlit Cloud, create a new app from the repo.
3. Use `app.py` as the entrypoint.
4. Add secrets in the Streamlit Cloud dashboard:

```toml
OPENAI_API_KEY = "your_key_here"
OPENAI_MODEL = "gpt-4o-mini"
```

5. Deploy the app.

## Notes

- The app starts in PDF-only mode.
- If the OpenAI key is missing, a heuristic fallback output is generated for testing the UI flow.
- The exposed API key in the chat should be rotated before production use.
