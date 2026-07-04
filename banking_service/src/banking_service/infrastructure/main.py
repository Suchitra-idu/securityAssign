from banking_service.infrastructure.app import create_app
from banking_service.infrastructure.config import Config

app = create_app(Config())
