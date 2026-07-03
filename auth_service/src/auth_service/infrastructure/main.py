from auth_service.infrastructure.app import create_app
from auth_service.infrastructure.config import Config

app = create_app(Config())
