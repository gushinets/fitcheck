"""Third-party SDK imports must never read the developer's .env during tests."""
import os

os.environ['PYTHON_DOTENV_DISABLED'] = '1'
