from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect
from typing import Optional

# Initialize Flask extensions here to avoid circular imports
db: SQLAlchemy = SQLAlchemy()
login_manager: LoginManager = LoginManager()
socketio: SocketIO = SocketIO()
csrf: CSRFProtect = CSRFProtect()

# Setup login manager
@login_manager.user_loader
def load_user(user_id: str) -> Optional["User"]:
    # Import inside function to avoid circular imports
    from models import User
    return User.query.get(int(user_id))
